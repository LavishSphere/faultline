"""SQLite prediction store: forecasts are persisted, with their audit hashes, BEFORE any reveal (SPEC §5).

Database: ``services/api/var/predictions.sqlite3`` by default (``var/`` is git-ignored).

Guarantees enforced here (tests/test_replay_seal.py):

* ``save(prediction, model_input)`` takes the gate's ``ModelInput`` (only ``GatedSnapshot.model_input`` can
  create one) and requires the prediction's ``event_id``, ``as_of``, ``variant``, ``prompt_sha256`` and
  ``snapshot_sha256`` to match it. Both hashes are recomputed from the model input's exact text.
* What the model saw is what gets hashed (#44): ``save(..., final_prompt=result.final_prompt)`` stores the exact
  message the model answered next to the gate's prompt. ``prompt_sha256`` / ``transcript_sha256`` must hash that
  message and ``gated_prompt_sha256`` the gate's prompt; a repair prompt must start with the gated prompt,
  unchanged. ``verify`` recomputes all of them.
* Only the replay variants ``agent_only`` / ``agent_plus_market`` are accepted; the snapshot must agree with
  the variant; cited ``evidence_ids`` must be in the snapshot.
* The pre-reveal scoring context from the ``ModelInput`` (market baseline, contamination flag, synthetic) is
  stored with the forecast, so scoring never takes these from a caller after outcomes are known.
* ``record_sha256`` = SHA-256 of the canonical JSON of ``{"prediction", "context", "persisted_at",
  "persist_seq"}``, so an edit to the forecast or its context is detectable by ``verify``.
* ``audit_log`` is one append-only, totally ordered sequence of ``persist`` and ``reveal`` entries
  (``seq``), so "saved before this event's outcome was first revealed" is a comparison of integers,
  not of clock readings. A reveal row also records the sealed file's provenance (``sealed_provenance``, #102).
* Triggers abort UPDATE and DELETE on both tables, an INSERT that reuses a prediction id (this also blocks
  ``INSERT OR REPLACE``), any ``audit_log`` row with a caller-chosen or non-increasing ``seq`` (no backdating),
  a reveal entry for a prediction that does not exist, and a prediction whose ``persist_seq`` is not its own
  ``audit_log`` persist entry.

These protections make tampering **evident**, not impossible: someone with write access to the file can
drop the triggers and rewrite a row together with its hashes. This module stores no outcomes and never
reads the sealed-outcome directory.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from agents.local_ollama import MAX_ATTEMPTS, is_repair_instruction
from config import API_DIR
from core import provenance
from core.temporal_gate import PROMPT_VARIANTS, ModelInput
from models import Prediction

DEFAULT_DB_PATH = API_DIR / "var" / "predictions.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id   TEXT PRIMARY KEY,
    event_id        TEXT NOT NULL,
    as_of           TEXT NOT NULL,
    agent_model     TEXT NOT NULL,
    model_digest    TEXT,
    variant         TEXT NOT NULL CHECK (variant IN ('agent_only', 'agent_plus_market')),
    p_yes           REAL NOT NULL CHECK (p_yes >= 0.0 AND p_yes <= 1.0),
    decision        TEXT NOT NULL CHECK (decision IN ('act', 'wait', 'hedge')),
    rationale       TEXT NOT NULL,
    evidence_ids    TEXT NOT NULL,
    prompt_sha256   TEXT NOT NULL CHECK (length(prompt_sha256) = 64),
    snapshot_sha256 TEXT NOT NULL CHECK (length(snapshot_sha256) = 64),
    temperature     REAL NOT NULL,
    seed            INTEGER,
    recorded_at     TEXT NOT NULL,
    provenance      TEXT NOT NULL,
    prompt_text     TEXT NOT NULL,
    snapshot_json   TEXT NOT NULL,
    persisted_at    TEXT NOT NULL,
    persist_seq     INTEGER NOT NULL UNIQUE,
    market_baseline_p_yes REAL CHECK (market_baseline_p_yes IS NULL OR
                                      (market_baseline_p_yes >= 0.0 AND market_baseline_p_yes <= 1.0)),
    market_baseline_ref   TEXT,
    contamination_flag    TEXT NOT NULL CHECK (contamination_flag IN ('unknown', 'likely', 'unlikely')),
    synthetic             INTEGER NOT NULL CHECK (synthetic IN (0, 1)),
    case_sha256           TEXT NOT NULL CHECK (length(case_sha256) = 64),
    record_sha256   TEXT NOT NULL CHECK (length(record_sha256) = 64)
);
CREATE INDEX IF NOT EXISTS predictions_key ON predictions (event_id, as_of, variant);
CREATE TABLE IF NOT EXISTS audit_log (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL CHECK (kind IN ('persist', 'reveal')),
    prediction_id TEXT NOT NULL,
    event_id      TEXT NOT NULL,
    at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_log_event ON audit_log (event_id, kind, seq);
CREATE TRIGGER IF NOT EXISTS predictions_no_reuse BEFORE INSERT ON predictions
WHEN EXISTS (SELECT 1 FROM predictions WHERE prediction_id = NEW.prediction_id)
BEGIN SELECT RAISE(ABORT, 'prediction already persisted (append-only)'); END;
CREATE TRIGGER IF NOT EXISTS predictions_no_update BEFORE UPDATE ON predictions
BEGIN SELECT RAISE(ABORT, 'predictions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS predictions_no_delete BEFORE DELETE ON predictions
BEGIN SELECT RAISE(ABORT, 'predictions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS predictions_persist_seq_is_logged BEFORE INSERT ON predictions
WHEN NEW.persist_seq IS NOT (SELECT max(seq) FROM audit_log)
  OR NOT EXISTS (SELECT 1 FROM audit_log WHERE seq = NEW.persist_seq AND kind = 'persist'
                 AND prediction_id = NEW.prediction_id AND event_id = NEW.event_id)
BEGIN SELECT RAISE(ABORT, 'persist_seq must be the newest audit log entry, its own persist (append-only)'); END;
-- In a BEFORE INSERT trigger an auto-assigned INTEGER PRIMARY KEY reads as -1; anything else was chosen by
-- the caller, which would allow backdating. The AFTER trigger also refuses an explicit -1 (non-increasing).
CREATE TRIGGER IF NOT EXISTS audit_log_no_explicit_seq BEFORE INSERT ON audit_log
WHEN NEW.seq <> -1
BEGIN SELECT RAISE(ABORT, 'audit log is append-only: seq is assigned by SQLite'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_increasing AFTER INSERT ON audit_log
WHEN NEW.seq <= COALESCE((SELECT max(seq) FROM audit_log WHERE seq <> NEW.seq), 0)
BEGIN SELECT RAISE(ABORT, 'audit log is append-only: seq must increase'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_reveal_needs_prediction BEFORE INSERT ON audit_log
WHEN NEW.kind = 'reveal' AND NOT EXISTS (SELECT 1 FROM predictions
                                         WHERE prediction_id = NEW.prediction_id AND event_id = NEW.event_id)
BEGIN SELECT RAISE(ABORT, 'audit log is append-only: a reveal must name a persisted prediction'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""

_COLUMNS = (
    "prediction_id",
    "event_id",
    "as_of",
    "agent_model",
    "model_digest",
    "variant",
    "p_yes",
    "decision",
    "rationale",
    "evidence_ids",
    "prompt_sha256",
    "snapshot_sha256",
    "temperature",
    "seed",
    "recorded_at",
    "provenance",
    "prompt_text",
    "snapshot_json",
    "persisted_at",
    "persist_seq",
    "market_baseline_p_yes",
    "market_baseline_ref",
    "contamination_flag",
    "synthetic",
    "case_sha256",
    "record_sha256",
    "gated_prompt_sha256",
    "attempts",
    "transcript_sha256",
    "num_ctx",
    "num_predict",
    "final_prompt_text",
)
_CONTEXT_COLUMNS = ("market_baseline_p_yes", "market_baseline_ref", "contamination_flag", "synthetic", "case_sha256")
_STORE_ONLY = (
    "prompt_text",
    "final_prompt_text",
    "snapshot_json",
    "persisted_at",
    "persist_seq",
    "record_sha256",
    *_CONTEXT_COLUMNS,
)

# Model-run audit columns (#44), added to a table created by an earlier version with ALTER TABLE ADD COLUMN.
# NULL on records saved without a model provider; then the model saw the gated prompt (prompt_text) itself.
# ``prompt_text`` = the gate's prompt (hashed as gated_prompt_sha256); ``final_prompt_text`` = the exact message
# the model answered (hashed as prompt_sha256 and, as one user message, transcript_sha256).
_RUN_AUDIT_COLUMNS = {
    "gated_prompt_sha256": "TEXT CHECK (gated_prompt_sha256 IS NULL OR length(gated_prompt_sha256) = 64)",
    "attempts": "INTEGER CHECK (attempts IS NULL OR attempts IN (1, 2))",
    "transcript_sha256": "TEXT CHECK (transcript_sha256 IS NULL OR length(transcript_sha256) = 64)",
    "num_ctx": "INTEGER CHECK (num_ctx IS NULL OR num_ctx > 0)",
    "num_predict": "INTEGER CHECK (num_predict IS NULL OR num_predict > 0)",
    "final_prompt_text": "TEXT",
}
# audit_log columns added later (ALTER TABLE ADD COLUMN, idempotent). ``sealed_provenance`` (#102) is the
# provenance of the sealed file a reveal read, written by ``record_reveal``; NULL on persist rows and on reveals
# logged before #102, which therefore count as real for the cross-event ``late`` check.
_AUDIT_LOG_COLUMNS = {
    "sealed_provenance": (
        "TEXT CHECK (sealed_provenance IS NULL OR sealed_provenance IN ('REAL_HISTORICAL', 'SYNTHETIC'))"
    ),
}
SealedProvenance = Literal["REAL_HISTORICAL", "SYNTHETIC"]
# Prediction fields left out of record_sha256 when None, so records saved before #44 keep their hashes.
_OPTIONAL_RUN_FIELDS = ("gated_prompt_sha256", "attempts", "transcript_sha256", "num_ctx", "num_predict")
# The provider makes one answer plus at most one schema repair (agents.local_ollama.MAX_ATTEMPTS == 2).
ALLOWED_ATTEMPTS = tuple(range(1, MAX_ATTEMPTS + 1))


class PredictionExists(ValueError):
    pass


class HashMismatch(ValueError):
    pass


@dataclass(frozen=True)
class ScoringContext:
    """Pre-reveal scoring context for one forecast, fixed by the gate (``ModelInput``) when it was saved."""

    market_baseline_p_yes: float | None  # None: market baseline NOT AVAILABLE at this as_of
    market_baseline_ref: str | None  # "venue:market_id" of the baseline quote
    contamination_flag: str
    synthetic: bool
    case_sha256: str  # content hash of the case record the forecast was made from

    def as_json(self) -> dict:
        return {
            "market_baseline_p_yes": self.market_baseline_p_yes,
            "market_baseline_ref": self.market_baseline_ref,
            "contamination_flag": self.contamination_flag,
            "synthetic": self.synthetic,
            "case_sha256": self.case_sha256,
        }


@dataclass(frozen=True)
class StoredPrediction:
    prediction: Prediction
    prompt: str
    snapshot_json: str
    persisted_at: datetime
    persist_seq: int
    context: ScoringContext
    record_sha256: str
    final_prompt: str | None = None
    """The exact message the model answered; None on records saved before #44 (then it is ``prompt``)."""

    @property
    def model_prompt(self) -> str:
        return self.prompt if self.final_prompt is None else self.final_prompt


