"""Sealed outcomes, future-fact canary, provenance hashing and persist-before-reveal (SPEC §5, §10).

Written before core/provenance.py, core/store.py and core/evaluator.py. All fixtures are SYNTHETIC.
"""

from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_temporal_gate import (
    _RECORDER,
    AS_OF,
    EVENT,
    case_file_dict,
    evidence_dict,
    outcome_keys_in_snapshot,
    quote_dict,
    standard_record,
    walk_keys,
    write_case_file,
)

from core import provenance
from core import store as store_module
from core.evaluator import (
    NotRevealable,
    OutcomeNotAvailable,
    OutcomeVault,
    RevealedOutcome,
    build_scorecard,
)
from core.store import DEFAULT_DB_PATH, HashMismatch, PredictionExists, PredictionStore, record_sha256
from core.temporal_gate import EvidenceStore, MarketNotAvailable, ModelInput
from models import ErrorCode, Prediction, Provenance

API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = API_DIR.parents[1]
RECORDED = datetime(2025, 1, 15, 12, 5, tzinfo=UTC)


class Clock:
    """Deterministic clock: each call advances one second."""

    def __init__(self, start: datetime) -> None:
        self.t = start

    def __call__(self) -> datetime:
        self.t += timedelta(seconds=1)
        return self.t


def sealed_dict(event_id: str = EVENT, outcome: str = "YES", notes: str | None = None) -> dict:
    return {
        "event_id": event_id,
        "outcome": outcome,
        "resolved_at": (AS_OF + timedelta(days=7)).isoformat(),
        "source_url": "https://example.org/settlement",
        "provenance": "SYNTHETIC",
        "notes": notes,
    }


def write_sealed(sealed_dir: Path, data: dict) -> Path:
    sealed_dir.mkdir(parents=True, exist_ok=True)
    path = sealed_dir / f"{data['event_id']}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def prediction_for(mi, snap, *, pid: str = "pred_001", p_yes: float = 0.6, **overrides) -> Prediction:
    data = dict(
        prediction_id=pid,
        event_id=snap.case.event_id,
        as_of=snap.as_of,
        agent_model="ollama/test-model",
        model_digest=None,
        variant=mi.variant,
        p_yes=p_yes,
        decision="wait",
        rationale="SYNTHETIC test rationale.",
        evidence_ids=list(mi.evidence_ids),
        prompt_sha256=mi.prompt_sha256,
        snapshot_sha256=mi.snapshot_sha256,
        temperature=0.0,
        seed=7,
        recorded_at=RECORDED,
        provenance=Provenance.RECORDED_RUN,
    )
    data.update(overrides)
    return Prediction(**data)


@pytest.fixture
def world(tmp_path):
    """A store + vault over a tmp data dir with one sealed SYNTHETIC case."""
    sealed = tmp_path / "data" / "sealed_outcomes"
    write_sealed(sealed, sealed_dict())
    store = PredictionStore(tmp_path / "var" / "predictions.sqlite3", clock=Clock(RECORDED))
    vault = OutcomeVault(store, sealed_dir=sealed, clock=Clock(RECORDED + timedelta(hours=1)))
    snap = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF)
    return store, vault, snap, sealed


# ---------------------------------------------------------------- future-fact canary (SPEC §5 control e)


CANARY = f"CANARY-{uuid.uuid4()}"
VISIBLE = f"VISIBLE-{uuid.uuid4()}"


