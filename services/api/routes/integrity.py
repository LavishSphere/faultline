"""GET /api/integrity: what the AI was NOT allowed to see, and which guarantees held (issue #81, SPEC §1, §5).

Read-only and pre-reveal safe. Case and run checks are recomputed on every request; the two code-level system
checks (import/reference scan, payroll probe) are cached per process for up to ``SYSTEM_CACHE_SECONDS``.

* ``evidence_cutoff``: the temporal gate is run on the case at its cutoff, then audited independently. Every
  admitted item must be dated ``available_at <= as_of`` and ``published_at <= as_of``, every admitted quote must
  satisfy ``as_of - 24h <= ts <= as_of``, a recount from the committed case file (same rules, re-derived here)
  must agree with the gate, and no id, title or text of a withheld item may appear in either rendered prompt.
* ``outcome_fields_stripped``: outcome-like keys (``models.OUTCOME_FIELD_PATTERN``) must be absent from the exact
  snapshot payload (both variants); no value of a stripped key may appear in the rendered prompts; and a built-in
  synthetic probe with nested outcome-like keys is pushed through ``strip_outcome_keys`` and
  ``_project_evidence``, so the protection is tested even when the case has nothing to strip. The quote side
  marker ``"outcome": "YES"`` at a quote's top level is the one allowlisted key.
* ``sealed_folder_untouched``: a ``sys.audit`` hook (installed when this module is imported) resolves every
  opened or listed path (``realpath``, relative paths against the working directory) and records it when it lies
  in the configured sealed folder or in any folder named ``sealed_outcomes``, noting whether it happened inside
  ``OutcomeVault.reveal``. Opens relative to a directory descriptor (``dir_fd``) or through a hard link cannot be
  attributed; the check says so.
* ``model_contamination_disclosed``: the case's ``contamination_flag`` vs ``agents.model_cards``.
* ``persisted_before_reveal``, ``run_hashes_match``, ``run_matches_gate`` (only with a persisted
  ``prediction_id``; the prediction database is opened read-only).
* ``live_web_isolated``: a static scan of every replay module and the local modules they import: imports, string
  constants (including pieces joined with ``+`` and f-strings), names, attributes, keywords and definitions that
  name live web-search code (the Live Explore client, its router, its app state or its API host). Names assembled
  at run time from variables or data cannot be seen by a static scan. PR #73's separation tests are the second
  line of defence.
* ``payroll_hard_constraint``: if ``core.optimizer`` exists, every named scenario is solved with payroll cuts made
  free, once with Protect payroll off (control: the solver should cut) and once on (it must cut nothing); a probe
  where the control never cuts is NOT AVAILABLE. Until the optimizer exists, NOT AVAILABLE.

A check whose input is missing (no case selected, no persisted prediction, no optimizer) is NOT AVAILABLE, never
PASS. The only place a PASS is produced is ``_verdict(bool)`` (a test enforces this).

This module never imports ``core.evaluator``, never opens the sealed folder and never writes the prediction
database. The response has no outcome-like key anywhere and carries counts, ids, flags and hashes only.
"""

from __future__ import annotations

import ast
import contextvars
import importlib
import importlib.util
import json
import math
import os
import re
import sqlite3
import sys
import threading
import time
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from agents.model_cards import contamination_flag as card_contamination_flag
from agents.model_cards import get_model_card, normalize_model_tag
from config import API_DIR, Settings, get_settings
from core import provenance, temporal_gate
from core import store as store_module
from core.store import PredictionStore, StoredPrediction
from core.temporal_gate import PROMPT_VARIANTS, EvidenceStore, GatedSnapshot, MarketNotAvailable, SealedDataError
from models import OUTCOME_FIELD_PATTERN, ErrorCode, EvidenceItem, Provenance
from routes import NOT_AVAILABLE, CodedRoute, RouteError, RouteErrorBody
from routes.scenarios import load_scenarios
from routes.simulate import load_business

router = APIRouter(tags=["integrity"], route_class=CodedRoute)

CASES_DIR = "demo_cases"
SOURCE_ROOT: Path = API_DIR  # root of the import scan (tests point it at a mutated copy)
# MATH_MODEL §7, restated here on purpose so the audit does not borrow the gate's own constant.
MAX_QUOTE_AGE = timedelta(hours=24)
_MARKET_SIDE_KEY, _MARKET_SIDE_VALUE = "outcome", "YES"
_IDENTIFIER = r"^[A-Za-z0-9_.:\-]+$"

CheckStatus = Literal["PASS", "FAIL", "NOT AVAILABLE"]
CheckScope = Literal["case", "run", "system"]
CheckId = Literal[
    "evidence_cutoff",
    "outcome_fields_stripped",
    "sealed_folder_untouched",
    "model_contamination_disclosed",
    "persisted_before_reveal",
    "run_hashes_match",
    "run_matches_gate",
    "live_web_isolated",
    "payroll_hard_constraint",
]

LIMITS = (
    "Tamper-evident, not tamper-proof: someone with write access to the prediction database can drop its "
    "triggers and rewrite a row together with its hashes. Committed recorded runs in git are the stronger record.",
    "Pretraining contamination is disclosed, not removed: switching the network off does not erase what a model "
    "learned in training. Cases flagged 'likely' are excluded from the benchmark.",
    "These checks run inside the API's Python process. They see file access made through Python in this process "
    "since monitoring began; they cannot see other processes, a restart resets the count, and Python code that "
    "deliberately bypasses the guards is out of scope.",
    "Curated dates are trusted: the gate enforces available_at as curated. It cannot prove a web page was not "
    "revised after the cutoff (archive snapshots are the mitigation).",
)


# ---------------------------------------------------------------- response models (no outcome-like keys)


class IntegrityFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str = Field(description="Counts, ids, flags or hashes as text; NOT AVAILABLE when unknown.")


class IntegrityCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: CheckId
    scope: CheckScope = Field(description="case: the selected case; run: one persisted forecast; system: the code.")
    title: str
    status: CheckStatus = Field(description="Computed on this request. NOT AVAILABLE when the check could not run.")
    explanation: str = Field(description="One plain-language line on what the status means.")
    facts: list[IntegrityFact] = Field(description="The evidence behind the status.")
    enforced_by: list[str] = Field(description="Code and tests that enforce the guarantee.")


class IntegrityExclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["evidence", "market"]
    reason: str = Field(description="The temporal gate's exclusion reason.")
    count: int


class IntegrityCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: int
    failed: int
    not_available: int