@dataclass(frozen=True)
class RevealMark:
    seq: int
    at: datetime


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _prediction_json(prediction: Prediction) -> dict:
    data = prediction.model_dump(mode="json")
    data["as_of"] = _iso(prediction.as_of)
    data["recorded_at"] = _iso(prediction.recorded_at)
    for name in _OPTIONAL_RUN_FIELDS:
        if data[name] is None:
            del data[name]
    return data


def record_sha256(prediction: Prediction, context: ScoringContext, persisted_at: datetime, persist_seq: int) -> str:
    """SHA-256 of the canonical JSON of the whole forecast (including both input hashes), its pre-reveal
    scoring context and its persist mark."""
    payload = {
        "prediction": _prediction_json(prediction),
        "context": context.as_json(),
        "persisted_at": _iso(persisted_at),
        "persist_seq": persist_seq,
    }
    return provenance.sha256_hex(provenance.canonical_json(payload))


def model_prompt_problems(prediction: Prediction, gated_prompt: str, final_prompt: str) -> list[str]:
    """Check what the model saw against the gate's prompt and the prediction's hashes (#44).

    With run audit fields: ``gated_prompt_sha256`` hashes the gate's prompt; ``prompt_sha256`` and
    ``transcript_sha256`` hash ``final_prompt``; ``attempts`` is 1 or 2. ``attempts == 1`` means ``final_prompt`` IS
    the gated prompt; ``attempts == 2`` means it is the gated prompt, unchanged, followed by EXACTLY the provider's
    repair instruction (``agents.local_ollama.is_repair_instruction``: fixed header and footer, only ``- ...``
    problem lines between them), so no other text can be smuggled into what the model saw. Without run audit
    fields (records made without a model provider) the model must have seen exactly the gated prompt.
    """
    p = prediction
    problems: list[str] = []
    if provenance.prompt_sha256(final_prompt) != p.prompt_sha256:
        problems.append("prompt_sha256 does not match the stored prompt text")
    run_fields = {name: getattr(p, name) for name in _OPTIONAL_RUN_FIELDS}
    if p.gated_prompt_sha256 is None:
        if any(v is not None for v in run_fields.values()):
            problems.append("model-run audit fields are set without gated_prompt_sha256")
        if provenance.prompt_sha256(gated_prompt) != p.prompt_sha256 or final_prompt != gated_prompt:
            problems.append("prompt_sha256 does not match the stored gated prompt text (no model-run audit fields)")
        return problems
    missing = sorted(name for name in ("attempts", "transcript_sha256") if run_fields[name] is None)
    if missing:
        problems.append(f"model-run audit fields missing: {missing}")
    if provenance.prompt_sha256(gated_prompt) != p.gated_prompt_sha256:
        problems.append("gated_prompt_sha256 does not match the stored gated prompt text")
    if p.attempts is not None and p.attempts not in ALLOWED_ATTEMPTS:
        problems.append(f"attempts must be one of {ALLOWED_ATTEMPTS} (one answer plus at most one repair)")
    if p.attempts == 1 and final_prompt != gated_prompt:
        problems.append("attempts == 1 but the model prompt differs from the gated prompt")
    if p.attempts == 2 and not (
        final_prompt.startswith(gated_prompt) and is_repair_instruction(final_prompt[len(gated_prompt) :])
    ):
        problems.append(
            "a repair attempt's prompt must be the gated prompt, unchanged, plus exactly the provider's repair "
            "instruction"
        )
    if p.transcript_sha256 is not None and provenance.transcript_sha256(final_prompt) != p.transcript_sha256:
        problems.append("transcript_sha256 does not match the stored model prompt")
    return problems