def build_canary_tree(root: Path) -> tuple[Path, Path]:
    """Two cases. The canary is placed ONLY in data the gate must exclude; VISIBLE only in admissible data."""
    cases, sealed = root / "data" / "demo_cases", root / "data" / "sealed_outcomes"
    for event_id, with_market in (("synthetic_canary_a", True), ("synthetic_canary_b", False)):
        leaky_key = evidence_dict("evid_key", AS_OF - timedelta(days=2), "Admissible text.", event_id=event_id)
        leaky_key["resolution_note"] = f"settled YES {CANARY}"
        quotes = [
            quote_dict(AS_OF - timedelta(hours=30), "0.40", volume=f"stale {CANARY}"),
            quote_dict(AS_OF + timedelta(hours=1), "0.99", volume=f"future {CANARY}"),
        ]
        if with_market:
            quotes.append(
                quote_dict(AS_OF - timedelta(hours=1), "0.56", source_url=f"https://example.org/api/{CANARY}")
            )
        data = case_file_dict(
            event_id,
            evidence=[
                evidence_dict("evid_ok", AS_OF - timedelta(days=1), f"Admissible {VISIBLE}.", event_id=event_id),
                evidence_dict("evid_future", AS_OF + timedelta(hours=1), f"Leak {CANARY}", event_id=event_id),
                evidence_dict(
                    "evid_unverified",
                    AS_OF - timedelta(days=3),
                    f"Leak {CANARY}",
                    event_id=event_id,
                    retrospective_unverified=True,
                ),
                evidence_dict("evid_wrong", AS_OF - timedelta(days=3), f"Leak {CANARY}", event_id="another_event"),
                evidence_dict(
                    "evid_archived",
                    AS_OF - timedelta(days=4),
                    "Archived admissible text.",
                    event_id=event_id,
                    archive_url=f"https://web.archive.org/web/2026/{CANARY}",
                ),
                leaky_key,
            ],
            quotes=quotes,
        )
        data["curation_notes"] = f"curator saw the result: {CANARY}"
        write_case_file(cases, data)
        write_sealed(sealed, sealed_dict(event_id, notes=f"sealed {CANARY}"))
    return cases, sealed


def test_canary_never_reaches_any_prompt_or_snapshot(tmp_path):
    cases, sealed = build_canary_tree(tmp_path)
    # The canary really is on disk, in both excluded case data and sealed outcomes.
    assert all(CANARY in p.read_text("utf-8") for p in [*cases.glob("*.json"), *sealed.glob("*.json")])

    store = EvidenceStore.from_dir(cases)
    assert store.case_ids() == ["synthetic_canary_a", "synthetic_canary_b"]
    rendered = 0
    for case_id in store.case_ids():
        snap = store.get_as_of(case_id, AS_OF)
        outputs = [repr(snap), store.public_case(case_id).model_dump_json()]
        for variant in ("agent_only", "agent_plus_market"):
            try:
                mi = snap.model_input(variant)
            except MarketNotAvailable:
                assert variant == "agent_plus_market" and case_id == "synthetic_canary_b"
                continue
            outputs += [mi.prompt, mi.snapshot_json]
            assert VISIBLE in mi.prompt  # positive control: admissible text does reach the prompt
            assert outcome_keys_in_snapshot(json.loads(mi.snapshot_json)) == []
            rendered += 1
        for text in outputs:
            assert CANARY not in text
    assert rendered == 3


def test_repo_cases_have_no_outcome_keys_or_future_evidence():
    """Runs on whatever real cases exist under data/demo_cases (none until issue #20 lands)."""
    store = EvidenceStore.from_dir()
    if not store.case_ids():
        pytest.skip("no cases in services/api/data/demo_cases yet (issue #20)")
    for case_id in store.case_ids():
        snap = store.get_as_of(case_id, store.public_case(case_id).as_of)
        variants = ["agent_only"] + (["agent_plus_market"] if snap.market_available else [])
        for variant in variants:
            obj = json.loads(snap.model_input(variant).snapshot_json)
            assert outcome_keys_in_snapshot(obj) == []
            for item in obj["evidence"]:
                assert datetime.fromisoformat(item["available_at"]) <= snap.as_of


def test_sealed_outcomes_dir_exists_and_var_is_git_ignored():
    assert (API_DIR / "data" / "sealed_outcomes").is_dir()
    assert "services/api/var/" in (REPO_ROOT / ".gitignore").read_text("utf-8").splitlines()
    assert DEFAULT_DB_PATH.parent == API_DIR / "var"


# ---------------------------------------------------------------- provenance hashing


def test_canonical_json_is_sorted_compact_utf8():
    assert provenance.canonical_json({"b": 1, "a": [1, {"d": 2, "c": "é"}]}) == '{"a":[1,{"c":"é","d":2}],"b":1}'


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), datetime(2025, 1, 1, tzinfo=UTC), {1: "x"}, b"x"])
def test_canonical_json_refuses_ambiguous_values(bad):
    with pytest.raises((TypeError, ValueError)):
        provenance.canonical_json({"k": bad})