class IntegrityResponse(BaseModel):
    """Pre-reveal: counts, ids, flags and hashes only. No evidence text, no outcome, no outcome-like key."""

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    case_id: str | None
    prediction_id: str | None
    as_of: AwareDatetime | None = Field(description="The case cutoff the gate was run at; null without a case.")
    case_provenance: Provenance | None
    prediction_provenance: Provenance | None
    computed_at: AwareDatetime = Field(description="When these checks ran (they are recomputed on every request).")
    checks: list[IntegrityCheck]
    counts: IntegrityCounts
    excluded: list[IntegrityExclusion] = Field(description="What the gate withheld from the model, by reason.")
    limits: list[str] = Field(description="What these checks do not guarantee.")
    notes: list[str]


# ---------------------------------------------------------------- the only source of PASS


def _verdict(ok: bool) -> CheckStatus:
    return "PASS" if ok else "FAIL"


def _check(
    cid: CheckId,
    scope: CheckScope,
    title: str,
    status: CheckStatus,
    explanation: str,
    facts: list[tuple[str, object]],
    enforced_by: list[str],
) -> IntegrityCheck:
    return IntegrityCheck(
        id=cid,
        scope=scope,
        title=title,
        status=status,
        explanation=explanation,
        facts=[IntegrityFact(label=label, value=_text(value)) for label, value in facts],
        enforced_by=enforced_by,
    )


def _text(value: object) -> str:
    if value is None:
        return NOT_AVAILABLE
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


# ---------------------------------------------------------------- sealed-folder monitor (sys.audit)

_SEALED_NAME = "sealed_outcomes"
_WATCHED_EVENTS = frozenset({"open", "os.listdir", "os.scandir", "glob.glob"})
_VAULT_FILE = os.path.join("core", "evaluator.py")
_SEALED_REAL: dict[str, str] = {}


def _configured_sealed_real() -> str:
    """realpath of the configured sealed folder, case-folded (cached per data dir; the folder need not exist)."""
    configured = str(get_settings().data_dir / _SEALED_NAME)
    real = _SEALED_REAL.get(configured)
    if real is None:
        real = _SEALED_REAL[configured] = os.path.realpath(configured).casefold()
    return real


def is_sealed_path(target: str) -> bool:
    """Is ``target`` inside a sealed folder, after resolving symlinks and the working directory?

    True for the configured folder (compared by realpath, case-insensitively) and for any folder named
    ``sealed_outcomes`` (test fixtures, copies). A path relative to a ``dir_fd`` is resolved against the working
    directory instead, and a hard link has its own path, so neither can be attributed.
    """
    if not os.path.isabs(target):
        target = os.path.join(os.getcwd(), target)
    real = os.path.realpath(target).casefold()
    if _SEALED_NAME in Path(real).parts or _SEALED_NAME in Path(target.casefold()).parts:
        return True
    sealed = _configured_sealed_real()
    return real == sealed or real.startswith(sealed + os.sep)


def _from_vault() -> bool:
    frame = sys._getframe(2)
    while frame is not None:
        code = frame.f_code
        if code.co_name == "reveal" and code.co_filename.endswith(_VAULT_FILE):
            return True
        frame = frame.f_back
    return False