def check_record(rec: StoredPrediction) -> list[str]:
    """Problems with a stored record; empty means prompts, snapshot and forecast all match their hashes."""
    problems = model_prompt_problems(rec.prediction, rec.prompt, rec.model_prompt)
    if provenance.sha256_hex(rec.snapshot_json) != rec.prediction.snapshot_sha256:
        problems.append("snapshot_sha256 does not match the stored snapshot JSON")
    if record_sha256(rec.prediction, rec.context, rec.persisted_at, rec.persist_seq) != rec.record_sha256:
        problems.append("record_sha256 does not match the stored forecast")
    return problems


def _check_against_model_input(prediction: Prediction, mi: ModelInput) -> None:
    if prediction.variant not in PROMPT_VARIANTS:
        raise ValueError(f"variant {prediction.variant!r} cannot be persisted (replay variants: {PROMPT_VARIANTS})")
    if prediction.variant != mi.variant:
        raise ValueError(f"prediction variant {prediction.variant} does not match model input variant {mi.variant}")
    if prediction.event_id != mi.event_id:
        raise ValueError(f"prediction event_id {prediction.event_id!r} does not match model input {mi.event_id!r}")
    if prediction.as_of != datetime.fromisoformat(mi.as_of):
        raise ValueError(f"prediction as_of {_iso(prediction.as_of)} does not match model input as_of {mi.as_of}")
    problems = []
    if provenance.prompt_sha256(mi.prompt) != mi.prompt_sha256:
        problems.append("model input prompt no longer matches its prompt_sha256")
    if provenance.sha256_hex(mi.snapshot_json) != mi.snapshot_sha256:
        problems.append("model input snapshot no longer matches its snapshot_sha256")
    if (prediction.gated_prompt_sha256 or prediction.prompt_sha256) != mi.prompt_sha256:
        field = "gated_prompt_sha256" if prediction.gated_prompt_sha256 else "prompt_sha256"
        problems.append(f"prediction {field} differs from the model input")
    if prediction.snapshot_sha256 != mi.snapshot_sha256:
        problems.append("prediction snapshot_sha256 differs from the model input")
    if problems:
        raise HashMismatch("; ".join(problems))

    payload = json.loads(mi.snapshot_json)
    if provenance.snapshot_payload_json(payload) != mi.snapshot_json:
        raise ValueError("snapshot_json must be canonical JSON (sorted keys, no whitespace)")
    n_quotes = len(payload["market_quotes"])
    if prediction.variant == "agent_only" and n_quotes:
        raise ValueError("agent_only prediction has market quotes in its snapshot")
    if prediction.variant == "agent_plus_market" and not n_quotes:
        raise ValueError("agent_plus_market prediction has no market quote in its snapshot")
    available = {e.get("evidence_id") for e in payload["evidence"]}
    missing = [e for e in prediction.evidence_ids if e not in available]
    if missing:
        raise ValueError(f"prediction cites evidence not in its snapshot: {missing}")


