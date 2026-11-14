"""GET /api/integrity: the INTEGRITY panel's checks are computed live, never hardcoded (issue #81).

Written before routes/integrity.py. Three kinds of test:

* Honest system -> each check reports PASS with the real counts and hashes.
* Mutations -> break the thing a check guards (the gate's date filter, the retrospective filter, key stripping,
  a sealed-folder read, a Tavily import, a stored record, a case edit, a late save, a payroll cut) and the
  check flips to FAIL. A check whose input is missing is NOT AVAILABLE, never PASS.
* Leakage -> the route is pre-reveal safe: no outcome-like key anywhere in its JSON or its schema, and a canary
  planted only in the sealed folder never appears, even after a reveal was logged.

All fixtures are SYNTHETIC and hand-written for these tests.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import re
import shutil
import sqlite3
import textwrap
import types
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import store as store_module
from core import temporal_gate
from core.store import PredictionStore
from core.temporal_gate import EvidenceStore
from main import create_app
from models import Prediction, Provenance
from routes import integrity

API_DIR = Path(__file__).resolve().parents[1]
REAL_DATA = API_DIR / "data"
# Duplicated on purpose (see tests/test_contracts.py): weakening models.py must not weaken this test.
OUTCOME_LIKE = re.compile(r"outcome|resolution|resolved|settle|result|winner|final_price", re.IGNORECASE)
CANARY = f"CANARY-{uuid.uuid4()}"
EVENT = "synthetic_integrity_001"
AS_OF = datetime(2025, 3, 3, 15, 0, tzinfo=UTC)
COLLECTED = datetime(2026, 11, 13, 3, 41, tzinfo=UTC)
STATUSES = {"PASS", "FAIL", "NOT AVAILABLE"}
CASE_CHECKS = {"evidence_cutoff", "outcome_fields_stripped", "model_contamination_disclosed"}
RUN_CHECKS = {"persisted_before_reveal", "run_hashes_match", "run_matches_gate"}


# ---------------------------------------------------------------- fixture builders


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def evidence(eid: str, available_at: datetime, *, event_id: str = EVENT, published_at: datetime | None = None,
             unverified: bool = False, extra: dict | None = None) -> dict:
    text = f"SYNTHETIC evidence text {eid}."
    item = {
        "evidence_id": eid,
        "event_id": event_id,
        "title": f"SYNTHETIC source {eid}",
        "source_url": f"https://example.org/{eid}",
        "archive_url": None,
        "published_at": _iso(published_at or available_at),
        "observed_at": _iso(COLLECTED),
        "available_at": _iso(available_at),
        "content_sha256": _sha(text),
        "content": text,
        "retrospective_unverified": unverified,
        "provenance": "SYNTHETIC",
    }
    item.update(extra or {})
    return item


def quote(ts: datetime, p: str, market_id: str = "SYNTH-INT-1") -> dict:
    return {
        "venue": "kalshi",
        "market_id": market_id,
        "url": f"https://example.org/markets/{market_id}",
        "source_url": "https://example.org/api/candles",
        "outcome": "YES",
        "p_yes": float(p),
        "quote_kind": "candle_close",
        "ts": _iso(ts),
        "raw_price": p,
        "raw_scale": "dollars",
        "volume": "900.00",
        "collected_at": _iso(COLLECTED),
        "raw_sha256": _sha(f"{market_id}{ts.isoformat()}{p}"),
    }


def case_file(event_id: str = EVENT, *, as_of: datetime = AS_OF, flag: str = "unlikely", horizon_days: int = 14,
              evidence_items: list[dict] | None = None, quotes: list[dict] | None = None) -> dict:
    return {
        "case": {
            "event_id": event_id,
            "title": f"SYNTHETIC: will the test committee act ({event_id})?",
            "as_of": _iso(as_of),
            "horizon_days": horizon_days,
            "resolution_rule": "SYNTHETIC rule text: YES if the test condition holds.",
            "evidence_ids": [],
            "market_quote_id": None,
            "snapshot_hash": "sha256:" + "0" * 64,
            "synthetic": True,
            "contamination_flag": flag,
            "provenance": "SYNTHETIC",
        },
        "evidence": evidence_items if evidence_items is not None else standard_evidence(),
        "market_quotes": quotes if quotes is not None else standard_quotes(),
    }


def standard_evidence() -> list[dict]:
    """Two admissible items (one on the boundary), one per evidence exclusion reason, one with an outcome key."""
    return [
        evidence("evid_ok", AS_OF - timedelta(days=4)),
        evidence("evid_edge", AS_OF),
        evidence("evid_keyed", AS_OF - timedelta(days=2), extra={"resolution_note": f"settled {CANARY}"}),
        # Published before the cutoff, but first public only after it: the date filter is what excludes it.
        evidence("evid_late", AS_OF + timedelta(hours=2), published_at=AS_OF - timedelta(days=1)),
        evidence("evid_unverified", AS_OF - timedelta(days=3), unverified=True),
        evidence("evid_other", AS_OF - timedelta(days=1), event_id="other_event"),
    ]


def standard_quotes() -> list[dict]:
    return [
        quote(AS_OF - timedelta(hours=30), "0.41"),  # stale
        quote(AS_OF - timedelta(hours=2), "0.55"),  # selected
        quote(AS_OF + timedelta(hours=1), "0.93"),  # future
    ]


def write_case(data_dir: Path, payload: dict) -> Path:
    cases = data_dir / "demo_cases"
    cases.mkdir(parents=True, exist_ok=True)
    path = cases / f"{payload['case']['event_id']}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    for name in ("demo_business.json", "scenarios.json"):
        shutil.copy(REAL_DATA / name, d / name)
    sealed = d / "sealed_outcomes"
    sealed.mkdir()
    (sealed / f"{EVENT}.json").write_text(
        json.dumps({"event_id": EVENT, "outcome": "NO", "source_url": "https://example.org/s",
                    "provenance": "SYNTHETIC", "notes": CANARY}),
        encoding="utf-8",
    )
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(d))
    monkeypatch.delenv("FAULTLINE_OLLAMA_MODEL", raising=False)
    monkeypatch.setattr(store_module, "DEFAULT_DB_PATH", tmp_path / "var" / "predictions.sqlite3")
    integrity.MONITOR.reset()  # earlier tests in this process wrote sealed fixtures; count only from here
    integrity._SYSTEM_CACHE.clear()  # system checks are cached per process; each test computes its own
    return d


@pytest.fixture
def client():
    return TestClient(create_app())


def get(client: TestClient, **params) -> dict:
    resp = client.get("/api/integrity", params={k: v for k, v in params.items() if v is not None})
    assert resp.status_code == 200, resp.text
    return resp.json()


def checks(body: dict) -> dict[str, dict]:
    return {c["id"]: c for c in body["checks"]}


def facts(check: dict) -> dict[str, str]:
    return {f["label"]: f["value"] for f in check["facts"]}


def persist(data_dir: Path, *, pid: str = "pred_int_001", variant: str = "agent_only", event_id: str = EVENT,
            clock_start: datetime | None = None) -> Prediction:
    """Save a forecast exactly as the replay route does: from the gate's ModelInput, before any reveal."""
    cases = EvidenceStore.from_dir(data_dir / "demo_cases")
    snap = cases.get_as_of(event_id, cases.public_case(event_id).as_of)
    mi = snap.model_input(variant)
    pred = Prediction(
        prediction_id=pid,
        event_id=event_id,
        as_of=datetime.fromisoformat(mi.as_of),
        agent_model="ollama/llama3.1:8b",
        model_digest=None,
        variant=variant,
        p_yes=0.6,
        decision="wait",
        rationale="SYNTHETIC rationale citing evid_ok.",
        evidence_ids=["evid_ok"],
        prompt_sha256=mi.prompt_sha256,
        snapshot_sha256=mi.snapshot_sha256,
        temperature=0.0,
        seed=7,
        recorded_at=COLLECTED,
        provenance=Provenance.RECORDED_RUN,
    )
    PredictionStore(store_module.DEFAULT_DB_PATH).save(pred, mi)
    return pred


