"""Raw-response provenance: exact bytes on disk plus a SHA-256 manifest.

Layout (market-data skill)::

    data/raw/<venue>/<market_id>/<collected_at>.json   exact response bytes
    data/raw/<venue>/<market_id>/manifest.json         {"entries": [{path, sha256, url, params, collected_at, ...}]}

``store_raw`` refuses any body that contains settlement/outcome keys (Kalshi market
``result``/``settlement_*``, Gamma ``outcomePrices``/``umaResolutionStatus`` ...). Those
responses belong in ``data/sealed_outcomes/`` (owned by the replay workstream), never in
``data/raw/`` where the agent path can read quotes.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import PROVENANCE_REAL, MarketDataError, Venue

# Keys that reveal (or after settlement, encode) the outcome. Matched case-insensitively
# against every key in the JSON body.
OUTCOME_KEYS = frozenset(
    {
        "result",
        "expiration_value",
        "settlement_value",
        "settlement_value_dollars",
        "settlement_ts",
        "settlement_floor_dollars",
        "yes_settlement_value_dollars",
        "outcomeprices",
        "umaresolutionstatus",
        "umaresolutionstatuses",
        "resolvedby",
        "closedtime",
        "automaticallyresolved",
        "winner",
        "final_price",
    }
)


@dataclass(frozen=True)
class RawResponse:
    """One HTTP response exactly as received (bytes untouched)."""

    url: str  # request URL without query string
    params: dict[str, Any]
    status_code: int
    body: bytes
    collected_at: datetime
    endpoint: str = ""  # short label, e.g. "kalshi.historical_candlesticks"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def sha256(self) -> str:
        return sha256_hex(self.body)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _walk_keys(obj: Any):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


def find_outcome_keys(body: bytes) -> set[str]:
    """Return outcome-revealing keys present anywhere in a JSON body.

    A body that is not valid JSON raises: it cannot be checked, so it must not pass as clean.
    """
    try:
        obj = json.loads(body)
    except ValueError as exc:
        raise MarketDataError("response body is not valid JSON; cannot check it for outcome keys") from exc
    return {k for k in _walk_keys(obj) if k.lower() in OUTCOME_KEYS}


def _atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file in the same directory + os.replace, so readers never see a partial file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def _stamp(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _safe_component(s: str) -> str:
    if not s or "/" in s or "\\" in s or s in (".", "..") or s.startswith("."):
        raise MarketDataError(f"unsafe path component {s!r}")
    return s


def store_raw(raw_root: Path, venue: Venue, market_id: str, resp: RawResponse) -> Path:
    """Write ``resp.body`` byte-for-byte and append a manifest entry. Returns the file path."""
    if resp.status_code != 200:
        raise MarketDataError(f"refusing to store non-200 response ({resp.status_code})")
    leaked = find_outcome_keys(resp.body)  # raises on non-JSON bodies
    if leaked:
        raise MarketDataError(
            f"refusing to store a response with outcome keys {sorted(leaked)} in data/raw; "
            "settlement data goes only to data/sealed_outcomes/"
        )
    d = Path(raw_root) / _safe_component(venue) / _safe_component(market_id)
    d.mkdir(parents=True, exist_ok=True)
    name = f"{_stamp(resp.collected_at)}.json"
    path = d / name
    try:
        with open(path, "xb") as fh:  # exclusive create: raw files are immutable
            fh.write(resp.body)
    except FileExistsError as exc:
        raise MarketDataError(f"{path} already exists; raw files are immutable") from exc

    manifest_path = d / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {"entries": []}
    )
    manifest["entries"].append(
        {
            "path": f"{venue}/{market_id}/{name}",
            "sha256": resp.sha256,
            "bytes": len(resp.body),
            "url": resp.url,
            "params": resp.params,
            "http_status": resp.status_code,
            "endpoint": resp.endpoint,
            "collected_at": resp.collected_at.astimezone(UTC).isoformat(),
            "provenance": PROVENANCE_REAL,
            **({"notes": resp.extra} if resp.extra else {}),
        }
    )
    _atomic_write_text(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


def load_manifest(raw_root: Path, venue: str, market_id: str) -> list[dict[str, Any]]:
    p = Path(raw_root) / venue / market_id / "manifest.json"
    return json.loads(p.read_text("utf-8"))["entries"]


def verify_manifest(raw_root: Path, venue: str, market_id: str) -> list[str]:
    """Recompute every entry's SHA-256. Returns a list of problems (empty == all good)."""
    problems: list[str] = []
    for e in load_manifest(raw_root, venue, market_id):
        f = Path(raw_root) / e["path"]
        if not f.is_file():
            problems.append(f"missing file {e['path']}")
            continue
        got = sha256_hex(f.read_bytes())
        if got != e["sha256"]:
            problems.append(f"sha256 mismatch for {e['path']}: manifest {e['sha256']} != file {got}")
    return problems