class PredictionStore:
    def __init__(self, path: Path | str = DEFAULT_DB_PATH, *, clock: Callable[[], datetime] = _utcnow) -> None:
        self.path = Path(path)
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            present = {r["name"] for r in conn.execute("PRAGMA table_info(predictions)")}
            for name, ddl in _RUN_AUDIT_COLUMNS.items():
                if name not in present:
                    conn.execute(f"ALTER TABLE predictions ADD COLUMN {name} {ddl}")
            present = {r["name"] for r in conn.execute("PRAGMA table_info(audit_log)")}
            for name, ddl in _AUDIT_LOG_COLUMNS.items():
                if name not in present:
                    conn.execute(f"ALTER TABLE audit_log ADD COLUMN {name} {ddl}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA recursive_triggers = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------ writes

    def save(
        self, prediction: Prediction, model_input: ModelInput, *, final_prompt: str | None = None
    ) -> StoredPrediction:
        """Persist a forecast for exactly the gate output it was made from. Refuses anything that does not match.

        ``final_prompt`` is the exact message the model answered (``ForecastResult.final_prompt``); omitted, it
        is the gated prompt. Its hashes are checked by ``model_prompt_problems`` and it is stored for ``verify``.
        """
        if not isinstance(prediction, Prediction):
            raise TypeError("save expects a models.Prediction")
        if not isinstance(model_input, ModelInput):
            raise TypeError("save expects the ModelInput from GatedSnapshot.model_input")
        if final_prompt is not None and not isinstance(final_prompt, str):
            raise TypeError("final_prompt must be the prompt text")
        _check_against_model_input(prediction, model_input)
        model_prompt = model_input.prompt if final_prompt is None else final_prompt
        problems = model_prompt_problems(prediction, model_input.prompt, model_prompt)
        if problems:
            raise HashMismatch("; ".join(problems))
        context = ScoringContext(
            market_baseline_p_yes=model_input.market_baseline_p_yes,
            market_baseline_ref=model_input.market_baseline_ref,
            contamination_flag=model_input.contamination_flag,
            synthetic=bool(model_input.synthetic),
            case_sha256=model_input.case_sha256,
        )
        persisted_at = self._clock()
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO audit_log (kind, prediction_id, event_id, at) VALUES ('persist', ?, ?, ?)",
                    (prediction.prediction_id, prediction.event_id, _iso(persisted_at)),
                )
                seq = int(cur.lastrowid)
                row = {
                    **_prediction_json(prediction),
                    **{name: getattr(prediction, name) for name in _OPTIONAL_RUN_FIELDS},
                    "evidence_ids": json.dumps(list(prediction.evidence_ids)),
                    "prompt_text": model_input.prompt,
                    "final_prompt_text": model_prompt,
                    "snapshot_json": model_input.snapshot_json,
                    "persisted_at": _iso(persisted_at),
                    "persist_seq": seq,
                    **context.as_json(),
                    "synthetic": int(context.synthetic),
                    "record_sha256": record_sha256(prediction, context, persisted_at, seq),
                }
                sql = f"INSERT INTO predictions ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' for _ in _COLUMNS)})"
                conn.execute(sql, [row[c] for c in _COLUMNS])
        except sqlite3.IntegrityError as exc:
            if "already persisted" in str(exc) or "UNIQUE" in str(exc):
                raise PredictionExists(f"prediction {prediction.prediction_id!r} already persisted") from exc
            raise
        return StoredPrediction(
            prediction,
            model_input.prompt,
            model_input.snapshot_json,
            persisted_at,
            seq,
            context,
            row["record_sha256"],
            final_prompt=model_prompt,
        )

    def record_reveal(
        self, prediction: Prediction, revealed_at: datetime, *, sealed_provenance: SealedProvenance
    ) -> RevealMark:
        """Log one reveal, with the provenance of the sealed file it read (REAL_HISTORICAL or SYNTHETIC)."""
        if sealed_provenance not in ("REAL_HISTORICAL", "SYNTHETIC"):
            raise ValueError("sealed_provenance must be REAL_HISTORICAL or SYNTHETIC")
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO audit_log (kind, prediction_id, event_id, at, sealed_provenance) "
                "VALUES ('reveal', ?, ?, ?, ?)",
                (prediction.prediction_id, prediction.event_id, _iso(revealed_at), sealed_provenance),
            )
        return RevealMark(seq=int(cur.lastrowid), at=revealed_at)

    # ------------------------------------------------------------ reads

    @staticmethod
    def _to_record(row: sqlite3.Row) -> StoredPrediction:
        data = {k: row[k] for k in row.keys() if k not in _STORE_ONLY}
        data["evidence_ids"] = json.loads(data["evidence_ids"])
        return StoredPrediction(
            prediction=Prediction.model_validate(data),
            prompt=row["prompt_text"],
            snapshot_json=row["snapshot_json"],
            persisted_at=datetime.fromisoformat(row["persisted_at"]),
            persist_seq=int(row["persist_seq"]),
            context=ScoringContext(
                market_baseline_p_yes=row["market_baseline_p_yes"],
                market_baseline_ref=row["market_baseline_ref"],
                contamination_flag=row["contamination_flag"],
                synthetic=bool(row["synthetic"]),
                case_sha256=row["case_sha256"],
            ),
            record_sha256=row["record_sha256"],
            final_prompt=row["final_prompt_text"],
        )

    def get_record(self, prediction_id: str) -> StoredPrediction | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM predictions WHERE prediction_id = ?", (prediction_id,)).fetchone()
        return None if row is None else self._to_record(row)

    def get(self, prediction_id: str) -> Prediction | None:
        rec = self.get_record(prediction_id)
        return None if rec is None else rec.prediction

    def records_for(self, event_id: str, as_of: datetime, variant: str) -> list[StoredPrediction]:
        """Every persisted prediction for one (event_id, as_of, variant), in persist order."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM predictions WHERE event_id = ? AND as_of = ? AND variant = ? ORDER BY persist_seq",
                (event_id, _iso(as_of), variant),
            ).fetchall()
        return [self._to_record(r) for r in rows]

    def all_records(self) -> list[StoredPrediction]:
        """Every persisted prediction, in persist order (the scorecard's population)."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM predictions ORDER BY persist_seq").fetchall()
        return [self._to_record(r) for r in rows]

    def list_predictions(self, event_id: str | None = None) -> list[Prediction]:
        with self._connect() as conn:
            if event_id is None:
                rows = conn.execute("SELECT * FROM predictions ORDER BY persist_seq").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM predictions WHERE event_id = ? ORDER BY persist_seq", (event_id,)
                ).fetchall()
        return [self._to_record(r).prediction for r in rows]

    def first_reveal_any(self) -> RevealMark | None:
        """The earliest reveal of any prediction in this store (any event), or None."""
        with self._connect() as conn:
            row = conn.execute("SELECT seq, at FROM audit_log WHERE kind = 'reveal' ORDER BY seq LIMIT 1").fetchone()
        return None if row is None else RevealMark(seq=int(row["seq"]), at=datetime.fromisoformat(row["at"]))

    def first_counted_reveal(self, exempt_events: Iterable[str]) -> RevealMark | None:
        """The earliest reveal that counts for the cross-event ``late`` check (#102).

        A reveal is skipped only if its event is in ``exempt_events`` AND it was logged with sealed provenance
        SYNTHETIC. Reveals logged with REAL_HISTORICAL, or before #102 (NULL), always count.
        """
        exempt = sorted(set(exempt_events))
        if not exempt:
            return self.first_reveal_any()
        marks = ", ".join("?" for _ in exempt)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT seq, at FROM audit_log WHERE kind = 'reveal' AND NOT "
                f"(COALESCE(sealed_provenance, '') = 'SYNTHETIC' AND event_id IN ({marks})) ORDER BY seq LIMIT 1",
                exempt,
            ).fetchone()
        return None if row is None else RevealMark(seq=int(row["seq"]), at=datetime.fromisoformat(row["at"]))

    def first_reveal(self, event_id: str) -> RevealMark | None:
        """The earliest reveal of ANY prediction for this event (any as_of, any variant), or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT seq, at FROM audit_log WHERE event_id = ? AND kind = 'reveal' ORDER BY seq LIMIT 1", (event_id,)
            ).fetchone()
        return None if row is None else RevealMark(seq=int(row["seq"]), at=datetime.fromisoformat(row["at"]))

    def verify(self, prediction_id: str) -> list[str]:
        """Recompute the prompt, snapshot and record hashes. Empty list means the audit record is intact."""
        rec = self.get_record(prediction_id)
        if rec is None:
            return [f"prediction {prediction_id!r} is not persisted"]
        problems = check_record(rec)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT seq FROM audit_log WHERE kind = 'persist' AND prediction_id = ? ORDER BY seq", (prediction_id,)
            ).fetchall()
        if [int(r["seq"]) for r in row] != [rec.persist_seq]:
            problems.append("audit log persist entry does not match the stored persist_seq")
        return problems

    def reveal_times(self, prediction_id: str) -> list[datetime]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT at FROM audit_log WHERE kind = 'reveal' AND prediction_id = ? ORDER BY seq", (prediction_id,)
            ).fetchall()
        return [datetime.fromisoformat(r["at"]) for r in rows]