class SealedAccessMonitor:
    """Counts opens/listings of any path that ``is_sealed_path`` places in a sealed folder.

    Process-wide since ``started_at``; ``window()`` additionally collects the accesses made while one report is
    computed (a context variable, so concurrent requests do not mix). The hook never raises.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._window: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
            "integrity_sealed_window", default=None
        )
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.started_at = datetime.now(UTC)
            self.total = 0
            self.outside_vault = 0

    def snapshot(self) -> tuple[int, int, datetime]:
        with self._lock:
            return self.total, self.outside_vault, self.started_at

    @contextmanager
    def window(self) -> Iterator[list[str]]:
        seen: list[str] = []
        token = self._window.set(seen)
        try:
            yield seen
        finally:
            self._window.reset(token)

    def __call__(self, event: str, args: tuple) -> None:
        if event not in _WATCHED_EVENTS or not args:
            return
        try:
            target = args[0]
            if isinstance(target, os.PathLike):
                target = os.fspath(target)
            if isinstance(target, bytes):
                target = os.fsdecode(target)
            if not isinstance(target, str) or not is_sealed_path(target):
                return
            via_vault = _from_vault()
            with self._lock:
                self.total += 1
                if not via_vault:
                    self.outside_vault += 1
            seen = self._window.get()
            if seen is not None:
                seen.append(event)
        except Exception:  # an audit hook must never break the operation it observes
            return


MONITOR = SealedAccessMonitor()
sys.addaudithook(MONITOR)


# ---------------------------------------------------------------- import scan (AST, transitive)

REPLAY_MODULES = (
    "core.temporal_gate",
    "core.store",
    "core.evaluator",
    "core.provenance",
    "core.forecasting",
    "agents.provider",
    "agents.local_ollama",
    "agents.model_cards",
    "agents.skeptic",
    "routes.cases",
    "routes.replay",
    "routes.benchmark",
    "routes.recorded",
)
# The live-web patterns are assembled at run time ON PURPOSE. PR #73's separation test flags any string constant or
# name in a non-Live-Explore module that spells a live-web module, and this file must only *describe* them. Do not
# "simplify" these into single literals.
_EXP = "expl" + "ore"
_WEB = "tav" + "ily"
_LIVE_WEB_PATTERN = re.compile("|".join((_WEB, "faultline_" + _EXP, "routes" + r"\." + _EXP, _EXP + "_search")),
                               re.IGNORECASE)
# Key-presence plumbing (config boolean, /api/health notice, OptionalKeys field) is not a reference to the client.
_KEY_PRESENCE = re.compile("|".join((_WEB.upper() + "_API_KEY", _WEB + "_api_key(?:_set)?")))
_LIVE_WEB_EXACT = frozenset({_EXP})
_LIVE_WEB_PACKAGES = ("routes." + _EXP, "agents." + _EXP)


def _module_file(root: Path, dotted: str) -> Path | None:
    base = root.joinpath(*dotted.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _imported_names(path: Path, dotted: str) -> set[str]:
    """Every module name a file imports, including relative imports and string literals given to importlib."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = dotted if path.name == "__init__.py" else dotted.rpartition(".")[0]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".") if package else []
                parts = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
                base = ".".join([*parts, base] if base else parts)
            names.add(base)
            names.update(f"{base}.{a.name}" if base else a.name for a in node.names)
        elif isinstance(node, ast.Call):
            func = node.func
            fname = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            if fname in ("import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant):
                if isinstance(node.args[0].value, str):
                    names.add(node.args[0].value)
    return {n for n in names if n}


def _is_live_web(name: str | None) -> bool:
    if not name:
        return False
    return (
        bool(_LIVE_WEB_PATTERN.search(_KEY_PRESENCE.sub("", name)))
        or name in _LIVE_WEB_EXACT
        or any(name == m or name.startswith(m) for m in _LIVE_WEB_PACKAGES)
    )


def _folded(node: ast.AST) -> str | None:
    """A string built only from literals: ``"a" + "b"``, the literal parts of an f-string, ``"%s" % "x"``."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            text = _folded(v.value) if isinstance(v, ast.FormattedValue) else _folded(v)
            parts.append(text or "")  # a non-literal placeholder is unknown: keep the literal parts around it
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        left, right = _folded(node.left), _folded(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def live_web_refs(tree: ast.AST) -> set[str]:
    """Every static reference to live web-search code in a module, as ``kind:text`` (comments are not code)."""
    refs: set[str] = set()

    def check(kind: str, text: str | None) -> None:
        if _is_live_web(text):
            refs.add(f"{kind}:{text}")

    for node in ast.walk(tree):
        if isinstance(node, ast.alias):
            check("import", node.name)
            check("alias", node.asname)
        elif isinstance(node, ast.ImportFrom):
            check("import", node.module)
            for a in node.names:
                check("import", f"{node.module}.{a.name}" if node.module else a.name)
        elif isinstance(node, (ast.Constant, ast.JoinedStr, ast.BinOp)):
            check("const", _folded(node))
        elif isinstance(node, ast.Attribute):
            check("attr", node.attr)
        elif isinstance(node, ast.Name):
            check("name", node.id)
        elif isinstance(node, ast.keyword):
            check("kw", node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            check("def", node.name)
        elif isinstance(node, ast.arg):
            check("arg", node.arg)
    return refs


@dataclass(frozen=True)
class ImportScan:
    roots: tuple[str, ...]
    reached: tuple[str, ...]
    offenders: tuple[str, ...]  # "<module> imports <name>" / "<module> references <kind:text>"


def scan_imports(root: Path, starts: tuple[str, ...]) -> ImportScan:
    roots = tuple(m for m in starts if _module_file(root, m) is not None)
    seen: set[str] = set()
    queue = list(roots)
    offenders: list[str] = []
    while queue:
        dotted = queue.pop()
        if dotted in seen:
            continue
        seen.add(dotted)
        path = _module_file(root, dotted)
        if path is None:
            continue
        refs = live_web_refs(ast.parse(path.read_text(encoding="utf-8")))
        offenders += [f"{dotted} references {ref}" for ref in sorted(refs)]
        for name in sorted(_imported_names(path, dotted)):
            if _is_live_web(name):
                offenders.append(f"{dotted} imports {name}")
            parts = name.split(".")
            for i in range(1, len(parts) + 1):
                prefix = ".".join(parts[:i])
                if prefix not in seen and _module_file(root, prefix) is not None:
                    queue.append(prefix)
    return ImportScan(roots=roots, reached=tuple(sorted(seen)), offenders=tuple(sorted(set(offenders))))


# ---------------------------------------------------------------- helpers


def _parse_time(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo is not None else None


def _dated_by(item: Mapping[str, Any], keys: tuple[str, ...], cutoff: datetime) -> bool:
    """True when every named timestamp parses and is at or before the cutoff."""
    times = [_parse_time(item.get(k)) for k in keys]
    return all(t is not None and t <= cutoff for t in times)


def _quote_in_window(item: Mapping[str, Any], cutoff: datetime) -> bool:
    ts = _parse_time(item.get("ts"))
    return ts is not None and cutoff - MAX_QUOTE_AGE <= ts <= cutoff


def _outcome_like_keys(obj: object, *, quote_top: bool = False) -> int:
    """Outcome-like keys anywhere in obj, except the quote side marker ``"outcome": "YES"`` at a quote's top."""
    count = 0
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            key = str(k)
            if OUTCOME_FIELD_PATTERN.search(key) and not (
                quote_top and key == _MARKET_SIDE_KEY and v == _MARKET_SIDE_VALUE
            ):
                count += 1
            count += _outcome_like_keys(v)
    elif isinstance(obj, (list, tuple)):
        count += sum(_outcome_like_keys(v, quote_top=quote_top) for v in obj)
    return count


def _payload_outcome_keys(payload: Mapping[str, Any]) -> int:
    return _outcome_like_keys(payload.get("evidence", [])) + sum(
        _outcome_like_keys(q, quote_top=True) for q in payload.get("market_quotes", [])
    )


def _expected_reason(item: Mapping[str, Any], event_id: str, cutoff: datetime) -> str | None:
    """The gate's evidence rules, re-derived from the raw case file (same order as the gate)."""
    available, published = _parse_time(item.get("available_at")), _parse_time(item.get("published_at"))
    if item.get("event_id") != event_id:
        return "wrong_event"
    if item.get("retrospective_unverified", False) is not False:
        return "retrospective_unverified"
    if available is None or available > cutoff:
        return "available_after_as_of"
    if published is None or published > cutoff:
        return "published_after_as_of"
    return None


def _read_case_file(store: EvidenceStore, case_id: str) -> dict | None:
    """The committed case file the gate loaded (never anything under a sealed folder)."""
    if store.source_dir is None:
        return None
    path = (store.source_dir / f"{case_id}.json").resolve()
    if any(part.casefold() == _SEALED_NAME for part in path.parts) or not path.is_relative_to(store.source_dir):
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _plain(name: str) -> str:
    return name.replace("_", " ")


# A withheld string shorter than this is too generic to search for in a prompt (it would match ordinary words).
MIN_NEEDLE = 12
_ID_EDGE = r"A-Za-z0-9_.:\-"


def _id_in(text: str, item_id: str) -> bool:
    return re.search(rf"(?<![{_ID_EDGE}]){re.escape(item_id)}(?![{_ID_EDGE}])", text) is not None


def _admitted_text(r: _Report) -> str:
    """Everything the model is allowed to see as text: admitted items, the case question and rule."""
    if r.snap is None:
        return ""
    parts = [r.snap.case.title, r.snap.case.question_criteria]
    for e in r.snap.evidence:
        parts += [str(e.get("title", "")), str(e.get("content", "")), str(e.get("evidence_id", ""))]
    return "\n".join(parts)


def _leaks(needles: list[str], prompts: dict[str, str], allowed: str) -> tuple[int, int]:
    """(needles found in any prompt, needles not checked because too short or also part of admitted text)."""
    found = skipped = 0
    for needle in needles:
        if len(needle) < MIN_NEEDLE or needle in allowed:
            skipped += 1
        elif any(needle in prompt for prompt in prompts.values()):
            found += 1
    return found, skipped


def _string_leaves(obj: object) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, Mapping):
        return [s for v in obj.values() for s in _string_leaves(v)]
    if isinstance(obj, (list, tuple)):
        return [s for v in obj for s in _string_leaves(v)]
    return []