def walk_keys(obj, path: str = "$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}.{k}", k
            yield from walk_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_keys(v, f"{path}[{i}]")


# ---------------------------------------------------------------- shape and honesty of the contract


def test_route_is_published_get_only(client, data_dir):
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths["/api/integrity"]) == {"get"}
    assert client.post("/api/integrity").status_code == 405


def test_every_status_is_one_of_three_and_nothing_passes_without_its_input(client, data_dir):
    """No case, no prediction: case and run checks are NOT AVAILABLE, never PASS."""
    body = get(client)
    by_id = checks(body)
    assert {c["status"] for c in body["checks"]} <= STATUSES
    for cid in CASE_CHECKS | RUN_CHECKS:
        assert by_id[cid]["status"] == "NOT AVAILABLE", cid
    counts = body["counts"]
    assert counts["passed"] + counts["failed"] + counts["not_available"] == len(body["checks"])
    assert counts["passed"] == sum(c["status"] == "PASS" for c in body["checks"])
    assert body["limits"], "the panel must state its limits"
    for c in body["checks"]:
        assert c["explanation"].strip() and c["enforced_by"], c["id"]


def test_no_cases_directory_means_case_checks_not_available(client, data_dir):
    by_id = checks(get(client, case_id=None))
    assert by_id["evidence_cutoff"]["status"] == "NOT AVAILABLE"
    assert client.get("/api/integrity", params={"case_id": "nope"}).status_code == 404