def test_sha256_known_vectors():
    assert provenance.sha256_hex("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert provenance.prompt_sha256("abc") == provenance.sha256_hex("abc")
    payload = {"evidence": [], "market_quotes": []}
    assert provenance.snapshot_sha256(payload) == provenance.sha256_hex('{"evidence":[],"market_quotes":[]}')


def test_snapshot_payload_requires_exact_shape():
    with pytest.raises(ValueError):
        provenance.snapshot_sha256({"evidence": []})
    with pytest.raises(ValueError):
        provenance.snapshot_sha256({"evidence": [], "market_quotes": [], "outcome": 1})


# ---------------------------------------------------------------- persist-before-reveal


def test_reveal_before_persist_raises_and_does_not_touch_sealed_dir(world):
    _store, vault, _snap, _sealed = world
    _RECORDER.paths = []
    _RECORDER.active = True
    try:
        with pytest.raises(NotRevealable) as exc:
            vault.reveal("pred_001")
    finally:
        _RECORDER.active = False
    assert exc.value.code == ErrorCode.NOT_REVEALABLE
    assert [p for p in _RECORDER.paths if "sealed_outcomes" in p] == []


def test_reveal_after_persist_returns_outcome_and_is_logged(world):
    store, vault, snap, _ = world
    mi = snap.model_input("agent_only")
    pred = prediction_for(mi, snap)
    saved = store.save(pred, mi)
    revealed = vault.reveal("pred_001")
    assert isinstance(revealed, RevealedOutcome)
    assert revealed.y == 1 and revealed.prediction == pred
    assert (revealed.persisted_at, revealed.persist_seq) == (saved.persisted_at, saved.persist_seq)
    assert revealed.event_first_reveal_seq == revealed.reveal_seq > revealed.persist_seq
    assert revealed.event_first_revealed_at == revealed.revealed_at
    assert revealed.persisted_before_outcome_revealed
    reveals = store.reveal_times("pred_001")
    assert len(reveals) == 1 and saved.persisted_at < reveals[0] == revealed.revealed_at


def test_reveal_clock_before_persist_time_is_refused(tmp_path):
    sealed = tmp_path / "sealed_outcomes"
    write_sealed(sealed, sealed_dict())
    store = PredictionStore(tmp_path / "p.sqlite3", clock=Clock(RECORDED + timedelta(days=1)))
    vault = OutcomeVault(store, sealed_dir=sealed, clock=Clock(RECORDED))  # clock behind the store's
    snap = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF)
    mi = snap.model_input("agent_only")
    store.save(prediction_for(mi, snap), mi)
    with pytest.raises(NotRevealable, match="precedes"):
        vault.reveal("pred_001")
    assert store.reveal_times("pred_001") == []


def test_revealed_outcome_cannot_be_forged(world):
    store, vault, snap, _ = world
    mi = snap.model_input("agent_only")
    store.save(prediction_for(mi, snap), mi)
    real = vault.reveal("pred_001")
    with pytest.raises(TypeError):
        dataclasses.replace(real, y=0)
    with pytest.raises(TypeError):
        RevealedOutcome(**{f.name: getattr(real, f.name) for f in dataclasses.fields(real)})


def test_save_requires_the_gate_model_input(world):
    store, _, snap, _ = world
    mi = snap.model_input("agent_only")
    pred = prediction_for(mi, snap)
    with pytest.raises(TypeError):
        store.save(pred, {"prompt": mi.prompt, "snapshot_json": mi.snapshot_json})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        dataclasses.replace(mi, prompt="forged")
    with pytest.raises(TypeError):
        ModelInput(**dataclasses.asdict(mi))
    assert store.get("pred_001") is None


FORGED_SNAPSHOT = provenance.canonical_json(
    {"evidence": [{"evidence_id": "x", "available_at": "2030-01-01T00:00:00Z", "content": CANARY}], "market_quotes": []}
)


@pytest.mark.parametrize(
    ("overrides", "error", "match"),
    [
        ({"event_id": "other_event"}, ValueError, "event_id"),
        ({"as_of": AS_OF - timedelta(days=7)}, ValueError, "as_of"),
        ({"prompt_sha256": "0" * 64}, HashMismatch, "prompt_sha256"),
        ({"snapshot_sha256": provenance.sha256_hex(FORGED_SNAPSHOT)}, HashMismatch, "snapshot_sha256"),
        ({"variant": "agent_plus_market"}, ValueError, "agent_plus_market"),
        ({"variant": "hosted_comparator"}, ValueError, "hosted_comparator"),
    ],
    ids=["event", "as_of", "prompt-hash", "forged-snapshot-hash", "variant", "hosted-comparator"],
)
def test_save_rejects_prediction_not_matching_its_model_input(world, overrides, error, match):
    store, vault, snap, _ = world
    mi = snap.model_input("agent_only")
    with pytest.raises(error, match=match):
        store.save(prediction_for(mi, snap, **overrides), mi)
    assert store.get("pred_001") is None
    with pytest.raises(NotRevealable):
        vault.reveal("pred_001")