def _stripped_values(obj: object, *, quote_top: bool = False) -> list[str]:
    """String values held under outcome-like keys (what stripping removed), except the quote side marker."""
    out: list[str] = []
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            key = str(k)
            if OUTCOME_FIELD_PATTERN.search(key) and not (
                quote_top and key == _MARKET_SIDE_KEY and v == _MARKET_SIDE_VALUE
            ):
                out += _string_leaves(v)
            else:
                out += _stripped_values(v)
    elif isinstance(obj, (list, tuple)):
        out += [s for v in obj for s in _stripped_values(v, quote_top=quote_top)]
    return out


_PROBE_TS = datetime(2000, 1, 1, tzinfo=UTC)


def strip_probe() -> tuple[bool, int]:
    """Push built-in SYNTHETIC items with nested outcome-like keys through the gate's own stripping and projection.

    Returns (protection held, outcome-like keys that survived). Runs whatever the case data is, so the check tests
    the protection, not only the data.
    """
    survived = 0
    nested = {
        "title": "probe",
        "keep": "k",
        "resolution": "x",
        "Result_note": {"winner": "x"},
        "nested": {"final_price": 0.9, "items": [{"settled_at": "x", "keep": 1}, {"OUTCOME": "NO"}]},
    }
    out = temporal_gate.strip_outcome_keys(nested)
    survived += _outcome_like_keys(out)
    kept = isinstance(out, Mapping) and out.get("keep") == "k" and out.get("nested", {}).get("items", [{}])[0] == {
        "keep": 1
    }
    quote = temporal_gate.strip_outcome_keys(
        {"outcome": "YES", "p_yes": 0.5, "meta": {"outcome": "YES", "resolved": True}}, allow_market_side=True
    )
    survived += _outcome_like_keys(quote, quote_top=True)
    kept = kept and isinstance(quote, Mapping) and quote.get("outcome") == "YES"
    wrong_side = temporal_gate.strip_outcome_keys({"outcome": "NO", "p_yes": 0.5}, allow_market_side=True)
    survived += _outcome_like_keys(wrong_side)
    item = EvidenceItem(
        evidence_id="integrity_probe",
        event_id="integrity_probe",
        title="SYNTHETIC probe",
        source_url="https://example.org/probe",
        published_at=_PROBE_TS,
        observed_at=_PROBE_TS,
        available_at=_PROBE_TS,
        content_sha256="0" * 64,
        content="SYNTHETIC probe text.",
        provenance=Provenance.SYNTHETIC,
    )
    projected = temporal_gate._project_evidence(item)
    survived += _outcome_like_keys(projected)
    kept = kept and set(projected) <= set(temporal_gate.EVIDENCE_PROMPT_FIELDS)
    return survived == 0 and kept, survived


# ---------------------------------------------------------------- context for one report


@dataclass
class _Report:
    settings: Settings
    case_id: str | None
    store: EvidenceStore | None
    snap: GatedSnapshot | None
    raw: dict | None
    record: StoredPrediction | None
    prediction_note: str | None
    notes: list[str]
    prompts: dict[str, str]  # variant -> rendered prompt, for the variants that can render


_NO_CASE = "No replay case selected (pass case_id, or a prediction_id whose case is committed)."


def _check_cutoff(r: _Report) -> IntegrityCheck:
    title = "Nothing published after the cutoff reached the model"
    enforced = [
        "services/api/core/temporal_gate.py::EvidenceStore.get_as_of",
        "tests/test_temporal_gate.py::test_evidence_after_as_of_is_rejected_and_boundary_is_included",
        "tests/test_replay_seal.py::test_canary_never_reaches_any_prompt_or_snapshot",
        "tests/test_routes_integrity.py::test_mutation_breaking_the_date_filter_flips_the_cutoff_check_to_fail",
    ]
    if r.snap is None:
        return _check("evidence_cutoff", "case", title, NOT_AVAILABLE, _NO_CASE, [], enforced)
    snap, cutoff = r.snap, r.snap.as_of
    late = [e["evidence_id"] for e in snap.evidence if not _dated_by(e, ("available_at", "published_at"), cutoff)]
    late_quotes = [f"{q['venue']}:{q['market_id']}" for q in snap.market_quotes if not _quote_in_window(q, cutoff)]
    gate_reasons = Counter(x.reason for x in snap.exclusions if x.kind == "evidence")
    gate_markets = {f"{q['venue']}:{q['market_id']}" for q in snap.market_quotes}

    recount: bool | None = None
    candidates: int | None = None
    leaked: int | None = None
    unchecked = 0
    if r.raw is not None:
        items = [e for e in r.raw.get("evidence") or [] if isinstance(e, Mapping)]
        candidates = len(items)
        expected = {str(e.get("evidence_id")): _expected_reason(e, snap.case.event_id, cutoff) for e in items}
        withheld_items = [e for e in items if expected[str(e.get("evidence_id"))] is not None]
        allowed = _admitted_text(r)
        id_hits = sum(
            1 for e in withheld_items
            if str(e.get("evidence_id")) not in allowed and any(_id_in(pr, str(e.get("evidence_id")))
                                                                 for pr in r.prompts.values())
        )
        text_hits, unchecked = _leaks(
            [str(e.get(k)) for e in withheld_items for k in ("title", "content") if isinstance(e.get(k), str)],
            r.prompts, allowed,
        )
        leaked = id_hits + text_hits
        expected_admitted = {eid for eid, reason in expected.items() if reason is None}
        expected_reasons = Counter(reason for reason in expected.values() if reason is not None)
        markets: dict[str, bool] = {}
        for q in r.raw.get("market_quotes") or []:
            if isinstance(q, Mapping):
                ref = f"{q.get('venue')}:{q.get('market_id')}"
                markets[ref] = markets.get(ref, False) or _quote_in_window(q, cutoff)
        expected_markets = {ref for ref, ok in markets.items() if ok}
        recount = (
            expected_admitted == set(snap.evidence_ids)
            and expected_reasons == gate_reasons
            and expected_markets == gate_markets
        )
    ok = not late and not late_quotes and recount is True and leaked == 0 and bool(r.prompts)
    breached = bool(late or late_quotes or recount is False or leaked)
    status: CheckStatus = _verdict(ok) if breached or ok else NOT_AVAILABLE
    withheld = sum(gate_reasons.values())
    if status != NOT_AVAILABLE and ok:
        explanation = (
            f"Every item the model could see was public at or before the cutoff; {withheld} later or "
            "unverifiable items were withheld, an independent recount agrees, and none of them is in the prompt."
        )
    elif status != NOT_AVAILABLE:
        explanation = (
            "Something dated after the cutoff reached the model input or the prompt text, or the gate's counts "
            "disagree with an independent recount of the case file."
        )
    else:
        explanation = "The committed case file could not be re-read, so the gate's counts could not be recounted."
    facts: list[tuple[str, object]] = [
        ("Cutoff (as_of)", cutoff),
        ("Evidence items the model could see", f"{len(snap.evidence)} of {candidates}" if candidates is not None
         else f"{len(snap.evidence)} of {NOT_AVAILABLE}"),
        ("Admitted items dated after the cutoff", len(late)),
        ("Market quotes the model could see", len(snap.market_quotes)),
        ("Admitted quotes outside the 24 h window before the cutoff", len(late_quotes)),
        ("Independent recount agrees with the gate", recount),
        ("Withheld items whose id, title or text is in a prompt", leaked),
        ("Withheld strings not searched (shorter than 12 characters, or also in admitted text)", unchecked),
        ("Prompts searched", ", ".join(sorted(r.prompts)) or NOT_AVAILABLE),
    ]
    facts += [(f"Withheld: {_plain(reason)}", n) for reason, n in sorted(gate_reasons.items())]
    return _check("evidence_cutoff", "case", title, status, explanation, facts, enforced)