def test_unknown_case_is_404(client, data_dir):
    write_case(data_dir, case_file())
    resp = client.get("/api/integrity", params={"case_id": "no_such_case"})
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_pass_is_only_ever_produced_from_a_boolean():
    """Source guard: the string "PASS" occurs only in the status type and in ``_verdict(ok)``. No check can
    hardcode a pass: each one must hand ``_verdict`` the boolean it computed."""
    tree = ast.parse(Path(integrity.__file__).read_text(encoding="utf-8"))
    allowed: list[range] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_verdict":
            allowed.append(range(node.lineno, node.end_lineno + 1))
        elif isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "CheckStatus" for t in node.targets):
            allowed.append(range(node.lineno, node.end_lineno + 1))
    assert len(allowed) == 2
    hits = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == "PASS"]
    assert hits and all(any(line in r for r in allowed) for line in hits), hits
    # Every _verdict call passes a computed value, never the literal True.
    literal_true = [
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_verdict"
        and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value is True
    ]
    assert literal_true == [], f"_verdict(True) hardcodes a pass at lines {literal_true}"


# ---------------------------------------------------------------- case checks: honest gate


def test_honest_case_checks_pass_with_the_gates_real_counts(client, data_dir):
    write_case(data_dir, case_file())
    body = get(client, case_id=EVENT)
    by_id = checks(body)
    assert body["case_id"] == EVENT and body["case_provenance"] == "SYNTHETIC"

    cutoff = by_id["evidence_cutoff"]
    assert cutoff["status"] == "PASS", cutoff
    f = facts(cutoff)
    assert f["Evidence items the model could see"] == "3 of 6"
    assert f["Admitted items dated after the cutoff"] == "0"
    assert f["Independent recount agrees with the gate"] == "yes"

    excluded = {(x["kind"], x["reason"]): x["count"] for x in body["excluded"]}
    real = EvidenceStore.from_dir(data_dir / "demo_cases").get_as_of(EVENT, AS_OF)
    expected: dict[tuple[str, str], int] = {}
    for x in real.exclusions:
        expected[(x.kind, x.reason)] = expected.get((x.kind, x.reason), 0) + 1
    assert excluded == expected
    assert excluded == {
        ("evidence", "available_after_as_of"): 1,
        ("evidence", "retrospective_unverified"): 1,
        ("evidence", "wrong_event"): 1,
    }

    stripped = by_id["outcome_fields_stripped"]
    assert stripped["status"] == "PASS", stripped
    assert facts(stripped)["Outcome-like fields dropped from candidate items"] == "1"
    assert facts(stripped)["Outcome-like fields in the model input"] == "0"

    sealed = by_id["sealed_folder_untouched"]
    assert sealed["status"] == "PASS", sealed
    assert facts(sealed)["Sealed-folder reads while computing this report"] == "0"


def _mutated_get_as_of(old: str, new: str):
    """EvidenceStore.get_as_of with one source line replaced (a real mutation of the gate, not a stub)."""
    src = textwrap.dedent(inspect.getsource(temporal_gate.EvidenceStore.get_as_of))
    assert old in src, f"mutation anchor {old!r} not found: the gate changed, update this test"
    namespace = dict(vars(temporal_gate))
    exec(compile(src.replace(old, new), temporal_gate.__file__, "exec"), namespace)  # noqa: S102
    return namespace["get_as_of"]


def test_mutation_breaking_the_date_filter_flips_the_cutoff_check_to_fail(client, data_dir, monkeypatch):
    write_case(data_dir, case_file())
    assert checks(get(client, case_id=EVENT))["evidence_cutoff"]["status"] == "PASS"

    mutated = _mutated_get_as_of("elif item.available_at > cutoff:", "elif False:")
    monkeypatch.setattr(temporal_gate.EvidenceStore, "get_as_of", mutated)
    # Positive control: the mutated gate really admits the late item.
    snap = EvidenceStore.from_dir(data_dir / "demo_cases").get_as_of(EVENT, AS_OF)
    assert "evid_late" in snap.evidence_ids

    check = checks(get(client, case_id=EVENT))["evidence_cutoff"]
    assert check["status"] == "FAIL", check
    assert facts(check)["Admitted items dated after the cutoff"] == "1"
    assert facts(check)["Independent recount agrees with the gate"] == "no"


def test_mutation_breaking_the_unverified_filter_flips_the_cutoff_check_to_fail(client, data_dir, monkeypatch):
    write_case(data_dir, case_file())
    mutated = _mutated_get_as_of("elif item.retrospective_unverified:", "elif False:")
    monkeypatch.setattr(temporal_gate.EvidenceStore, "get_as_of", mutated)
    check = checks(get(client, case_id=EVENT))["evidence_cutoff"]
    assert check["status"] == "FAIL", check
    assert facts(check)["Independent recount agrees with the gate"] == "no"


def test_mutation_breaking_the_staleness_window_flips_the_cutoff_check_to_fail(client, data_dir, monkeypatch):
    write_case(data_dir, case_file(quotes=[quote(AS_OF - timedelta(hours=30), "0.41")]))
    assert checks(get(client, case_id=EVENT))["evidence_cutoff"]["status"] == "PASS"
    monkeypatch.setattr(temporal_gate, "DEFAULT_MAX_STALENESS", timedelta(days=30))
    check = checks(get(client, case_id=EVENT))["evidence_cutoff"]
    assert check["status"] == "FAIL", check


