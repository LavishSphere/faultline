"""Skeptic / verifier for a proposed forecast (SPEC §3.3).

``review(forecast, offered_evidence_ids)`` re-checks a ``ForecastOutput`` against the evidence ids the prompt
offered and returns a ``SkepticReport``. It is deliberately independent of ``ForecastOutput``'s own validators
(it does not trust that the object was validated, e.g. one built with ``model_construct``), and it NEVER edits
the forecast: it only lists problems.

Severity:
* ``error``   -> the forecast must be rejected before display (unknown evidence id in ``evidence_ids``, an
  un-offered id in an explicit citation ``(...)`` / ``[...]`` in the rationale, p_yes not a finite number in
  [0, 1], invalid decision, rationale with no visible text or over the length limit);
* ``warning`` -> shown next to the forecast (a rationale sentence that cites no offered evidence id, an id cited in
  the rationale but missing from ``evidence_ids``, a token merely shaped like an offered id, duplicates, no
  evidence cited at all).

Sentence splitting is a plain heuristic (split after . ! ? followed by whitespace; fragments under three words
are joined to the next sentence), so a warning is a prompt for a human look, not a verdict. Shape matching
compares tokens with an offered id's prefix up to its last separator (``evid_a`` -> ``evid_``), ignoring case
and treating ``_ - . :`` alike. Evidence ids are often slugs (``bad-quarter``), so shape alone is only a warning.

Field-label normalisation (pre-run format fix, EVALUATION_PROTOCOL §8, 2026-11-14): inside a citation group, the
schema field name ``evidence_id`` / ``evidence_ids`` used as a label (optionally quoted, followed by ``:`` or ``=``,
as in ``(evidence_id: fomc-2026-jul.minutes)``) is dropped before the group's tokens are checked. Only that exact
label is dropped; every remaining token must still match an offered id exactly (no case folding, no "closest" id),
the rationale itself is never edited, and dropping a label can only remove the label's own UNKNOWN_CITED_ID error.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict

from agents.provider import RATIONALE_MAX_CHARS, has_visible_text
from models import Decision

Severity = Literal["error", "warning"]
ProblemCode = Literal[
    "UNKNOWN_EVIDENCE_ID",
    "UNKNOWN_CITED_ID",
    "POSSIBLE_UNKNOWN_ID",
    "P_YES_OUT_OF_RANGE",
    "INVALID_DECISION",
    "RATIONALE_LENGTH",
    "UNCITED_CLAIM",
    "CITATION_NOT_LISTED",
    "DUPLICATE_EVIDENCE_ID",
    "NO_EVIDENCE_CITED",
]

_DECISIONS = frozenset(get_args(Decision))
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_ID_CHARS = r"A-Za-z0-9_\-"
_ID_TOKEN = re.compile(r"[A-Za-z0-9_\-.:]+")
_SEPARATORS = re.compile(r"[\-.:]")
# Citation forms: "(evid_a)", "(evid_a, evid_b)", "[evid_a]".
_CITATION_GROUP = re.compile(r"[(\[]([^()\[\]]*)[)\]]")
# The prompt's own JSON key used as a label in a citation: "evidence_id: x", '"evidence_ids": x', "evidence_id=x".
_FIELD_LABEL = re.compile(r"""(?<![A-Za-z0-9_\-.:"'`])["'`]?evidence_ids?["'`]?\s*[:=]\s*""")
# An id-shaped piece: id grammar (models.Identifier) with at least one separator or digit.
_ID_SHAPED = re.compile(r"(?=[A-Za-z0-9_.:\-]*[_\-.:0-9])[A-Za-z0-9_.:\-]+")
_STRONG_ID_MARK = re.compile(r"[_0-9]")
# Sentences that only state the evidence is insufficient are not factual claims needing a citation.
_INSUFFICIENCY = re.compile(
    r"\b(insufficient|no (direct |relevant )?evidence|not enough (evidence|information)|lack of evidence)\b",
    re.IGNORECASE,
)


class SkepticProblem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ProblemCode
    severity: Severity
    message: str
    evidence_id: str | None = None
    sentence: str | None = None


class SkepticReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    problems: tuple[SkepticProblem, ...]

    @property
    def rejected(self) -> bool:
        """True when any error-level problem exists: the forecast must not be displayed as valid."""
        return any(p.severity == "error" for p in self.problems)

    @property
    def flagged(self) -> bool:
        return any(p.severity == "warning" for p in self.problems)

    def codes(self) -> list[str]:
        return [p.code for p in self.problems]


def _mentions(text: str, evidence_id: str) -> bool:
    """``evidence_id`` appears as a whole token (a trailing '.' or ':' ending a sentence is allowed)."""
    pattern = rf"(?<![{_ID_CHARS}.:]){re.escape(evidence_id)}(?![{_ID_CHARS}])(?![.:][{_ID_CHARS}])"
    return re.search(pattern, text) is not None


def _norm(s: str) -> str:
    """Case- and separator-insensitive form for shape comparison ("EVID-c" -> "evid_c")."""
    return _SEPARATORS.sub("_", s.lower())


def _id_prefixes(offered: Iterable[str]) -> set[str]:
    """For each offered id, the normalized part up to and including its last separator ("evid_a" -> "evid_")."""
    out = set()
    for eid in offered:
        cut = max(eid.rfind(c) for c in "_-.:")
        if cut >= 1:
            out.add(_norm(eid[: cut + 1]))
    return out


def _shares_prefix(token: str, prefixes: set[str]) -> bool:
    n = _norm(token)
    return any(n.startswith(p) and len(n) > len(p) for p in prefixes)


def _tokens(text: str) -> list[str]:
    return [t for t in (m.group(0).rstrip(".:-") for m in _ID_TOKEN.finditer(text)) if t]


def _unoffered_cited_ids(text: str, offered: list[str]) -> tuple[set[str], set[str]]:
    """Un-offered ids in the rationale, as (errors, warnings).

    Error: only in an explicit citation form, i.e. inside ``(...)`` or ``[...]``, when the token is not offered
    and either (a) shares an offered id's prefix and contains ``_`` or a digit, or (b) sits in a pure id list
    (every piece id-shaped, at least one piece offered), e.g. ``(evid_a, evid-c)``.
    Warning: any other token, anywhere, that shares an offered id's prefix but is not offered. With slug ids
    such as ``bad-quarter`` this catches ordinary hyphenated words (``bad-tempered``), so it is never an error.
    """
    prefixes = _id_prefixes(offered)
    offered_set = set(offered)
    errors: set[str] = set()
    for group in _CITATION_GROUP.finditer(text):
        content = _FIELD_LABEL.sub(" ", group.group(1))
        pieces = [p.rstrip(".:-") for p in re.split(r"[\s,;]+", content.strip()) if p.strip()]
        pure_list = bool(pieces) and all(_ID_SHAPED.fullmatch(p) for p in pieces)
        has_offered = any(p in offered_set for p in pieces)
        for token in _tokens(content):
            if token in offered_set:
                continue
            strong_shape = _shares_prefix(token, prefixes) and _STRONG_ID_MARK.search(token) is not None
            in_id_list = pure_list and has_offered and _ID_SHAPED.fullmatch(token) is not None
            if strong_shape or in_id_list:
                errors.add(token)
    warnings = {t for t in _tokens(text) if t not in offered_set and t not in errors and _shares_prefix(t, prefixes)}
    return errors, warnings


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text.strip()) if p.strip()]
    merged: list[str] = []
    carry = ""
    for p in parts:
        candidate = f"{carry} {p}".strip() if carry else p
        if len(candidate.split()) < 3:
            carry = candidate
            continue
        merged.append(candidate)
        carry = ""
    if carry:
        if merged:
            merged[-1] = f"{merged[-1]} {carry}"
        else:
            merged.append(carry)
    return merged


def review(forecast: Any, offered_evidence_ids: Iterable[str]) -> SkepticReport:
    """List every problem with ``forecast`` relative to the offered evidence ids. Never mutates ``forecast``."""
    offered = list(dict.fromkeys(offered_evidence_ids))
    offered_set = set(offered)
    problems: list[SkepticProblem] = []

    p_yes = getattr(forecast, "p_yes", None)
    if (
        isinstance(p_yes, bool)
        or not isinstance(p_yes, (int, float))
        or not math.isfinite(p_yes)
        or not 0.0 <= p_yes <= 1.0
    ):
        problems.append(
            SkepticProblem(
                code="P_YES_OUT_OF_RANGE",
                severity="error",
                message=f"p_yes must be a finite number in [0, 1]; got {p_yes!r}",
            )
        )

    decision = getattr(forecast, "decision", None)
    if not isinstance(decision, str) or decision not in _DECISIONS:
        problems.append(
            SkepticProblem(
                code="INVALID_DECISION", severity="error", message=f"decision must be one of {sorted(_DECISIONS)}"
            )
        )

    rationale = getattr(forecast, "rationale", None)
    if not isinstance(rationale, str) or not has_visible_text(rationale) or len(rationale) > RATIONALE_MAX_CHARS:
        problems.append(
            SkepticProblem(
                code="RATIONALE_LENGTH",
                severity="error",
                message=f"rationale must be non-empty text of at most {RATIONALE_MAX_CHARS} characters",
            )
        )
        rationale = rationale if isinstance(rationale, str) else ""

    raw_ids = getattr(forecast, "evidence_ids", None)
    cited = [e for e in raw_ids if isinstance(e, str)] if isinstance(raw_ids, (list, tuple)) else []
    if not isinstance(raw_ids, (list, tuple)) or len(cited) != len(raw_ids):
        problems.append(
            SkepticProblem(code="UNKNOWN_EVIDENCE_ID", severity="error", message="evidence_ids must be a list of ids")
        )
    seen: set[str] = set()
    for eid in cited:
        if eid in seen:
            problems.append(
                SkepticProblem(
                    code="DUPLICATE_EVIDENCE_ID",
                    severity="warning",
                    message="evidence id listed twice",
                    evidence_id=eid,
                )
            )
            continue
        seen.add(eid)
        if eid not in offered_set:
            problems.append(
                SkepticProblem(
                    code="UNKNOWN_EVIDENCE_ID",
                    severity="error",
                    message="evidence id was not offered in the prompt",
                    evidence_id=eid,
                )
            )

    if offered and not cited:
        problems.append(
            SkepticProblem(code="NO_EVIDENCE_CITED", severity="warning", message="no evidence id cited")
        )

    for eid in offered:
        if eid not in seen and _mentions(rationale, eid):
            problems.append(
                SkepticProblem(
                    code="CITATION_NOT_LISTED",
                    severity="warning",
                    message="rationale cites an evidence id that is missing from evidence_ids",
                    evidence_id=eid,
                )
            )

    cited_errors, shape_warnings = _unoffered_cited_ids(rationale, offered)
    for token in sorted(cited_errors):
        problems.append(
            SkepticProblem(
                code="UNKNOWN_CITED_ID",
                severity="error",
                message="rationale cites, in (...) or [...], an id that was not offered",
                evidence_id=token,
            )
        )
    for token in sorted(shape_warnings):
        problems.append(
            SkepticProblem(
                code="POSSIBLE_UNKNOWN_ID",
                severity="warning",
                message="rationale has a token shaped like an offered evidence id that was not offered",
                evidence_id=token,
            )
        )

    for sentence in split_sentences(rationale):
        if _INSUFFICIENCY.search(sentence):
            continue
        if not any(_mentions(sentence, eid) for eid in offered):
            problems.append(
                SkepticProblem(
                    code="UNCITED_CLAIM",
                    severity="warning",
                    message="rationale sentence cites no offered evidence id",
                    sentence=sentence,
                )
            )

    return SkepticReport(problems=tuple(problems))