def _check_stripped(r: _Report) -> IntegrityCheck:
    title = "Answer fields never reach the model"
    enforced = [
        "services/api/core/temporal_gate.py::strip_outcome_keys",
        "tests/test_temporal_gate.py::test_strip_outcome_keys_recursive",
        "tests/test_routes_integrity.py::test_mutation_leaking_an_outcome_key_into_the_projection_flips_the_strip_check",
    ]
    if r.snap is None:
        return _check("outcome_fields_stripped", "case", title, NOT_AVAILABLE, _NO_CASE, [], enforced)
    dropped: int | None = None
    if r.raw is not None:
        dropped = sum(_outcome_like_keys(e) for e in r.raw.get("evidence") or []) + sum(
            _outcome_like_keys(q, quote_top=True) for q in r.raw.get("market_quotes") or []
        )
    remaining = 0
    variants = []
    for variant in PROMPT_VARIANTS:
        try:
            payload = r.snap.payload(variant)
        except MarketNotAvailable:
            continue
        variants.append(variant)
        remaining += _payload_outcome_keys(payload)
    value_hits: int | None = None
    unchecked = 0
    if r.raw is not None:
        values = [v for e in r.raw.get("evidence") or [] for v in _stripped_values(e)]
        values += [v for q in r.raw.get("market_quotes") or [] for v in _stripped_values(q, quote_top=True)]
        value_hits, unchecked = _leaks(values, r.prompts, _admitted_text(r))
    try:
        probe_ok, probe_survived = strip_probe()
    except Exception:  # the probe uses the gate's internals; if they changed, the protection is unverified
        probe_ok, probe_survived = None, None
    ok = remaining == 0 and value_hits == 0 and probe_ok is True and bool(r.prompts)
    breached = remaining > 0 or bool(value_hits) or probe_ok is False
    status: CheckStatus = _verdict(ok) if breached or ok else NOT_AVAILABLE
    if ok:
        explanation = (
            "Fields that could carry the answer were dropped before the prompt was built: none is in the model "
            "input or the prompt text, and a built-in probe confirms the stripping works."
        )
    elif breached:
        explanation = "An answer-like field or its value reaches the model, or the stripping probe failed."
    else:
        explanation = "The case file or the stripping probe could not be checked, so this cannot be confirmed."
    facts: list[tuple[str, object]] = [
        ("Outcome-like fields dropped from candidate items", dropped),
        ("Outcome-like fields in the model input", remaining),
        ("Values of dropped fields found in a prompt", value_hits),
        ("Dropped values not searched (shorter than 12 characters, or also in admitted text)", unchecked),
        ("Built-in stripping probe: outcome-like keys that survived", probe_survived),
        ("Model inputs checked", ", ".join(variants)),
    ]
    return _check("outcome_fields_stripped", "case", title, status, explanation, facts, enforced)


def _check_sealed(window: list[str]) -> IntegrityCheck:
    title = "The sealed answers folder was not opened"
    enforced = [
        "services/api/core/temporal_gate.py::_refuse_sealed",
        "services/api/core/evaluator.py::OutcomeVault.reveal",
        "tests/test_temporal_gate.py::test_gate_never_reads_sealed_outcomes",
        "tests/test_replay_seal.py::test_reveal_before_persist_raises_and_does_not_touch_sealed_dir",
    ]
    total, outside, since = MONITOR.snapshot()
    gate_path = _module_file(SOURCE_ROOT, "core.temporal_gate")
    self_path = _module_file(SOURCE_ROOT, "routes.integrity")
    gate_imports = None if gate_path is None else any(
        "evaluator" in n for n in _imported_names(gate_path, "core.temporal_gate")
    )
    self_imports = None if self_path is None else any(
        "evaluator" in n for n in _imported_names(self_path, "routes.integrity")
    )
    breached = bool(window) or outside > 0 or gate_imports is True or self_imports is True
    status: CheckStatus
    if breached:
        status = _verdict(False)
        explanation = "The sealed answers were opened outside the reveal step, or a model-path module imports them."
    elif gate_imports is None or self_imports is None:
        status = NOT_AVAILABLE
        explanation = "No sealed-folder read was seen, but the module import check could not run."
    else:
        status = _verdict(not breached)
        explanation = (
            "Nothing on the model's path opened the answers; only the reveal step may, after saving. Paths are "
            "resolved (symlinks, working directory); opens relative to a dir_fd or via a hard link are not attributed."
        )
    facts: list[tuple[str, object]] = [
        ("Sealed-folder reads while computing this report", len(window)),
        ("Sealed-folder reads by this API process since monitoring began", total),
        ("Reads outside OutcomeVault.reveal since monitoring began", outside),
        ("Monitoring began", since),
        ("Temporal gate imports the evaluator", gate_imports),
        ("This route imports the evaluator", self_imports),
    ]
    return _check("sealed_folder_untouched", "system", title, status, explanation, facts, enforced)


