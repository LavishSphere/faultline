"""Sealed outcomes, future-fact canary, provenance hashing and persist-before-reveal (SPEC §5, §10).

Written before core/provenance.py, core/store.py and core/evaluator.py. All fixtures are SYNTHETIC.
"""

from __future__ import annotations

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
from core.evaluator import NotRevealable, OutcomeNotAvailable, OutcomeVault, RevealedOutcome
from core.store import DEFAULT_DB_PATH, HashMismatch, PredictionExists, PredictionStore
from core.temporal_gate import EvidenceStore, MarketNotAvailable
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
    store.save(pred, prompt=mi.prompt, snapshot_json=mi.snapshot_json)
    revealed = vault.reveal("pred_001")
    assert isinstance(revealed, RevealedOutcome)
    assert revealed.y == 1 and revealed.prediction == pred
    rec = store.get_record("pred_001")
    reveals = store.reveal_times("pred_001")
    assert len(reveals) == 1 and rec.persisted_at < reveals[0] == revealed.revealed_at


def test_revealed_outcome_cannot_be_forged():
    with pytest.raises(TypeError):
        RevealedOutcome(prediction=None, y=1, sealed=None, revealed_at=AS_OF)  # type: ignore[call-arg]


def test_save_rejects_hashes_that_do_not_match(world):
    store, vault, snap, _ = world
    mi = snap.model_input("agent_only")
    with pytest.raises(HashMismatch):
        store.save(prediction_for(mi, snap), prompt=mi.prompt + " ", snapshot_json=mi.snapshot_json)
    with pytest.raises(HashMismatch):
        store.save(prediction_for(mi, snap), prompt=mi.prompt, snapshot_json=mi.snapshot_json.replace("evid_ok", "x"))
    assert store.get("pred_001") is None
    with pytest.raises(NotRevealable):
        vault.reveal("pred_001")


def test_save_rejects_non_canonical_snapshot(world):
    store, _, snap, _ = world
    mi = snap.model_input("agent_only")
    pretty = json.dumps(json.loads(mi.snapshot_json), indent=2)
    pred = prediction_for(mi, snap, snapshot_sha256=provenance.sha256_hex(pretty))
    with pytest.raises(ValueError, match="canonical"):
        store.save(pred, prompt=mi.prompt, snapshot_json=pretty)


def test_save_rejects_variant_snapshot_mismatch(world):
    store, _, snap, _ = world
    plus = snap.model_input("agent_plus_market")
    # Claiming agent_only for a snapshot that contains a market quote is refused.
    with pytest.raises(ValueError, match="agent_only"):
        store.save(
            prediction_for(plus, snap, variant="agent_only"), prompt=plus.prompt, snapshot_json=plus.snapshot_json
        )
    only = snap.model_input("agent_only")
    with pytest.raises(ValueError, match="agent_plus_market"):
        store.save(
            prediction_for(only, snap, variant="agent_plus_market"),
            prompt=only.prompt,
            snapshot_json=only.snapshot_json,
        )


def test_save_rejects_citations_outside_the_snapshot(world):
    store, _, snap, _ = world
    mi = snap.model_input("agent_only")
    with pytest.raises(ValueError, match="evid_future"):
        store.save(
            prediction_for(mi, snap, evidence_ids=["evid_ok", "evid_future"]),
            prompt=mi.prompt,
            snapshot_json=mi.snapshot_json,
        )


def test_predictions_are_append_only(world):
    store, _, snap, _ = world
    mi = snap.model_input("agent_only")
    store.save(prediction_for(mi, snap), prompt=mi.prompt, snapshot_json=mi.snapshot_json)
    with pytest.raises(PredictionExists):
        store.save(prediction_for(mi, snap, p_yes=0.9), prompt=mi.prompt, snapshot_json=mi.snapshot_json)
    with sqlite3.connect(store.path) as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE predictions SET p_yes = 0.99 WHERE prediction_id = 'pred_001'")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM predictions WHERE prediction_id = 'pred_001'")
    assert store.get("pred_001").p_yes == 0.6


def test_store_round_trips_audit_fields_and_hashes_recompute(world, tmp_path):
    store, _, snap, _ = world
    mi = snap.model_input("agent_plus_market")
    pred = prediction_for(mi, snap, pid="pred_plus", model_digest="sha256:" + "d" * 64, seed=42)
    store.save(pred, prompt=mi.prompt, snapshot_json=mi.snapshot_json)

    reopened = PredictionStore(store.path)  # a fresh connection sees the same row
    rec = reopened.get_record("pred_plus")
    assert rec.prediction == pred
    assert rec.prediction.agent_model == "ollama/test-model"
    assert (rec.prediction.temperature, rec.prediction.seed, rec.prediction.variant) == (0.0, 42, "agent_plus_market")
    # RECORDED RUN audit: recompute both hashes from what was stored.
    assert provenance.prompt_sha256(rec.prompt) == rec.prediction.prompt_sha256
    assert provenance.sha256_hex(rec.snapshot_json) == rec.prediction.snapshot_sha256
    assert reopened.verify("pred_plus") == []
    assert [p.prediction_id for p in reopened.list_predictions(event_id=EVENT)] == ["pred_plus"]


def test_reveal_refuses_when_stored_audit_was_tampered(world):
    store, vault, snap, _ = world
    mi = snap.model_input("agent_only")
    store.save(prediction_for(mi, snap), prompt=mi.prompt, snapshot_json=mi.snapshot_json)
    with sqlite3.connect(store.path) as conn:
        conn.execute("DROP TRIGGER predictions_no_update")
        conn.execute("UPDATE predictions SET prompt_text = 'edited' WHERE prediction_id = 'pred_001'")
    assert store.verify("pred_001") != []
    with pytest.raises(NotRevealable, match="hash"):
        vault.reveal("pred_001")


def test_reveal_without_sealed_file_is_not_available(world):
    store, vault, snap, sealed = world
    (sealed / f"{EVENT}.json").unlink()
    mi = snap.model_input("agent_only")
    store.save(prediction_for(mi, snap), prompt=mi.prompt, snapshot_json=mi.snapshot_json)
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
    store.save(prediction_for(mi, snap), prompt=mi.prompt, snapshot_json=mi.snapshot_json)
    with pytest.raises(ValueError):
        vault.reveal("pred_001")


def test_sealed_outcome_no_maps_to_zero(world):
    store, vault, snap, sealed = world
    write_sealed(sealed, sealed_dict(outcome="NO"))
    mi = snap.model_input("agent_only")
    store.save(prediction_for(mi, snap), prompt=mi.prompt, snapshot_json=mi.snapshot_json)
    assert vault.reveal("pred_001").y == 0


# ---------------------------------------------------------------- pre-reveal payloads


def test_pre_reveal_payloads_walk_clean(world):
    store, _, snap, _ = world
    mi = snap.model_input("agent_plus_market")
    pred = prediction_for(mi, snap)
    store.save(pred, prompt=mi.prompt, snapshot_json=mi.snapshot_json)
    outcome_like = re.compile(r"outcome|resolution|resolved|settle|result|winner|final_price", re.IGNORECASE)
    for payload in (pred.model_dump(mode="json"), store.get("pred_001").model_dump(mode="json")):
        assert [p for p, k, _ in walk_keys(payload) if outcome_like.search(k)] == []