def test_mutation_leaking_an_outcome_key_into_the_projection_flips_the_strip_check(client, data_dir, monkeypatch):
    write_case(data_dir, case_file())
    original = temporal_gate._project_evidence

    def leaky(item):
        return {**original(item), "resolved_value": "leak"}

    monkeypatch.setattr(temporal_gate, "_project_evidence", leaky)
    check = checks(get(client, case_id=EVENT))["outcome_fields_stripped"]
    assert check["status"] == "FAIL", check
    assert facts(check)["Outcome-like fields in the model input"] != "0"


def test_a_sealed_folder_read_during_the_report_flips_the_sealed_check(client, data_dir, monkeypatch):
    write_case(data_dir, case_file())
    original = temporal_gate.EvidenceStore.get_as_of
    sealed_file = data_dir / "sealed_outcomes" / f"{EVENT}.json"

    def peeking(self, case_id, as_of):
        sealed_file.read_text(encoding="utf-8")  # what a leaky gate would do
        return original(self, case_id, as_of)

    monkeypatch.setattr(temporal_gate.EvidenceStore, "get_as_of", peeking)
    check = checks(get(client, case_id=EVENT))["sealed_folder_untouched"]
    assert check["status"] == "FAIL", check
    assert facts(check)["Sealed-folder reads while computing this report"] != "0"


def test_a_sealed_read_outside_the_vault_since_start_flips_the_sealed_check(client, data_dir):
    write_case(data_dir, case_file())
    (data_dir / "sealed_outcomes" / f"{EVENT}.json").read_text(encoding="utf-8")  # not via OutcomeVault.reveal
    check = checks(get(client, case_id=EVENT))["sealed_folder_untouched"]
    assert check["status"] == "FAIL", check
    assert facts(check)["Reads outside OutcomeVault.reveal since monitoring began"] == "1"


def test_a_sealed_read_inside_the_vault_is_counted_but_allowed(client, data_dir, tmp_path):
    """The evaluator is the one reader the design allows; its reads are attributed to it, not flagged."""
    from core.evaluator import OutcomeVault

    write_case(data_dir, case_file())
    pred = persist(data_dir)
    vault = OutcomeVault(PredictionStore(store_module.DEFAULT_DB_PATH), sealed_dir=data_dir / "sealed_outcomes")
    vault.reveal(pred.prediction_id)
    check = checks(get(client, case_id=EVENT))["sealed_folder_untouched"]
    f = facts(check)
    assert int(f["Sealed-folder reads by this API process since monitoring began"]) >= 1
    assert f["Reads outside OutcomeVault.reveal since monitoring began"] == "0"
    assert check["status"] == "PASS", check


# ---------------------------------------------------------------- model card / contamination


def test_contamination_check_compares_the_case_flag_with_the_model_card(client, data_dir):
    # llama3.1:8b (default model): training data to Dec 2023, released 2024-07-23.
    write_case(data_dir, case_file("synthetic_old_unlikely", as_of=datetime(2023, 6, 1, tzinfo=UTC), flag="unlikely"))
    write_case(data_dir, case_file("synthetic_old_likely", as_of=datetime(2023, 6, 1, tzinfo=UTC), flag="likely"))
    write_case(data_dir, case_file("synthetic_new_unlikely", as_of=datetime(2025, 3, 1, tzinfo=UTC), flag="unlikely"))
    for eid, expected in (
        ("synthetic_old_unlikely", "FAIL"),
        ("synthetic_old_likely", "PASS"),
        ("synthetic_new_unlikely", "PASS"),
    ):
        check = checks(get(client, case_id=eid))["model_contamination_disclosed"]
        assert check["status"] == expected, (eid, check)
        assert facts(check)["Model"] == "llama3.1:8b"
        assert facts(check)["Training data ends (model card)"] == "2023-12"


def test_contamination_is_not_available_for_a_model_without_a_verified_cutoff(client, data_dir, monkeypatch):
    monkeypatch.setenv("FAULTLINE_OLLAMA_MODEL", "gemma4:e2b")
    write_case(data_dir, case_file())
    check = checks(get(client, case_id=EVENT))["model_contamination_disclosed"]
    assert check["status"] == "NOT AVAILABLE", check
    assert facts(check)["Training data ends (model card)"] == "NOT AVAILABLE"


# ---------------------------------------------------------------- run checks (per prediction)


def test_run_checks_pass_for_an_honest_persisted_forecast(client, data_dir):
    write_case(data_dir, case_file())
    pred = persist(data_dir)
    body = get(client, prediction_id=pred.prediction_id)  # the case is taken from the stored forecast
    assert body["case_id"] == EVENT and body["prediction_provenance"] == "RECORDED_RUN"
    by_id = checks(body)
    for cid in RUN_CHECKS:
        assert by_id[cid]["status"] == "PASS", by_id[cid]
    hashes = facts(by_id["run_hashes_match"])
    assert hashes["prompt_sha256 (stored)"] == pred.prompt_sha256
    assert hashes["prompt_sha256 (recomputed)"] == pred.prompt_sha256
    assert hashes["snapshot_sha256 (recomputed)"] == pred.snapshot_sha256
    order = facts(by_id["persisted_before_reveal"])
    assert order["First reveal for this event"] == "none yet"