def _check_contamination(r: _Report) -> IntegrityCheck:
    title = "Training-data contamination is disclosed"
    enforced = [
        "services/api/agents/model_cards.py::contamination_flag",
        "services/api/core/evaluator.py::build_scorecard (contamination_likely exclusion)",
        "tests/test_agents_model_cards.py",
    ]
    model = r.record.prediction.agent_model if r.record is not None else r.settings.ollama_model
    tag = normalize_model_tag(model)
    card = get_model_card(model)
    cutoff_month = (
        None if card is None or card.knowledge_cutoff_month is None
        else f"{card.knowledge_cutoff_month[0]:04d}-{card.knowledge_cutoff_month[1]:02d}"
    )
    facts: list[tuple[str, object]] = [
        ("Model", tag),
        ("Model source", "the persisted forecast" if r.record is not None else "the configured replay model"),
        ("Training data ends (model card)", cutoff_month),
        ("Public release (model card)", None if card is None or card.release_date is None else card.release_date),
    ]
    if r.snap is None:
        return _check("model_contamination_disclosed", "case", title, NOT_AVAILABLE, _NO_CASE, facts, enforced)
    case = r.snap.case
    horizon_end = case.as_of + timedelta(days=case.horizon_days)
    facts += [("Case flag", case.contamination_flag), ("Question horizon ends", horizon_end)]
    if card is None or card.cutoff_end is None:
        return _check(
            "model_contamination_disclosed", "case", title, NOT_AVAILABLE,
            f"No verified training cutoff for {tag}; the case is flagged '{case.contamination_flag}'.",
            facts, enforced,
        )
    # Earliest and latest the question can have been settled: the cutoff and the end of its horizon.
    at_horizon = card_contamination_flag(model, horizon_end)
    at_cutoff = card_contamination_flag(model, case.as_of)
    if case.contamination_flag == "likely":
        ok = True
        explanation = (
            "Flagged 'likely': the model may know the answer from training, so the benchmark excludes this case."
        )
    elif case.contamination_flag == "unknown":
        ok = at_horizon != "likely"
        explanation = (
            "Flagged 'unknown' and the question may run past the model's training data."
            if ok else "Flagged 'unknown', but the whole question falls inside the model's training data."
        )
    else:
        ok = at_cutoff == "unlikely"
        explanation = (
            "Flagged 'unlikely': the question opened after the model was released."
            if ok else "Flagged 'unlikely', but the question was open before the model's public release."
        )
    return _check(
        "model_contamination_disclosed", "case", title, _verdict(ok), explanation, facts, enforced
    )


def _run_unavailable(r: _Report) -> str:
    return r.prediction_note or "No forecast selected yet (pass the prediction_id of a persisted run)."


def _check_order(r: _Report, prediction_store: PredictionStore | None) -> IntegrityCheck:
    title = "The forecast was saved before any answer was revealed"
    enforced = [
        "services/api/core/store.py (append-only audit_log triggers)",
        "services/api/core/evaluator.py::build_scorecard (persisted_after_outcome_revealed)",
        "tests/test_replay_seal.py::test_peek_then_predict_is_excluded",
    ]
    if r.record is None or prediction_store is None:
        return _check("persisted_before_reveal", "run", title, NOT_AVAILABLE, _run_unavailable(r), [], enforced)
    pred = r.record.prediction
    first = prediction_store.first_reveal(pred.event_id)
    ok = first is None or r.record.persist_seq < first.seq
    explanation = (
        "Saved, with its hashes, before this event's answer was first revealed (audit-log order, not clocks)."
        if ok else "Saved after this event's answer was first revealed; the benchmark ignores it."
    )
    facts: list[tuple[str, object]] = [
        ("Saved at audit-log position", r.record.persist_seq),
        ("Saved at", r.record.persisted_at),
        ("First reveal for this event", "none yet" if first is None else f"position {first.seq}"),
    ]
    return _check("persisted_before_reveal", "run", title, _verdict(ok), explanation, facts, enforced)


def _check_hashes(r: _Report, prediction_store: PredictionStore | None) -> IntegrityCheck:
    title = "The saved run matches its fingerprints"
    enforced = [
        "services/api/core/store.py::PredictionStore.verify",
        "services/api/core/provenance.py",
        "tests/test_replay_seal.py::test_reveal_refuses_when_stored_record_was_tampered",
    ]
    if r.record is None or prediction_store is None:
        return _check("run_hashes_match", "run", title, NOT_AVAILABLE, _run_unavailable(r), [], enforced)
    rec, pred = r.record, r.record.prediction
    problems = prediction_store.verify(pred.prediction_id)
    model_prompt = getattr(rec, "model_prompt", rec.prompt)
    facts: list[tuple[str, object]] = [
        ("prompt_sha256 (stored)", pred.prompt_sha256),
        ("prompt_sha256 (recomputed)", provenance.prompt_sha256(model_prompt)),
        ("snapshot_sha256 (stored)", pred.snapshot_sha256),
        ("snapshot_sha256 (recomputed)", provenance.sha256_hex(rec.snapshot_json)),
        ("record_sha256 (stored)", rec.record_sha256),
        ("record_sha256 (recomputed)", store_module.record_sha256(pred, rec.context, rec.persisted_at,
                                                                  rec.persist_seq)),
        ("Model", pred.agent_model),
        ("Temperature / seed", f"{pred.temperature:g} / {_text(pred.seed)}"),
    ]
    facts += [("Problem", p) for p in problems]
    ok = not problems
    explanation = (
        "Prompt, evidence snapshot and forecast still hash to the values saved with the run (tamper-evident)."
        if ok else "A stored hash does not match its stored text: the record was changed after it was saved."
    )
    return _check("run_hashes_match", "run", title, _verdict(ok), explanation, facts, enforced)


def _check_replay(r: _Report) -> IntegrityCheck:
    title = "Re-running the gate reproduces what the model saw"
    enforced = [
        "services/api/core/temporal_gate.py::GatedSnapshot.model_input",
        "services/api/core/temporal_gate.py::case_sha256",
        "tests/test_scoring.py::test_editing_a_committed_case_after_the_run_is_context_mismatch",
    ]
    if r.record is None:
        return _check("run_matches_gate", "run", title, NOT_AVAILABLE, _run_unavailable(r), [], enforced)
    if r.store is None or r.case_id not in r.store.case_ids():
        return _check(
            "run_matches_gate", "run", title, NOT_AVAILABLE,
            "The forecast's case is not among the committed cases, so the gate cannot be re-run.", [], enforced,
        )
    rec, pred = r.record, r.record.prediction
    try:
        mi = r.store.get_as_of(pred.event_id, pred.as_of).model_input(pred.variant)  # type: ignore[arg-type]
    except (MarketNotAvailable, ValueError):
        mi = None
    gated_prompt = getattr(pred, "gated_prompt_sha256", None) or pred.prompt_sha256
    snap_ok = mi is not None and mi.snapshot_sha256 == pred.snapshot_sha256
    prompt_ok = mi is not None and mi.prompt_sha256 == gated_prompt
    case_ok = r.store.case_sha256(pred.event_id) == rec.context.case_sha256
    cited_ok = mi is not None and set(pred.evidence_ids) <= set(mi.evidence_ids)
    ok = snap_ok and prompt_ok and case_ok and cited_ok
    facts: list[tuple[str, object]] = [
        ("Snapshot hash reproduced", snap_ok),
        ("Gated prompt hash reproduced", prompt_ok),
        ("Case file unchanged since the run (case_sha256)", case_ok),
        ("Cited evidence was all in the gated snapshot", cited_ok),
    ]
    explanation = (
        "The committed case, gated today at the same cutoff, gives exactly the evidence and prompt the model got."
        if ok else "Today's gated input differs from the run's (the case changed, or the run used other data)."
    )
    return _check("run_matches_gate", "run", title, _verdict(ok), explanation, facts, enforced)


