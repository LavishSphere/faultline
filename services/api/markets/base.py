"""Shared types for the read-only prediction-market data layer (SPEC §4, MATH_MODEL §7).

Self-contained on purpose: nothing here imports the app's ``models.py``.

Two quote types exist so that normalization cannot silently run twice:

* ``RawQuote`` holds venue values *exactly as received* (strings, original scale).
* ``NormalizedQuote`` holds ``p_yes`` in [0, 1] plus the raw value and scale it was
  derived from. Its validator recomputes ``p_yes`` from ``raw_price``/``raw_scale``,
  so a quote whose probability was divided twice (0.0063) or never divided (63)
  cannot be constructed.

Market prices are price-derived implied probabilities, distorted by fees, spread,
liquidity and incentives. They are not "true" probabilities. See ``MARKET_LABEL``.

Venue ``"synthetic"`` (issue #102) exists only so a SYNTHETIC demo case can carry a hand-written
benchmark price. Such a quote must say so in every field that could be mistaken for a real one:
``provenance == "SYNTHETIC"``, ``quote_kind == "synthetic"``, ``label == SYNTHETIC_QUOTE_LABEL`` (filled in
when absent), ``raw_scale == "decimal"`` and URLs on an RFC 2606 ``.invalid`` host. Real venues can never carry
those values. Nothing was fetched, so two fields have a fixed meaning: ``collected_at`` is when the case author
wrote the price into the case file, and ``raw_sha256`` must equal ``synthetic_quote_sha256(market_id, ts,
raw_price)`` (SHA-256 of the canonical JSON of those three values plus the venue), never a hash of venue bytes.
The collection path (``MarketMeta``, ``RawQuote``, ``EventMarketProvider``, ``raw_store``) uses ``RealVenue``
only, so nothing synthetic can be collected or stored under ``data/raw``. The temporal gate refuses a synthetic
quote on a case that is not ``synthetic: true``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol, runtime_checkable
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

# Venues that data is collected from (read-only public APIs).
RealVenue = Literal["kalshi", "polymarket"]
# Any venue a NormalizedQuote may name. "synthetic" = a fictional price written by a case author for a
# SYNTHETIC case; never collected, never REAL HISTORICAL.
Venue = Literal["kalshi", "polymarket", "synthetic"]
SYNTHETIC_VENUE = "synthetic"

# Scale of a raw venue price:
#   "cents"   : integer-ish cents 0..100 (legacy Kalshi integer price fields)
#   "dollars" : Kalshi FixedPointDollars string, $0..$1 per $1-notional contract
#   "decimal" : Polymarket decimal price 0..1
RawScale = Literal["cents", "dollars", "decimal"]

# How the quote was obtained. Preference order (MATH_MODEL §7): midpoint, candle_close, last_trade.
# "price_history_point" is a Polymarket CLOB /prices-history point. The official docs do not
# say whether ``p`` is a midpoint or a last trade, so we refuse to label it as either.
# "synthetic" is the only kind a synthetic-venue quote may have (and no real quote may have it).
QuoteKind = Literal["midpoint", "candle_close", "last_trade", "price_history_point", "synthetic"]

MARKET_LABEL = (
    "market-implied probability (price-derived; affected by fees, spread, liquidity), "
    "not a true probability"
)
# The only label a synthetic-venue quote may carry (and no real quote may carry it).
SYNTHETIC_QUOTE_LABEL = (
    "SYNTHETIC benchmark price written by the case author; not from any market, not a true probability"
)
MarketLabel = Literal[
    "market-implied probability (price-derived; affected by fees, spread, liquidity), "
    "not a true probability",
    "SYNTHETIC benchmark price written by the case author; not from any market, not a true probability",
]
PROVENANCE_REAL = "REAL HISTORICAL"
PROVENANCE_SYNTHETIC = "SYNTHETIC"
NOT_AVAILABLE = "NOT AVAILABLE"
# Wire values of a quote's provenance; the same strings as ``models.Provenance`` (this module does not
# import models.py). A test checks they stay a subset of it.
QuoteProvenance = Literal["REAL_HISTORICAL", "SYNTHETIC"]


def synthetic_quote_sha256(market_id: str, ts: datetime, raw_price: str) -> str:
    """The required ``raw_sha256`` of a synthetic quote: SHA-256 of the canonical JSON (sorted keys, no
    whitespace, UTF-8) of ``{"market_id", "raw_price", "ts" (UTC, ISO-8601 with Z), "venue": "synthetic"}``."""
    payload = {
        "market_id": market_id,
        "raw_price": raw_price,
        "ts": _require_utc(ts).isoformat().replace("+00:00", "Z"),
        "venue": SYNTHETIC_VENUE,
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class MarketDataError(Exception):
    """Base error for the markets package."""


class OutOfRangePrice(MarketDataError, ValueError):
    """A price fell outside [0, 1] after normalization (or outside its raw scale)."""


class AlreadyNormalizedError(MarketDataError, TypeError):
    """Raised when a value that is already a probability is fed back into normalization."""


class HistoryNotAvailable(MarketDataError):
    """The venue did not return usable history. Callers must record NOT AVAILABLE."""


def _require_utc(v: datetime) -> datetime:
    if not isinstance(v, datetime):
        raise TypeError("expected datetime")
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError("naive datetime rejected: timestamps must be timezone-aware UTC")
    return v.astimezone(UTC)


class MarketMeta(BaseModel):
    """Pre-resolution market metadata.

    Deliberately has NO outcome/settlement fields (result, settlement value, resolved
    price, final status). Parsers drop those keys so leakage is a type error, not a
    forgotten ``if``. Raw metadata responses DO contain them and must not be stored in
    ``data/raw`` where the agent path can read them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    venue: RealVenue
    market_id: str
    url: str
    title: str
    yes_label: str | None = None
    rules: str | None = None
    # Named source of truth the rules point to (pre-resolution info; Gamma ``resolutionSource``).
    # None -> NOT AVAILABLE from this endpoint. Field names here deliberately avoid
    # outcome|resolution|settle|result so the replay temporal gate's key-stripping does not
    # silently drop them, and so a key-walk leak check stays strict.
    reference_source: str | None = None
    is_binary: bool
    sides: tuple[str, ...] = ()  # venue labels in index order, e.g. ("Yes", "No")
    open_time: datetime | None = None
    close_time: datetime | None = None
    # True when the market belongs to a mutually exclusive group (Kalshi MECNET event,
    # Polymarket negRisk). Such markets must not be treated as independent events.
    mutually_exclusive_group: bool | None = None
    group_id: str | None = None  # Kalshi event_ticker / Polymarket negRiskMarketID
    yes_token_id: str | None = None  # Polymarket CLOB asset id for the YES outcome
    series_ticker: str | None = None  # Kalshi, needed for the live candlestick endpoint
    data_tier: Literal["live", "historical"] | None = None  # Kalshi partition used
    # Kalshi GET /historical/cutoff ``market_settled_ts`` value that decided ``data_tier``.
    kalshi_tier_cutoff: datetime | None = None
    source_url: str

    @field_validator("open_time", "close_time", "kalshi_tier_cutoff")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return None if v is None else _require_utc(v)