def test_save_rejects_agent_only_claim_for_market_snapshot(world):
    store, _, snap, _ = world
    plus = snap.model_input("agent_plus_market")
    with pytest.raises(ValueError, match="agent_only"):
        store.save(prediction_for(plus, snap, variant="agent_only"), plus)


@pytest.mark.parametrize(
    ("source", "claimed"), [("agent_plus_market", "agent_only"), ("agent_only", "agent_plus_market")]
)
def test_save_checks_snapshot_contents_against_variant_even_if_model_input_is_relabeled(world, source, claimed):
    store, _, snap, _ = world
    mi = snap.model_input(source)
    object.__setattr__(mi, "variant", claimed)  # hashes still match the text; only the label lies
    with pytest.raises(ValueError, match="market quote"):
        store.save(prediction_for(mi, snap, variant=claimed), mi)


def test_save_rejects_model_input_tampered_after_creation(world):
    store, _, snap, _ = world
    mi = snap.model_input("agent_only")
    pred = prediction_for(mi, snap)
    object.__setattr__(mi, "snapshot_json", FORGED_SNAPSHOT)
    with pytest.raises(HashMismatch):
        store.save(pred, mi)


def test_save_rejects_citations_outside_the_snapshot(world):
    store, _, snap, _ = world
    mi = snap.model_input("agent_only")
    with pytest.raises(ValueError, match="evid_future"):
        store.save(prediction_for(mi, snap, evidence_ids=["evid_ok", "evid_future"]), mi)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE predictions SET p_yes = 0.99 WHERE prediction_id = 'pred_001'",
        "DELETE FROM predictions WHERE prediction_id = 'pred_001'",
        "INSERT OR REPLACE INTO predictions SELECT prediction_id, event_id, as_of, agent_model, model_digest, variant, "
        "0.99, decision, rationale, evidence_ids, prompt_sha256, snapshot_sha256, temperature, seed, recorded_at, "
        "provenance, prompt_text, snapshot_json, persisted_at, persist_seq, market_baseline_p_yes, "
        "market_baseline_ref, contamination_flag, synthetic, case_sha256, record_sha256, gated_prompt_sha256, "
        "attempts, transcript_sha256, num_ctx, num_predict, final_prompt_text FROM predictions",
        "UPDATE audit_log SET seq = seq + 100",
        "DELETE FROM audit_log",
        "INSERT OR REPLACE INTO audit_log (seq, kind, prediction_id, event_id, at) "
        "SELECT seq, 'persist', prediction_id, event_id, at FROM audit_log WHERE kind = 'reveal'",
        # Audit round 2: a caller-chosen seq could backdate a persist or plant an early fake reveal.
        "INSERT INTO audit_log (seq, kind, prediction_id, event_id, at) "
        "VALUES (0, 'persist', 'forged', 'synthetic_fed_001', '2025-01-01T00:00:00+00:00')",
        "INSERT INTO audit_log (seq, kind, prediction_id, event_id, at) "
        "VALUES (-7, 'reveal', 'pred_001', 'synthetic_fed_001', 'now')",
        "INSERT INTO audit_log (seq, kind, prediction_id, event_id, at) "
        "VALUES (-1, 'persist', 'forged', 'synthetic_fed_001', 'now')",
        "INSERT INTO audit_log (seq, kind, prediction_id, event_id, at) "
        "VALUES (1000, 'persist', 'forged', 'synthetic_fed_001', 'now')",
        "INSERT INTO audit_log (kind, prediction_id, event_id, at) VALUES ('reveal', 'ghost', 'other_event', 'now')",
        "INSERT INTO predictions SELECT 'forged', event_id, as_of, agent_model, model_digest, variant, p_yes, "
        "decision, rationale, evidence_ids, prompt_sha256, snapshot_sha256, temperature, seed, recorded_at, "
        "provenance, prompt_text, snapshot_json, persisted_at, 0, market_baseline_p_yes, market_baseline_ref, "
        "contamination_flag, synthetic, case_sha256, record_sha256, gated_prompt_sha256, attempts, "
        "transcript_sha256, num_ctx, num_predict, final_prompt_text FROM predictions",
    ],
    ids=[
        "update",
        "delete",
        "insert-or-replace",
        "log-update",
        "log-delete",
        "log-replace",
        "log-seq-zero",
        "log-negative-reveal",
        "log-explicit-minus-one",
        "log-explicit-high",
        "log-reveal-without-prediction",
        "prediction-without-log-entry",
    ],
)
def test_predictions_and_audit_log_are_append_only(world, sql):
    store, vault, snap, _ = world
    mi = snap.model_input("agent_only")
    store.save(prediction_for(mi, snap), mi)
    vault.reveal("pred_001")
    with pytest.raises(PredictionExists):
        store.save(prediction_for(mi, snap, p_yes=0.9), mi)
    with sqlite3.connect(store.path) as conn, pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute(sql)
    assert store.get("pred_001").p_yes == 0.6
    assert store.verify("pred_001") == []
    assert len(store.reveal_times("pred_001")) == 1