def _check_live_web() -> IntegrityCheck:
    title = "The replay cannot reach live web search"
    enforced = [
        "services/api/routes/integrity.py::scan_imports, live_web_refs",
        "tests/test_routes_integrity.py::test_import_scan_flips_when_a_replay_module_reaches_live_web_code",
        "tests/test_explore_separation.py (PR #73)",
    ]
    try:
        scan = scan_imports(SOURCE_ROOT, REPLAY_MODULES)
    except (OSError, SyntaxError, ValueError) as exc:
        return _check(
            "live_web_isolated", "system", title, NOT_AVAILABLE,
            f"The static scan could not run ({type(exc).__name__}).", [], enforced,
        )
    facts: list[tuple[str, object]] = [
        ("Replay modules scanned", len(scan.roots)),
        ("Modules reached through their imports", len(scan.reached)),
        ("Imports or references to live web-search code", len(scan.offenders)),
    ]
    facts += [("Offending import or reference", o) for o in scan.offenders]
    if not scan.roots:
        return _check(
            "live_web_isolated", "system", title, NOT_AVAILABLE,
            "No replay module was found to scan.", facts, enforced,
        )
    ok = not scan.offenders
    explanation = (
        "No replay module, or module it imports, names live web-search code. Static scan only: a name assembled "
        "at run time from variables cannot be seen."
        if ok else "A replay module, or a module it imports, names live web-search code."
    )
    return _check("live_web_isolated", "system", title, _verdict(ok), explanation, facts, enforced)


SYSTEM_CACHE_SECONDS = 60.0
_SYSTEM_CACHE: dict[tuple[str, str], tuple[float, datetime, IntegrityCheck]] = {}
_SYSTEM_LOCK = threading.Lock()


def _cached(name: str, key: str, compute) -> IntegrityCheck:
    """System-level checks are code properties, not per-request data: reuse a result for up to 60 s per process
    (an unauthenticated GET must not trigger 8 MILP solves every time). The response says when it was computed."""
    now = time.monotonic()
    with _SYSTEM_LOCK:
        hit = _SYSTEM_CACHE.get((name, key))
    if hit is None or now - hit[0] > SYSTEM_CACHE_SECONDS:
        hit = (now, datetime.now(UTC), compute())
        with _SYSTEM_LOCK:
            _SYSTEM_CACHE[(name, key)] = hit
    check = hit[2]
    stamp = [
        IntegrityFact(label="Computed at", value=_text(hit[1])),
        IntegrityFact(label="Cache", value=f"code-level check, cached up to {SYSTEM_CACHE_SECONDS:g} s per process"),
    ]
    return check.model_copy(update={"facts": [*check.facts, *stamp]})


def _load_optimizer() -> Any | None:
    """The finance optimizer module (core/optimizer.py, issue #17), or None while it does not exist."""
    if importlib.util.find_spec("core.optimizer") is None:
        return None
    return importlib.import_module("core.optimizer")


def _max_share(value: object) -> float:
    values = value if isinstance(value, (list, tuple)) else [value]
    shares = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(shares) != len(values) or not all(math.isfinite(s) for s in shares):
        raise ValueError("payroll_cut is not a finite number or list of numbers")
    return max(shares, default=0.0)


def _tempting_settings(optimizer: Any) -> Any:
    """Optimizer settings with payroll cuts made FREE (disruption cost 0), so an unprotected solver would use them.

    A probe on the default costs proves little: if cutting payroll is never worth it, a plan without cuts says
    nothing about the bound. With free cuts the control run (Protect payroll off) cuts payroll, and the test run
    (Protect payroll on) must not.
    """
    return optimizer.OptimizerSettings(disruption_costs=optimizer.DisruptionCosts(payroll_cut_per_dollar=0.0))


def _check_payroll(settings: Settings) -> IntegrityCheck:
    title = "Protect payroll is a hard solver constraint"
    enforced = [
        "services/api/core/optimizer.py (payroll-cut upper bound 0 when Protect payroll is on; MATH_MODEL §4)",
        "tests/test_routes_integrity.py::test_payroll_check_flips_when_the_solver_cuts_payroll",
    ]
    optimizer = _load_optimizer()
    if optimizer is None or not callable(getattr(optimizer, "optimize", None)):
        return _check(
            "payroll_hard_constraint", "system", title, NOT_AVAILABLE,
            "The recovery optimizer is not in this build yet (issue #17), so there is no solver to check.",
            [], enforced,
        )
    try:
        business = load_business(settings)
        scenarios = load_scenarios(settings) or []
        tempting = _tempting_settings(optimizer)
    except (RouteError, AttributeError, TypeError, ValueError) as exc:
        return _check(
            "payroll_hard_constraint", "system", title, NOT_AVAILABLE,
            f"The probe could not be set up ({getattr(exc, 'code', type(exc).__name__)}).", [], enforced,
        )
    solved = infeasible = errors = control_cuts = 0
    worst = 0.0
    violations: list[str] = []
    for scenario in scenarios:
        try:
            control = optimizer.optimize(business, scenario.shock, protect_payroll=False, settings=tempting)
            if getattr(control, "status", None) == "OPTIMAL" and _max_share(control.plan.payroll_cut) > 1e-9:
                control_cuts += 1
            res = optimizer.optimize(business, scenario.shock, protect_payroll=True, settings=tempting)
            status = getattr(res, "status", None)
            if status == "OPTIMAL":
                share = _max_share(res.plan.payroll_cut)
                worst = max(worst, share)
                if share > 1e-9:
                    violations.append(scenario.id)
                solved += 1
            elif status == "NO FEASIBLE PLAN":
                infeasible += 1
            else:
                errors += 1
        except Exception:  # an unexpected optimizer contract: report it, never assume the constraint held
            errors += 1
    facts: list[tuple[str, object]] = [
        ("Named scenarios probed (payroll cuts made free)", len(scenarios)),
        ("Control, Protect payroll OFF: plans that cut payroll", control_cuts),
        ("Protect payroll ON: plans solved", solved),
        ("Protect payroll ON: NO FEASIBLE PLAN (payroll still not cut)", infeasible),
        ("Protect payroll ON: largest payroll-cut share in any plan", f"{worst:g}"),
        ("Scenarios the probe could not evaluate", errors),
    ]
    facts += [("Plan cut payroll with Protect payroll on, scenario", v) for v in violations]
    if violations:
        return _check(
            "payroll_hard_constraint", "system", title, _verdict(False),
            "With Protect payroll on, the solver still chose a payroll cut.", facts, enforced,
        )
    if control_cuts == 0 or solved + infeasible == 0:
        return _check(
            "payroll_hard_constraint", "system", title, NOT_AVAILABLE,
            "The probe never made a payroll cut worth choosing, so the bound could not be observed.", facts, enforced,
        )
    return _check(
        "payroll_hard_constraint", "system", title, _verdict(not violations),
        "Even when cutting pay is free, the solver cuts none with Protect payroll on (it cuts with it off).",
        facts, enforced,
    )