def test_unknown_prediction_is_not_available_not_pass(client, data_dir):
    write_case(data_dir, case_file())
    persist(data_dir)
    by_id = checks(get(client, case_id=EVENT, prediction_id="pred_missing"))
    for cid in RUN_CHECKS:
        assert by_id[cid]["status"] == "NOT AVAILABLE", by_id[cid]


def test_prediction_for_another_case_is_rejected(client, data_dir):
    write_case(data_dir, case_file())
    write_case(data_dir, case_file("synthetic_other_case"))
    pred = persist(data_dir)
    resp = client.get("/api/integrity", params={"case_id": "synthetic_other_case", "prediction_id": pred.prediction_id})
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_missing_prediction_store_is_not_created(client, data_dir):
    write_case(data_dir, case_file())
    db = store_module.DEFAULT_DB_PATH
    assert not db.exists()
    by_id = checks(get(client, case_id=EVENT, prediction_id="pred_x"))
    assert by_id["run_hashes_match"]["status"] == "NOT AVAILABLE"
    assert not db.exists(), "a read-only check must not create the prediction store"


def test_tampered_record_flips_the_hash_check(client, data_dir):
    write_case(data_dir, case_file())
    pred = persist(data_dir)
    with sqlite3.connect(store_module.DEFAULT_DB_PATH) as conn:
        conn.execute("DROP TRIGGER predictions_no_update")
        conn.execute("UPDATE predictions SET p_yes = 0.9 WHERE prediction_id = ?", (pred.prediction_id,))
    check = checks(get(client, prediction_id=pred.prediction_id))["run_hashes_match"]
    assert check["status"] == "FAIL", check
    assert any("record_sha256" in f["value"] for f in check["facts"])


def test_editing_the_case_after_the_run_flips_the_gate_replay_check(client, data_dir):
    write_case(data_dir, case_file())
    pred = persist(data_dir)
    edited = case_file()
    edited["evidence"][0]["content"] = "SYNTHETIC evidence text, edited after the run."
    write_case(data_dir, edited)
    check = checks(get(client, prediction_id=pred.prediction_id))["run_matches_gate"]
    assert check["status"] == "FAIL", check


def test_forecast_saved_after_a_reveal_flips_the_order_check(client, data_dir):
    write_case(data_dir, case_file())
    first = persist(data_dir, pid="pred_int_first")
    store = PredictionStore(store_module.DEFAULT_DB_PATH)
    # Audit-log entry only; the sealed file is not read.
    store.record_reveal(first, datetime.now(UTC), sealed_provenance="SYNTHETIC")
    late = persist(data_dir, pid="pred_int_late")
    assert checks(get(client, prediction_id=first.prediction_id))["persisted_before_reveal"]["status"] == "PASS"
    check = checks(get(client, prediction_id=late.prediction_id))["persisted_before_reveal"]
    assert check["status"] == "FAIL", check


# ---------------------------------------------------------------- system checks


def _copy_sources(dst: Path) -> Path:
    shutil.copytree(API_DIR, dst, ignore=shutil.ignore_patterns(".venv", "var", "data", "tests", "__pycache__",
                                                                "*.egg-info", "node_modules", ".*_cache"))
    return dst


def test_import_scan_passes_on_the_real_tree(client, data_dir):
    check = checks(get(client))["live_web_isolated"]
    assert check["status"] == "PASS", check
    f = facts(check)
    assert f["Imports or references to live web-search code"] == "0"
    assert int(f["Replay modules scanned"]) >= 5


@pytest.mark.parametrize(
    "module, line",
    [
        ("core/temporal_gate.py", "import agents.tavily\n"),
        ("core/provenance.py", "from routes import explore\n"),  # reached transitively from the gate and store
        ("agents/local_ollama.py", "import importlib\nimportlib.import_module('tavily')\n"),
    ],
)
def test_import_scan_flips_when_a_replay_module_reaches_live_web_code(client, data_dir, tmp_path, monkeypatch,
                                                                       module, line):
    root = _copy_sources(tmp_path / "src")
    path = root / module
    path.write_text(path.read_text(encoding="utf-8") + "\n" + line, encoding="utf-8")
    monkeypatch.setattr(integrity, "SOURCE_ROOT", root)
    check = checks(get(client))["live_web_isolated"]
    assert check["status"] == "FAIL", check
    assert facts(check)["Imports or references to live web-search code"] != "0"