class RawQuote(BaseModel):
    """One observation as received from a venue. Prices are kept as exact strings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    venue: RealVenue
    market_id: str
    url: str  # human-facing market URL
    source_url: str  # API endpoint the bytes came from
    outcome: Literal["YES"] = "YES"
    ts: datetime  # observation time (candle end for candles), UTC
    raw_scale: RawScale
    yes_bid: str | None = None  # best YES bid at ts (candle close of bid distribution)
    yes_ask: str | None = None  # best YES ask at ts
    trade_close: str | None = None  # last trade price within the candle (null = no trades)
    last_trade: str | None = None  # standalone last-trade price
    point: str | None = None  # venue price-series point (Polymarket prices-history ``p``)
    volume: str | None = None
    open_interest: str | None = None
    period_seconds: int | None = None
    collected_at: datetime
    raw_sha256: str

    @field_validator("ts", "collected_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _require_utc(v)


class NormalizedQuote(BaseModel):
    """A YES-side implied probability with full provenance (MATH_MODEL §7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    venue: Venue
    market_id: str
    url: str
    source_url: str
    outcome: Literal["YES"] = "YES"
    p_yes: float
    quote_kind: QuoteKind
    ts: datetime
    raw_price: str  # the raw value p_yes was derived from (for midpoint: (bid+ask)/2 in raw scale)
    raw_scale: RawScale
    raw_bid: str | None = None
    raw_ask: str | None = None
    spread: float | None = None  # ask - bid, probability units
    volume: str | None = None
    open_interest: str | None = None
    period_seconds: int | None = None
    collected_at: datetime
    raw_sha256: str
    # Fixed by the venue: MARKET_LABEL for a real venue, SYNTHETIC_QUOTE_LABEL for venue "synthetic" (filled in
    # when absent). No caller can relabel a quote as a "true probability" or a synthetic price as a real one.
    label: MarketLabel = MARKET_LABEL
    # REAL_HISTORICAL for quotes from a real venue; SYNTHETIC exactly when venue == "synthetic".
    provenance: QuoteProvenance = "REAL_HISTORICAL"

    @field_validator("ts", "collected_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _require_utc(v)

    @model_validator(mode="before")
    @classmethod
    def _default_synthetic_label(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("venue") == SYNTHETIC_VENUE and "label" not in data:
            return {**data, "label": SYNTHETIC_QUOTE_LABEL}
        return data

    @model_validator(mode="after")
    def _synthetic_is_labelled(self) -> NormalizedQuote:
        synthetic = self.venue == SYNTHETIC_VENUE
        if self.label != (SYNTHETIC_QUOTE_LABEL if synthetic else MARKET_LABEL):
            raise ValueError("a quote's label is fixed by its venue (SYNTHETIC_QUOTE_LABEL only for \"synthetic\")")
        if synthetic != (self.provenance == "SYNTHETIC"):
            raise ValueError('a quote has provenance "SYNTHETIC" if and only if its venue is "synthetic"')
        if synthetic != (self.quote_kind == "synthetic"):
            raise ValueError('a quote has quote_kind "synthetic" if and only if its venue is "synthetic"')
        if synthetic:
            if self.raw_scale != "decimal":
                raise ValueError('a synthetic quote must use raw_scale "decimal"')
            for field in ("url", "source_url"):
                host = (urlsplit(getattr(self, field)).hostname or "").casefold()
                if not host.endswith(".invalid"):
                    raise ValueError(
                        f"a synthetic quote's {field} must be on an RFC 2606 .invalid host, so it cannot "
                        "point at a real venue"
                    )
            if self.raw_sha256 != synthetic_quote_sha256(self.market_id, self.ts, self.raw_price):
                raise ValueError(
                    "a synthetic quote's raw_sha256 must be synthetic_quote_sha256(market_id, ts, raw_price); "
                    "nothing was fetched, so it is never a hash of venue bytes"
                )
        return self

    @model_validator(mode="after")
    def _exactly_once(self) -> NormalizedQuote:
        # Local import avoids a cycle (normalize imports this module).
        from .normalize import normalize_price

        expected = normalize_price(self.raw_price, self.raw_scale)
        if expected is None or float(expected) != self.p_yes:
            raise ValueError(
                f"p_yes={self.p_yes!r} is not normalize({self.raw_price!r}, {self.raw_scale!r}); "
                "normalization must be applied exactly once"
            )
        return self

    @property
    def p_yes_exact(self) -> Decimal:
        from .normalize import normalize_price

        value = normalize_price(self.raw_price, self.raw_scale)
        assert value is not None
        return value


@runtime_checkable
class EventMarketProvider(Protocol):
    """Read-only venue adapter. Collection is an offline step; replay never calls this."""

    venue: RealVenue

    def get_market(self, market_id: str) -> MarketMeta: ...

    def get_history(self, market_id: str, start: datetime, end: datetime) -> list[RawQuote]: ...