def test_store_round_trips_audit_fields_and_hashes_recompute(world):
    store, _, snap, _ = world
    mi = snap.model_input("agent_plus_market")
    pred = prediction_for(mi, snap, pid="pred_plus", model_digest="sha256:" + "d" * 64, seed=42)
    store.save(pred, mi)

    reopened = PredictionStore(store.path)  # a fresh connection sees the same row
    rec = reopened.get_record("pred_plus")
    assert rec.prediction == pred
    assert rec.prediction.agent_model == "ollama/test-model"
    assert (rec.prediction.temperature, rec.prediction.seed, rec.prediction.variant) == (0.0, 42, "agent_plus_market")
    # RECORDED RUN audit: recompute every hash from what was stored.
    assert provenance.prompt_sha256(rec.prompt) == rec.prediction.prompt_sha256
    assert provenance.sha256_hex(rec.snapshot_json) == rec.prediction.snapshot_sha256
    assert record_sha256(rec.prediction, rec.context, rec.persisted_at, rec.persist_seq) == rec.record_sha256
    assert (rec.context.market_baseline_p_yes, rec.context.market_baseline_ref) == (0.56, "kalshi:SYNTH-FED-H25")
    assert (rec.context.contamination_flag, rec.context.synthetic) == ("unlikely", True)
    assert reopened.verify("pred_plus") == []
    assert [p.prediction_id for p in reopened.list_predictions(event_id=EVENT)] == ["pred_plus"]


def _drop_triggers(conn: sqlite3.Connection) -> None:
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
        conn.execute(f"DROP TRIGGER {name}")


@pytest.mark.parametrize(
    ("sql", "problem"),
    [
        ("UPDATE predictions SET prompt_text = 'edited'", "prompt_sha256"),
        ("UPDATE predictions SET p_yes = 0.99", "record_sha256"),
        ("UPDATE predictions SET decision = 'act'", "record_sha256"),
        ("UPDATE predictions SET persisted_at = '2025-01-01T00:00:00+00:00'", "record_sha256"),
        ("UPDATE predictions SET persist_seq = 999", "record_sha256"),
        ("UPDATE predictions SET market_baseline_p_yes = 0.3", "record_sha256"),
        ("UPDATE predictions SET contamination_flag = 'likely'", "record_sha256"),
        ("UPDATE predictions SET synthetic = 0", "record_sha256"),
    ],
    ids=["prompt", "p_yes", "decision", "persisted_at", "persist_seq", "market", "contamination", "synthetic"],
)
def test_reveal_refuses_when_stored_record_was_tampered(world, sql, problem):
    store, vault, snap, _ = world
    mi = snap.model_input("agent_only")
    store.save(prediction_for(mi, snap), mi)
    with sqlite3.connect(store.path) as conn:
        _drop_triggers(conn)
        conn.execute(sql)
    assert any(problem in p for p in store.verify("pred_001"))
    with pytest.raises(NotRevealable, match="hash"):
        vault.reveal("pred_001")


def test_reveal_without_sealed_file_is_not_available(world):
    store, vault, snap, sealed = world
    (sealed / f"{EVENT}.json").unlink()
    mi = snap.model_input("agent_only")
    store.save(prediction_for(mi, snap), mi)
    with pytest.raises(OutcomeNotAvailable):
        vault.reveal("pred_001")


@pytest.mark.parametrize(
    "patch",
    [{"event_id": "other_event"}, {"outcome": "MAYBE"}, {"outcome": 1}, {"extra_field": "x"}],
    ids=["wrong-event", "bad-outcome", "int-outcome", "extra-field"],
)
def test_reveal_rejects_malformed_sealed_file(world, patch):
    store, vault, snap, sealed = world
    data = sealed_dict()
    data.update(patch)
    (sealed / f"{EVENT}.json").write_text(json.dumps(data), encoding="utf-8")
    mi = snap.model_input("agent_only")
    store.save(prediction_for(mi, snap), mi)
    with pytest.raises(ValueError):
        vault.reveal("pred_001")


