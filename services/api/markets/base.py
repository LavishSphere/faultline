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
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

Venue = Literal["kalshi", "polymarket"]

# Scale of a raw venue price:
#   "cents"   : integer-ish cents 0..100 (legacy Kalshi integer price fields)
#   "dollars" : Kalshi FixedPointDollars string, $0..$1 per $1-notional contract
#   "decimal" : Polymarket decimal price 0..1
RawScale = Literal["cents", "dollars", "decimal"]

# How the quote was obtained. Preference order (MATH_MODEL §7): midpoint, candle_close, last_trade.
# "price_history_point" is a Polymarket CLOB /prices-history point. The official docs do not
# say whether ``p`` is a midpoint or a last trade, so we refuse to label it as either.
QuoteKind = Literal["midpoint", "candle_close", "last_trade", "price_history_point"]

MARKET_LABEL = (
    "market-implied probability (price-derived; affected by fees, spread, liquidity), "
    "not a true probability"
)
MarketLabel = Literal[
    "market-implied probability (price-derived; affected by fees, spread, liquidity), "
    "not a true probability"
]
PROVENANCE_REAL = "REAL HISTORICAL"
PROVENANCE_SYNTHETIC = "SYNTHETIC"
NOT_AVAILABLE = "NOT AVAILABLE"


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

    venue: Venue
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

    venue: Venue
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
    # Fixed: the only allowed value is MARKET_LABEL, so no caller can relabel a quote as a
    # "true probability".
    label: MarketLabel = MARKET_LABEL

    @field_validator("ts", "collected_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _require_utc(v)

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

    venue: Venue

    def get_market(self, market_id: str) -> MarketMeta: ...

    def get_history(self, market_id: str, start: datetime, end: datetime) -> list[RawQuote]: ...