def test_import_scan_with_no_replay_modules_is_not_available(client, data_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(integrity, "SOURCE_ROOT", tmp_path / "empty")
    assert checks(get(client))["live_web_isolated"]["status"] == "NOT AVAILABLE"


def _fake_optimizer(cut_off: float, cut_on: float, status_on: str = "OPTIMAL") -> types.ModuleType:
    """Stand-in solver: cut share ``cut_off`` with Protect payroll off (the control), ``cut_on`` with it on."""
    mod = types.ModuleType("fake_optimizer")
    mod.DisruptionCosts = lambda **kw: types.SimpleNamespace(**kw)
    mod.OptimizerSettings = lambda **kw: types.SimpleNamespace(**kw)
    seen = []

    def optimize(params, shock, protect_payroll, settings=None):
        seen.append(settings.disruption_costs.payroll_cut_per_dollar)
        status = status_on if protect_payroll else "OPTIMAL"
        plan = types.SimpleNamespace(payroll_cut=[0.0, cut_on if protect_payroll else cut_off])
        return types.SimpleNamespace(status=status, plan=plan if status == "OPTIMAL" else None)

    mod.optimize = optimize
    mod.seen = seen
    return mod


def test_payroll_check_uses_the_real_optimizer_when_present(client, data_dir):
    import importlib.util

    check = checks(get(client))["payroll_hard_constraint"]
    if importlib.util.find_spec("core.optimizer") is None:
        assert check["status"] == "NOT AVAILABLE", check
    else:
        assert check["status"] == "PASS", check
        assert facts(check)["Control, Protect payroll OFF: plans that cut payroll"] != "0"


@pytest.mark.parametrize(
    "solver, expected",
    [
        (lambda: _fake_optimizer(0.1, 0.0), "PASS"),
        (lambda: _fake_optimizer(0.1, 0.05), "FAIL"),  # the bound is broken
        (lambda: _fake_optimizer(0.1, 0.0, status_on="NO FEASIBLE PLAN"), "PASS"),
        (lambda: _fake_optimizer(0.0, 0.0), "NOT AVAILABLE"),  # control never cuts: the bound was not observed
        (lambda: None, "NOT AVAILABLE"),  # no optimizer in this build
    ],
)
def test_payroll_check_flips_when_the_solver_cuts_payroll(client, data_dir, monkeypatch, solver, expected):
    fake = solver()
    monkeypatch.setattr(integrity, "_load_optimizer", lambda: fake)
    check = checks(get(client))["payroll_hard_constraint"]
    assert check["status"] == expected, check
    if fake is not None:
        assert fake.seen and set(fake.seen) == {0.0}, "the probe must make payroll cuts free"


# ---------------------------------------------------------------- pre-reveal safety (leakage)


def test_response_has_no_outcome_keys_and_never_the_sealed_canary(client, data_dir):
    write_case(data_dir, case_file())
    pred = persist(data_dir)
    PredictionStore(store_module.DEFAULT_DB_PATH).record_reveal(pred, datetime.now(UTC), sealed_provenance="SYNTHETIC")
    for params in ({}, {"case_id": EVENT}, {"prediction_id": pred.prediction_id}):
        resp = client.get("/api/integrity", params=params)
        assert resp.status_code == 200
        assert CANARY not in resp.text
        bad = [p for p, k in walk_keys(resp.json()) if OUTCOME_LIKE.search(str(k))]
        assert bad == [], bad


def test_response_schema_has_no_outcome_like_property(client):
    schema = client.get("/openapi.json").json()["components"]["schemas"]
    names = [n for n in schema if n.startswith("Integrity")]
    assert names
    for name in names:
        bad = [p for p, k in walk_keys(schema[name].get("properties", {})) if OUTCOME_LIKE.search(str(k))]
        assert bad == [], (name, bad)


def test_integrity_route_does_not_import_the_evaluator():
    tree = ast.parse(Path(integrity.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(f"{node.module}.{a.name}" for a in node.names)
    assert not any("evaluator" in n for n in names), names


def test_report_does_not_read_the_sealed_folder(client, data_dir):
    """Belt and braces: the route's own monitor and the test's audit view agree that nothing sealed was opened."""
    write_case(data_dir, case_file())
    pred = persist(data_dir)
    integrity.MONITOR.reset()
    get(client, case_id=EVENT, prediction_id=pred.prediction_id)
    assert integrity.MONITOR.snapshot()[0] == 0


# ---------------------------------------------------------------- audit round 1 (PR #93): prompt text, probe, paths


def test_mutation_rendering_withheld_text_into_the_prompt_flips_both_checks(client, data_dir, monkeypatch):
    """The payload can be clean while the prompt string leaks: both checks must read the rendered prompt."""
    write_case(data_dir, case_file())
    assert checks(get(client, case_id=EVENT))["evidence_cutoff"]["status"] == "PASS"
    late_text = "SYNTHETIC evidence text evid_late."
    original = temporal_gate._render

    def leaky_render(snap, variant, payload):
        return original(snap, variant, payload) + f"\n{late_text} settled {CANARY}\n"

    monkeypatch.setattr(temporal_gate, "_render", leaky_render)
    by_id = checks(get(client, case_id=EVENT))
    cutoff, stripped = by_id["evidence_cutoff"], by_id["outcome_fields_stripped"]
    assert cutoff["status"] == "FAIL", cutoff
    assert facts(cutoff)["Withheld items whose id, title or text is in a prompt"] != "0"
    assert stripped["status"] == "FAIL", stripped
    assert facts(stripped)["Values of dropped fields found in a prompt"] != "0"


def test_mutation_leaking_a_withheld_id_into_the_prompt_flips_the_cutoff_check(client, data_dir, monkeypatch):
    write_case(data_dir, case_file())
    original = temporal_gate._render
    monkeypatch.setattr(temporal_gate, "_render", lambda snap, v, payload: original(snap, v, payload) + "evid_late")
    assert checks(get(client, case_id=EVENT))["evidence_cutoff"]["status"] == "FAIL"


def test_strip_check_tests_the_protection_even_when_the_case_has_nothing_to_strip(client, data_dir, monkeypatch):
    evidence_items = [e for e in standard_evidence() if e["evidence_id"] != "evid_keyed"]
    write_case(data_dir, case_file(evidence_items=evidence_items))
    honest = checks(get(client, case_id=EVENT))["outcome_fields_stripped"]
    assert honest["status"] == "PASS", honest
    assert facts(honest)["Outcome-like fields dropped from candidate items"] == "0"
    assert facts(honest)["Built-in stripping probe: outcome-like keys that survived"] == "0"

    monkeypatch.setattr(temporal_gate, "strip_outcome_keys", lambda obj, allow_market_side=False: obj)
    check = checks(get(client, case_id=EVENT))["outcome_fields_stripped"]
    assert check["status"] == "FAIL", check
    assert facts(check)["Built-in stripping probe: outcome-like keys that survived"] != "0"


def test_sealed_read_through_a_symlink_alias_is_seen(client, data_dir, tmp_path, make_symlink):
    write_case(data_dir, case_file())
    alias = tmp_path / "harmless_looking_dir"
    make_symlink(alias, data_dir / "sealed_outcomes", target_is_directory=True)
    (alias / f"{EVENT}.json").read_text(encoding="utf-8")
    check = checks(get(client, case_id=EVENT))["sealed_folder_untouched"]
    assert check["status"] == "FAIL", check


def test_sealed_relative_read_after_chdir_is_seen(client, data_dir):
    write_case(data_dir, case_file())
    here = os.getcwd()
    os.chdir(data_dir / "sealed_outcomes")
    try:
        with open(f"{EVENT}.json", encoding="utf-8") as fh:  # relative path: no folder name in it
            fh.read()
    finally:
        os.chdir(here)
    check = checks(get(client, case_id=EVENT))["sealed_folder_untouched"]
    assert check["status"] == "FAIL", check


def test_sealed_read_of_the_configured_folder_under_another_name_is_seen(tmp_path, monkeypatch, make_symlink):
    """The configured folder is matched by realpath, not by its name."""
    data = tmp_path / "data"
    (data / "sealed_outcomes").mkdir(parents=True)
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(data))
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert integrity.is_sealed_path(str(data / "sealed_outcomes" / "x.json"))
    assert integrity.is_sealed_path(str(data / "SEALED_OUTCOMES" / "x.json"))
    assert not integrity.is_sealed_path(str(other / "x.json"))
    link = tmp_path / "plain"
    make_symlink(link, data / "sealed_outcomes", target_is_directory=True)
    assert integrity.is_sealed_path(str(link / "x.json"))


def test_sealed_check_states_its_dir_fd_and_hard_link_limit(client, data_dir):
    check = checks(get(client))["sealed_folder_untouched"]
    assert "dir_fd" in check["explanation"] and "hard link" in check["explanation"]


@pytest.mark.parametrize(
    "source",
    [
        "import importlib\nimportlib.import_module('agents.' + 'tav' + 'ily')",
        "import importlib\nimportlib.import_module(name='agents.tavily')",
        "import sys\nm = sys.modules['agents.tavily']",
        "import httpx\nhttpx.post('https://api.tavily.com/search', json={})",
        "def f(request):\n    return request.app.state.faultline_explore",
        "from routes.explore import explore_search",
        "def run(tavily_client):\n    return tavily_client",
        "x = f'agents.{\"tav\"}ily'",
    ],
)
def test_reference_scan_flags_each_known_evasion(source):
    assert integrity.live_web_refs(ast.parse(source)), source


@pytest.mark.parametrize(
    "source",
    [
        "settings.tavily_api_key_set",
        "notice = 'TAVILY_API_KEY not set: Live Explore web search is disabled.'",
        "# import agents.tavily  (a comment is not code)\nx = 1",
    ],
)
def test_reference_scan_allows_key_presence_plumbing_and_comments(source):
    assert integrity.live_web_refs(ast.parse(source)) == set()


def test_reference_scan_limit_names_built_at_run_time_are_not_seen(client, data_dir):
    """Documented limit, asserted so it is never silently claimed: a name built from variables is invisible."""
    source = "a = 'tav'\nb = a + 'ily'\nimport importlib\nimportlib.import_module(b)"
    assert integrity.live_web_refs(ast.parse(source)) == set()
    assert "run time" in checks(get(client))["live_web_isolated"]["explanation"]


def test_reference_in_a_replay_module_flips_the_live_web_check(client, data_dir, tmp_path, monkeypatch):
    root = _copy_sources(tmp_path / "src")
    path = root / "agents" / "provider.py"
    path.write_text(path.read_text(encoding="utf-8") + "\nimport httpx\nhttpx.post('https://api.tavily.com/x')\n",
                    encoding="utf-8")
    monkeypatch.setattr(integrity, "SOURCE_ROOT", root)
    check = checks(get(client))["live_web_isolated"]
    assert check["status"] == "FAIL", check


_PR73_LIVE_EXPLORE = re.compile(r"tavily|faultline_explore|routes\.explore|explore_search", re.IGNORECASE)
_PR73_KEY_PRESENCE = re.compile(r"TAVILY_API_KEY|tavily_api_key(?:_set)?")


def test_this_route_contains_no_token_pr73_forbids():
    """PR #73's separation sweep (no constant folding) must find nothing in routes/integrity.py."""
    tree = ast.parse(Path(integrity.__file__).read_text(encoding="utf-8"))
    hits = []
    for node in ast.walk(tree):
        texts = []
        if isinstance(node, ast.alias):
            texts = [node.name, node.asname]
        elif isinstance(node, ast.ImportFrom):
            texts = [node.module]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            texts = [node.value]
        elif isinstance(node, ast.Attribute):
            texts = [node.attr]
        elif isinstance(node, ast.Name):
            texts = [node.id]
        elif isinstance(node, ast.keyword):
            texts = [node.arg]
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            texts = [node.name]
        elif isinstance(node, ast.arg):
            texts = [node.arg]
        for text in texts:
            if text and (_PR73_LIVE_EXPLORE.search(_PR73_KEY_PRESENCE.sub("", text)) or text == "explore"):
                hits.append(text)
    assert hits == []


# ---------------------------------------------------------------- read-only store, cache


def test_get_never_writes_the_prediction_store(client, data_dir):
    write_case(data_dir, case_file())
    pred = persist(data_dir)
    db = store_module.DEFAULT_DB_PATH
    before = (db.read_bytes(), db.stat().st_mtime_ns)
    assert checks(get(client, prediction_id=pred.prediction_id))["run_hashes_match"]["status"] == "PASS"
    assert (db.read_bytes(), db.stat().st_mtime_ns) == before


def test_old_store_schema_is_not_available_and_not_migrated(client, data_dir):
    write_case(data_dir, case_file())
    db = store_module.DEFAULT_DB_PATH
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE predictions (prediction_id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE audit_log (seq INTEGER PRIMARY KEY)")
    by_id = checks(get(client, case_id=EVENT, prediction_id="pred_x"))
    for cid in RUN_CHECKS:
        assert by_id[cid]["status"] == "NOT AVAILABLE", by_id[cid]
    with sqlite3.connect(db) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(predictions)")]
    assert cols == ["prediction_id"], "a GET must not migrate the schema"


def test_system_checks_are_cached_and_say_so(client, data_dir, tmp_path, monkeypatch):
    first = checks(get(client))["live_web_isolated"]
    assert facts(first)["Cache"].startswith("code-level check, cached up to 60 s")
    root = _copy_sources(tmp_path / "src")
    (root / "core" / "temporal_gate.py").write_text("import agents.tavily\n", encoding="utf-8")
    monkeypatch.setattr(integrity, "SOURCE_ROOT", root)  # a new root is a new cache key
    assert checks(get(client))["live_web_isolated"]["status"] == "FAIL"
    monkeypatch.setattr(integrity, "SOURCE_ROOT", API_DIR)
    again = checks(get(client))["live_web_isolated"]
    assert facts(again)["Computed at"] == facts(first)["Computed at"]  # reused, not recomputed


def _pr73_evasions() -> list[str]:
    from test_explore_separation import EVASIONS  # main's separation sweep (#73): its list, not a copy

    return list(EVASIONS)


@pytest.mark.parametrize("source", _pr73_evasions())
def test_panel_scan_flags_every_evasion_the_separation_sweep_knows(source):
    """The panel's live scan must be at least as strict as #73's sweep on every evasion that sweep lists."""
    assert integrity.live_web_refs(ast.parse(source)), source


def test_synthetic_venue_quotes_are_audited_like_any_quote(client, data_dir):
    """#111: a synthetic-venue quote (provenance SYNTHETIC, own label) passes the same window and stripping checks."""
    from test_synthetic_venue import syn_quote_dict

    quotes = [
        syn_quote_dict(AS_OF - timedelta(hours=2), "0.35", market_id="FAULTLINE-SYN-INT"),
        syn_quote_dict(AS_OF + timedelta(hours=1), "0.91", market_id="FAULTLINE-SYN-INT"),
    ]
    write_case(data_dir, case_file(quotes=quotes))
    body = get(client, case_id=EVENT)
    by_id = checks(body)
    assert by_id["evidence_cutoff"]["status"] == "PASS", by_id["evidence_cutoff"]
    assert facts(by_id["evidence_cutoff"])["Market quotes the model could see"] == "1"
    assert by_id["outcome_fields_stripped"]["status"] == "PASS", by_id["outcome_fields_stripped"]
    assert "agent_plus_market" in facts(by_id["outcome_fields_stripped"])["Model inputs checked"]