def test_sealed_outcome_no_maps_to_zero(world):
    store, vault, snap, sealed = world
    write_sealed(sealed, sealed_dict(outcome="NO"))
    mi = snap.model_input("agent_only")
    store.save(prediction_for(mi, snap), mi)
    assert vault.reveal("pred_001").y == 0


# ---------------------------------------------------------------- forecast before outcome, per EVENT


def test_peek_then_predict_is_excluded(world):
    """Audit attack 1: reveal a throwaway forecast at an earlier as_of, then predict p_yes = y."""
    store, vault, _, _ = world
    gate = EvidenceStore([standard_record()])
    probe_snap = gate.get_as_of(EVENT, AS_OF - timedelta(seconds=1))
    probe_mi = probe_snap.model_input("agent_only")
    store.save(prediction_for(probe_mi, probe_snap, pid="probe", p_yes=0.5), probe_mi)
    y = vault.reveal("probe").y

    snap = gate.get_as_of(EVENT, AS_OF)
    mi = snap.model_input("agent_only")
    store.save(prediction_for(mi, snap, pid="after_peek", p_yes=float(y)), mi)
    late = vault.reveal("after_peek")  # revealing is allowed, but it is marked as post-outcome
    assert not late.persisted_before_outcome_revealed
    assert late.event_first_reveal_seq < late.persist_seq

    card = build_scorecard(vault)
    assert card.exclusions_by_reason == {"persisted_after_outcome_revealed": 1}
    assert card.exclusions[0].prediction_ids == ["after_peek"]
    assert [(p.prediction_id, p.reason) for p in card.ignored_predictions] == [
        ("after_peek", "persisted_after_outcome_revealed")
    ]
    # The probe itself was saved before any reveal, so it is a legitimate forecast at its own as_of; the
    # peeked prediction contributes nothing.
    assert [e.prediction_ids for e in card.per_event] == [["probe"]]


def test_peek_through_another_variant_is_excluded(world):
    store, vault, snap, _ = world
    plus = snap.model_input("agent_plus_market")
    store.save(prediction_for(plus, snap, pid="plus_first"), plus)
    vault.reveal("plus_first")
    only = snap.model_input("agent_only")
    store.save(prediction_for(only, snap, pid="only_after"), only)
    card = build_scorecard(vault, agent_variant="agent_only")
    assert card.exclusions_by_reason == {"persisted_after_outcome_revealed": 1}
    assert card.n_events == 0


def test_cherry_picking_runs_is_impossible(world):
    """Audit attack 2: save several runs for one snapshot, reveal all, try to score only the best."""
    store, vault, snap, _ = world
    mi = snap.model_input("agent_only")
    reveals = []
    for i, p in enumerate([0.2, 0.5, 0.9]):
        store.save(prediction_for(mi, snap, pid=f"run{i}", p_yes=p), mi)
    for i in range(3):
        reveals.append(vault.reveal(f"run{i}"))
    with pytest.raises(TypeError):
        build_scorecard([max(reveals, key=lambda r: r.prediction.p_yes)])  # type: ignore[arg-type]
    card = build_scorecard(vault)
    assert card.n_events == 0
    assert card.exclusions_by_reason == {"multiple_predictions": 1}
    assert card.exclusions[0].prediction_ids == ["run0", "run1", "run2"]


def test_saved_but_unrevealed_prediction_is_scored_via_the_vault(world):
    store, vault, snap, _ = world
    mi = snap.model_input("agent_only")
    store.save(prediction_for(mi, snap, p_yes=0.7), mi)
    assert store.reveal_times("pred_001") == []
    card = build_scorecard(vault)
    assert card.exclusions == [] and card.n_events == 1
    assert card.per_event[0].prediction_ids == ["pred_001"]
    assert card.per_event[0].brier["agent_only"] == pytest.approx(0.09)
    assert len(store.reveal_times("pred_001")) == 1  # the scorecard's reveal is logged


