"""Audit hashes for replay inputs (SPEC §5, replay-integrity skill).

* ``snapshot_sha256`` = SHA-256 of the canonical JSON of the exact evidence + market-quote list given to
  the model: ``{"evidence": [...], "market_quotes": [...]}``.
* ``prompt_sha256`` = SHA-256 of the final prompt string the model saw (UTF-8).
* ``transcript_sha256`` = SHA-256 of the canonical JSON of that call's chat messages (one user message).

Canonical JSON: keys sorted, no whitespace (``","`` and ``":"`` separators), UTF-8 (non-ASCII kept as is,
not ``\\u`` escaped), NaN/Infinity refused. Only plain JSON types are accepted: datetimes, bytes and
non-string keys raise, so every caller converts them explicitly (timestamps as ISO-8601 UTC ``...Z``).

This module is pure: it reads no files and knows nothing about outcomes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SNAPSHOT_KEYS = frozenset({"evidence", "market_quotes"})


def _check_plain_json(obj: Any, path: str = "$") -> None:
    if obj is None or isinstance(obj, (bool, int, str)):
        return
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            raise ValueError(f"{path}: NaN/Infinity is not canonical JSON")
        return
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _check_plain_json(v, f"{path}[{i}]")
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise TypeError(f"{path}: non-string key {k!r}")
            _check_plain_json(v, f"{path}.{k}")
        return
    raise TypeError(f"{path}: {type(obj).__name__} is not a plain JSON value; convert it explicitly")


def canonical_json(obj: Any) -> str:
    """Sorted keys, compact separators, UTF-8 text, no NaN. Raises on non-JSON types."""
    _check_plain_json(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_hex(text: str) -> str:
    """Lower-case hex SHA-256 of ``text`` encoded as UTF-8."""
    if not isinstance(text, str):
        raise TypeError("sha256_hex hashes text; encode bytes deliberately elsewhere")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt_sha256(prompt: str) -> str:
    return sha256_hex(prompt)


def snapshot_payload_json(payload: dict[str, Any]) -> str:
    """Canonical JSON of a snapshot payload. It must have exactly the keys ``evidence`` and ``market_quotes``."""
    if not isinstance(payload, dict) or set(payload) != SNAPSHOT_KEYS:
        raise ValueError(f"snapshot payload must have exactly the keys {sorted(SNAPSHOT_KEYS)}")
    if not all(isinstance(payload[k], (list, tuple)) for k in SNAPSHOT_KEYS):
        raise ValueError("snapshot payload values must be lists")
    return canonical_json(payload)


def snapshot_sha256(payload: dict[str, Any]) -> str:
    return sha256_hex(snapshot_payload_json(payload))


def transcript_sha256(user_message: str) -> str:
    """SHA-256 of the canonical JSON of the chat messages of one model call: a single user message.

    Same definition as ``agents.local_ollama`` (``ForecastResult.transcript_sha256``), so the store can recompute it.
    """
    if not isinstance(user_message, str):
        raise TypeError("transcript_sha256 takes the user message text")
    return sha256_hex(canonical_json([{"role": "user", "content": user_message}]))