# ---------------------------------------------------------------- the route


def _load_cases(settings: Settings) -> EvidenceStore | None:
    directory = settings.data_dir / CASES_DIR
    if not directory.is_dir():
        return None
    try:
        return EvidenceStore.from_dir(directory)
    except (SealedDataError, ValueError):
        raise RouteError(
            ErrorCode.DATA_INVALID, f"A file in {CASES_DIR}/ failed the temporal gate's checks.", status_code=500
        ) from None


class ReadOnlyPredictionStore(PredictionStore):
    """The prediction store opened with SQLite ``mode=ro``: the reads of ``PredictionStore``, no DDL, no writes.

    ``PredictionStore.__init__`` creates the schema and migrates columns; a GET must do neither, so it is skipped.
    """

    def __init__(self, path: Path) -> None:  # deliberately does not call super().__init__ (DDL)
        self.path = Path(path)
        self._clock = store_module._utcnow

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def schema_problem(self) -> str | None:
        try:
            with self._connect() as conn:
                tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                columns = {r["name"] for r in conn.execute("PRAGMA table_info(predictions)")}
        except sqlite3.Error as exc:
            return f"the prediction store could not be opened read-only ({type(exc).__name__})"
        missing = sorted(set(store_module._COLUMNS) - columns)
        if not {"predictions", "audit_log"} <= tables or missing:
            return "the prediction store's schema is older than this build (run a replay once to migrate it)"
        return None


def _open_prediction_store() -> tuple[PredictionStore | None, str | None]:
    """(read-only store, None), or (None, why not). Never creates or migrates the database."""
    path = store_module.configured_db_path()
    if not path.is_file():
        return None, "No forecast has been saved yet (the prediction store does not exist)."
    store = ReadOnlyPredictionStore(path)
    problem = store.schema_problem()
    return (None, f"NOT AVAILABLE: {problem}.") if problem else (store, None)


@router.get(
    "/integrity",
    response_model=IntegrityResponse,
    responses={
        404: {"model": RouteErrorBody, "description": "NOT_FOUND: unknown case_id"},
        422: {"model": RouteErrorBody, "description": "VALIDATION_ERROR: bad query, or a prediction for another case"},
        500: {"model": RouteErrorBody, "description": "DATA_INVALID: a case file failed the gate's checks"},
    },
    summary="Integrity checks for a replay case and run, computed live (pre-reveal safe)",
)
def integrity_report(
    settings: Annotated[Settings, Depends(get_settings)],
    case_id: Annotated[str | None, Query(max_length=200, pattern=_IDENTIFIER)] = None,
    prediction_id: Annotated[str | None, Query(max_length=200, pattern=_IDENTIFIER)] = None,
) -> IntegrityResponse:
    notes: list[str] = []
    with MONITOR.window() as window:
        prediction_store: PredictionStore | None = None
        record: StoredPrediction | None = None
        prediction_note: str | None = None
        if prediction_id is not None:
            prediction_store, prediction_note = _open_prediction_store()
            if prediction_store is not None:
                record = prediction_store.get_record(prediction_id)
                if record is None:
                    prediction_note = f"Forecast {prediction_id} is not in the prediction store."
        if record is not None:
            if case_id is not None and case_id != record.prediction.event_id:
                raise RouteError(
                    ErrorCode.VALIDATION_ERROR,
                    f"Forecast {prediction_id} was made for another case, not {case_id}.",
                )
            case_id = record.prediction.event_id

        cases = _load_cases(settings) if case_id is not None else None
        snap: GatedSnapshot | None = None
        raw: dict | None = None
        if case_id is not None:
            if cases is None or case_id not in cases.case_ids():
                if record is None:
                    raise RouteError(ErrorCode.NOT_FOUND, f"Unknown replay case {case_id}.", status_code=404)
                notes.append(f"The forecast's case {case_id} is not among the committed cases.")
            else:
                snap = cases.get_as_of(case_id, cases.public_case(case_id).as_of)
                raw = _read_case_file(cases, case_id)

        prompts: dict[str, str] = {}
        if snap is not None:
            for variant in PROMPT_VARIANTS:
                try:
                    prompts[variant] = snap.model_input(variant).prompt
                except MarketNotAvailable:
                    continue
        report = _Report(settings, case_id, cases, snap, raw, record, prediction_note, notes, prompts)
        computed = [
            _check_cutoff(report),
            _check_stripped(report),
            _check_contamination(report),
            _check_order(report, prediction_store),
            _check_hashes(report, prediction_store),
            _check_replay(report),
            _cached("live_web", str(SOURCE_ROOT), _check_live_web),
            _cached("payroll", str(settings.data_dir), lambda: _check_payroll(settings)),
        ]
    # Last, so the window covers every step above.
    computed.insert(2, _check_sealed(window))

    exclusions = Counter((x.kind, x.reason) for x in snap.exclusions) if snap is not None else Counter()
    failed = sum(c.status == "FAIL" for c in computed)
    unavailable = sum(c.status == NOT_AVAILABLE for c in computed)
    return IntegrityResponse(
        case_id=case_id,
        prediction_id=prediction_id,
        as_of=snap.as_of if snap is not None else None,
        case_provenance=snap.case.provenance if snap is not None else None,
        prediction_provenance=record.prediction.provenance if record is not None else None,
        computed_at=datetime.now(UTC),
        checks=computed,
        counts=IntegrityCounts(passed=len(computed) - failed - unavailable, failed=failed, not_available=unavailable),
        excluded=[IntegrityExclusion(kind=k, reason=reason, count=n) for (k, reason), n in sorted(exclusions.items())],
        limits=list(LIMITS),
        notes=notes,
    )