def test_pre_reveal_prediction_kept_and_post_reveal_one_ignored(world):
    store, vault, snap, _ = world
    gate = EvidenceStore([standard_record()])
    mi = snap.model_input("agent_only")
    store.save(prediction_for(mi, snap, pid="honest", p_yes=0.6), mi)
    probe_snap = gate.get_as_of(EVENT, AS_OF - timedelta(hours=1))
    probe_mi = probe_snap.model_input("agent_only")
    store.save(prediction_for(probe_mi, probe_snap, pid="probe"), probe_mi)
    vault.reveal("probe")
    store.save(prediction_for(mi, snap, pid="after_peek", p_yes=1.0), mi)
    card = build_scorecard(vault)
    assert card.per_event[0].prediction_ids == ["probe", "honest"]  # one event, two horizons
    assert [p.prediction_id for p in card.ignored_predictions] == ["after_peek"]
    assert card.exclusions == []


def test_configured_sealed_folder_only_reveals_into_the_configured_store(tmp_path, monkeypatch):
    """Audit round 2: a scratch store must not be able to peek at the real sealed folder without a trace."""

    data = tmp_path / "data"
    write_sealed(data / "sealed_outcomes", sealed_dict())
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(data))
    official_db = tmp_path / "var" / "predictions.sqlite3"
    monkeypatch.setenv("FAULTLINE_PREDICTIONS_DB", str(official_db))

    scratch = PredictionStore(tmp_path / "scratch.sqlite3")
    with pytest.raises(ValueError, match="configured prediction store"):
        OutcomeVault(scratch)  # default sealed folder = the configured one
    with pytest.raises(ValueError, match="configured prediction store"):
        OutcomeVault(scratch, sealed_dir=data / "sealed_outcomes")
    with pytest.raises(ValueError, match="configured prediction store"):
        OutcomeVault(scratch, sealed_dir=data / "demo_cases" / ".." / "sealed_outcomes")

    official = PredictionStore(official_db, clock=Clock(RECORDED))
    vault = OutcomeVault(official, clock=Clock(RECORDED + timedelta(hours=1)))
    snap = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF)
    mi = snap.model_input("agent_only")
    official.save(prediction_for(mi, snap), mi)
    assert vault.reveal("pred_001").y == 1


def test_scorecard_takes_no_caller_contexts(world):
    import core.evaluator as evaluator

    store, vault, snap, _ = world
    mi = snap.model_input("agent_only")
    store.save(prediction_for(mi, snap), mi)
    assert not hasattr(evaluator, "EventContext")
    with pytest.raises(TypeError):
        build_scorecard(vault, [])  # type: ignore[misc]
    with pytest.raises(TypeError):
        build_scorecard(vault, contexts=[])  # type: ignore[call-arg]
    card = build_scorecard(vault)
    assert card.per_event[0].market_refs == ["kalshi:SYNTH-FED-H25"]
    assert card.per_event[0].brier["market"] == pytest.approx((0.56 - 1) ** 2)


def test_reserved_low_seq_cannot_backdate_a_later_prediction(world):
    """round3_b: reserve an orphan persist seq before any reveal, peek, then insert a forecast on that seq."""
    store, vault, _snap, _ = world
    gate = EvidenceStore([standard_record()])
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "INSERT INTO audit_log (kind, prediction_id, event_id, at) VALUES ('persist', 'forged', ?, ?)",
            (EVENT, RECORDED.isoformat()),
        )
        reserved = conn.execute("SELECT max(seq) FROM audit_log").fetchone()[0]
    psnap = gate.get_as_of(EVENT, AS_OF - timedelta(hours=1))
    pmi = psnap.model_input("agent_only")
    store.save(prediction_for(pmi, psnap, pid="probe"), pmi)
    vault.reveal("probe")
    snap = gate.get_as_of(EVENT, AS_OF)
    mi = snap.model_input("agent_only")
    rec = store.save(prediction_for(mi, snap, pid="template"), mi)  # a valid row to copy, then forge its seq
    with sqlite3.connect(store.path) as conn, pytest.raises(sqlite3.DatabaseError, match="newest audit log entry"):
        conn.execute(
            "INSERT INTO predictions SELECT 'forged', event_id, as_of, agent_model, model_digest, variant, 1.0, "
            "decision, rationale, evidence_ids, prompt_sha256, snapshot_sha256, temperature, seed, recorded_at, "
            "provenance, prompt_text, snapshot_json, persisted_at, ?, market_baseline_p_yes, market_baseline_ref, "
            "contamination_flag, synthetic, case_sha256, record_sha256, gated_prompt_sha256, attempts, "
            "transcript_sha256, num_ctx, num_predict, final_prompt_text FROM predictions WHERE prediction_id = ?",
            (reserved, rec.prediction.prediction_id),
        )
    assert store.get("forged") is None


