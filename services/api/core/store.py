"""SQLite prediction store: forecasts are persisted, with their audit hashes, BEFORE any reveal (SPEC §5).

Database: ``services/api/var/predictions.sqlite3`` by default (``var/`` is git-ignored).

Guarantees enforced here (tests/test_replay_seal.py):

* ``save`` recomputes ``prompt_sha256`` from the exact prompt text and ``snapshot_sha256`` from the exact
  canonical snapshot JSON, and refuses the row if either differs (``HashMismatch``).
* The snapshot must be canonical JSON with exactly ``evidence`` and ``market_quotes``; ``agent_only`` must
  have no market quote and ``agent_plus_market`` at least one; cited ``evidence_ids`` must be in the snapshot.
* Rows are append-only: SQLite triggers abort any UPDATE or DELETE on ``predictions``; a duplicate
  ``prediction_id`` raises ``PredictionExists``.
* ``persisted_at`` comes from the store's clock, not the caller, so a reveal can be checked against it.

This module stores no outcomes and never reads the sealed-outcome directory. The evaluator records each
reveal through ``record_reveal``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from config import API_DIR
from core import provenance
from models import Prediction

DEFAULT_DB_PATH = API_DIR / "var" / "predictions.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id   TEXT PRIMARY KEY,
    event_id        TEXT NOT NULL,
    as_of           TEXT NOT NULL,
    agent_model     TEXT NOT NULL,
    model_digest    TEXT,
    variant         TEXT NOT NULL CHECK (variant IN ('agent_only', 'agent_plus_market', 'hosted_comparator')),
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
    persisted_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS predictions_event ON predictions (event_id, as_of, variant);
CREATE TRIGGER IF NOT EXISTS predictions_no_update BEFORE UPDATE ON predictions
BEGIN SELECT RAISE(ABORT, 'predictions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS predictions_no_delete BEFORE DELETE ON predictions
BEGIN SELECT RAISE(ABORT, 'predictions are append-only'); END;
CREATE TABLE IF NOT EXISTS reveals (
    reveal_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id TEXT NOT NULL REFERENCES predictions (prediction_id),
    revealed_at   TEXT NOT NULL
);
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
)


class PredictionExists(ValueError):
    pass


class HashMismatch(ValueError):
    pass


@dataclass(frozen=True)
class StoredPrediction:
    prediction: Prediction
    prompt: str
    snapshot_json: str
    persisted_at: datetime


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def check_audit(prediction: Prediction, prompt: str, snapshot_json: str) -> list[str]:
    """Problems with a (prediction, prompt, snapshot) triple; empty means it is consistent."""
    problems: list[str] = []
    if provenance.prompt_sha256(prompt) != prediction.prompt_sha256:
        problems.append("prompt_sha256 does not match the stored prompt text")
    if provenance.sha256_hex(snapshot_json) != prediction.snapshot_sha256:
        problems.append("snapshot_sha256 does not match the stored snapshot JSON")
    return problems


def _check_snapshot(prediction: Prediction, snapshot_json: str) -> None:
    try:
        payload = json.loads(snapshot_json)
        canonical = provenance.snapshot_payload_json(payload)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"snapshot_json is not a canonical snapshot payload: {exc}") from exc
    if canonical != snapshot_json:
        raise ValueError("snapshot_json must be canonical JSON (sorted keys, no whitespace)")
    n_quotes = len(payload["market_quotes"])
    if prediction.variant == "agent_only" and n_quotes:
        raise ValueError("agent_only prediction has market quotes in its snapshot")
    if prediction.variant == "agent_plus_market" and not n_quotes:
        raise ValueError("agent_plus_market prediction has no market quote in its snapshot")
    available = {e.get("evidence_id") for e in payload["evidence"] if isinstance(e, dict)}
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

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------ writes

    def save(self, prediction: Prediction, *, prompt: str, snapshot_json: str) -> StoredPrediction:
        """Persist a prediction with its exact prompt and snapshot. Refuses anything that does not verify."""
        if not isinstance(prediction, Prediction):
            raise TypeError("save expects a models.Prediction")
        problems = check_audit(prediction, prompt, snapshot_json)
        if problems:
            raise HashMismatch("; ".join(problems))
        _check_snapshot(prediction, snapshot_json)
        persisted_at = self._clock()
        row = {
            **prediction.model_dump(mode="json"),
            "evidence_ids": json.dumps(list(prediction.evidence_ids)),
            "as_of": _iso(prediction.as_of),
            "recorded_at": _iso(prediction.recorded_at),
            "prompt_text": prompt,
            "snapshot_json": snapshot_json,
            "persisted_at": _iso(persisted_at),
        }
        sql = f"INSERT INTO predictions ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' for _ in _COLUMNS)})"
        try:
            with self._connect() as conn:
                conn.execute(sql, [row[c] for c in _COLUMNS])
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc) or "PRIMARY KEY" in str(exc):
                raise PredictionExists(f"prediction {prediction.prediction_id!r} already persisted") from exc
            raise
        return StoredPrediction(prediction, prompt, snapshot_json, persisted_at)

    def record_reveal(self, prediction_id: str, revealed_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO reveals (prediction_id, revealed_at) VALUES (?, ?)", (prediction_id, _iso(revealed_at))
            )

    # ------------------------------------------------------------ reads

    @staticmethod
    def _to_record(row: sqlite3.Row) -> StoredPrediction:
        data = {k: row[k] for k in row.keys() if k not in ("prompt_text", "snapshot_json", "persisted_at")}
        data["evidence_ids"] = json.loads(data["evidence_ids"])
        return StoredPrediction(
            prediction=Prediction.model_validate(data),
            prompt=row["prompt_text"],
            snapshot_json=row["snapshot_json"],
            persisted_at=datetime.fromisoformat(row["persisted_at"]),
        )

    def get_record(self, prediction_id: str) -> StoredPrediction | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM predictions WHERE prediction_id = ?", (prediction_id,)).fetchone()
        return None if row is None else self._to_record(row)

    def get(self, prediction_id: str) -> Prediction | None:
        rec = self.get_record(prediction_id)
        return None if rec is None else rec.prediction

    def list_predictions(self, event_id: str | None = None) -> list[Prediction]:
        with self._connect() as conn:
            if event_id is None:
                rows = conn.execute("SELECT * FROM predictions ORDER BY persisted_at, prediction_id").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM predictions WHERE event_id = ? ORDER BY persisted_at, prediction_id", (event_id,)
                ).fetchall()
        return [self._to_record(r).prediction for r in rows]

    def verify(self, prediction_id: str) -> list[str]:
        """Recompute both hashes from the stored text. Empty list means the audit record is intact."""
        rec = self.get_record(prediction_id)
        if rec is None:
            return [f"prediction {prediction_id!r} is not persisted"]
        return check_audit(rec.prediction, rec.prompt, rec.snapshot_json)

    def reveal_times(self, prediction_id: str) -> list[datetime]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT revealed_at FROM reveals WHERE prediction_id = ? ORDER BY reveal_id", (prediction_id,)
            ).fetchall()
        return [datetime.fromisoformat(r["revealed_at"]) for r in rows]