def test_replacing_a_prediction_with_a_fresh_persist_entry_is_refused(world):
    """Even with a newest, own persist entry (which satisfies the persist_seq trigger), an existing id is never
    replaced: INSERT OR REPLACE on a raw connection (recursive triggers off) is refused by the reuse trigger."""
    store, _, snap, _ = world
    mi = snap.model_input("agent_only")
    store.save(prediction_for(mi, snap), mi)
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "INSERT INTO audit_log (kind, prediction_id, event_id, at) VALUES ('persist', 'pred_001', ?, ?)",
            (EVENT, RECORDED.isoformat()),
        )
        newest = conn.execute("SELECT max(seq) FROM audit_log").fetchone()[0]
        with pytest.raises(sqlite3.DatabaseError, match="already persisted"):
            conn.execute(
                "INSERT OR REPLACE INTO predictions SELECT prediction_id, event_id, as_of, agent_model, model_digest, "
                "variant, 0.99, decision, rationale, evidence_ids, prompt_sha256, snapshot_sha256, temperature, seed, "
                "recorded_at, provenance, prompt_text, snapshot_json, persisted_at, ?, market_baseline_p_yes, "
                "market_baseline_ref, contamination_flag, synthetic, case_sha256, record_sha256, gated_prompt_sha256, "
                "attempts, transcript_sha256, num_ctx, num_predict, final_prompt_text FROM predictions",
                (newest,),
            )
    assert store.get("pred_001").p_yes == 0.6


# ---------------------------------------------------------------- pre-reveal payloads


def test_pre_reveal_payloads_walk_clean(world):
    store, _, snap, _ = world
    mi = snap.model_input("agent_plus_market")
    pred = prediction_for(mi, snap)
    store.save(pred, mi)
    outcome_like = re.compile(r"outcome|resolution|resolved|settle|result|winner|final_price", re.IGNORECASE)
    for payload in (pred.model_dump(mode="json"), store.get("pred_001").model_dump(mode="json")):
        assert [p for p, k, _ in walk_keys(payload) if outcome_like.search(k)] == []


# ---------------------------------------------------------------- question horizon covers the resolution (#158)


def _horizon_problems_via_vault() -> tuple[int, list[str], list[str], list[str]]:
    """Reveal every committed case through ``OutcomeVault`` (the only sealed-folder reader) into the scratch
    prediction store the autouse fixture configures, and return booleans only, never a sealed value:
    (cases checked, ids with no ``resolved_at``, ids resolved at or before ``as_of``, ids resolved after
    ``as_of + horizon_days``). The sealed objects never leave this function, so a failing assert cannot print one.
    """
    cases = EvidenceStore.from_dir()
    store = PredictionStore(store_module.configured_db_path())
    vault = OutcomeVault(store)  # default sealed folder = the committed one; refused unless the store is configured
    missing: list[str] = []
    not_after_cutoff: list[str] = []
    after_horizon: list[str] = []
    for i, case_id in enumerate(cases.case_ids()):
        snap = cases.get_as_of(case_id, cases.public_case(case_id).as_of)
        mi = snap.model_input("agent_only")
        store.save(prediction_for(mi, snap, pid=f"pred_horizon_{i:03d}"), mi)
        resolved_at = vault.reveal(f"pred_horizon_{i:03d}").sealed.resolved_at
        horizon_end = snap.as_of + timedelta(days=snap.case.horizon_days)
        if resolved_at is None:
            missing.append(case_id)
            continue
        if not resolved_at > snap.as_of:
            not_after_cutoff.append(case_id)
        if not resolved_at <= horizon_end:
            after_horizon.append(case_id)
        del resolved_at
    return len(cases.case_ids()), missing, not_after_cutoff, after_horizon


def test_repo_case_horizon_covers_the_sealed_resolution_time():
    """F11 (docs/FINANCE_REVIEW.md, #158): the question window ``as_of + horizon_days`` must reach the instant the
    sealed answer was published, or the prompt's "Horizon: N days after the cutoff" ends before the event and the
    contamination check (model card vs. horizon end) dates the event too early. Every committed case is checked,
    real and synthetic; only case ids reach the assertion."""
    n, missing, not_after_cutoff, after_horizon = _horizon_problems_via_vault()
    if n == 0:
        pytest.skip("no cases in services/api/data/demo_cases")
    assert missing == [], "sealed file has no resolved_at, so the horizon cannot be checked"
    assert not_after_cutoff == [], "resolved at or before the cutoff"
    assert after_horizon == [], "the question horizon ends before the sealed resolution time"
