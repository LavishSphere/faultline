"""Exact price normalization, timestamp parsing and as-of quote selection (MATH_MODEL §7).

Rules implemented here:
* Kalshi legacy cents: p = c / 100. Kalshi FixedPointDollars and Polymarket decimals: p = x.
  Normalization happens once, at ingestion, using ``Decimal`` so "0.63" stays exactly 0.63.
* Values outside [0, 1] after normalization are rejected (``OutOfRangePrice``).
* Missing values (None / "") normalize to None. Nothing is ever interpolated or defaulted.
* Preference per observation: bid/ask midpoint, then candle close, then last trade, then a
  venue price-history point (Polymarket, methodology undocumented).
* ``select_quote`` returns the last quote with ``as_of - max_staleness <= ts <= as_of``,
  otherwise None, which callers must render as NOT AVAILABLE.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal

from .base import (
    AlreadyNormalizedError,
    MarketDataError,
    NormalizedQuote,
    OutOfRangePrice,
    RawQuote,
    RawScale,
)

_ONE = Decimal(1)
_ZERO = Decimal(0)
_HUNDRED = Decimal(100)
_HALF = Decimal("0.5")

# Epoch values below this are seconds, at/above it are milliseconds, for any date after
# 1973-03-03 (1e11 ms) and before year 5138 (1e11 s). Used only as a consistency check
# against the unit the caller declares, never to guess the unit silently.
_S_MS_BOUNDARY = 10**11

DEFAULT_MAX_STALENESS = timedelta(hours=24)

_KIND_RANK = {"midpoint": 0, "candle_close": 1, "last_trade": 2, "price_history_point": 3}


def _to_decimal(raw: object) -> Decimal | None:
    if isinstance(raw, NormalizedQuote):
        raise AlreadyNormalizedError("NormalizedQuote passed to normalization; normalize exactly once")
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise TypeError("boolean is not a price")
    if isinstance(raw, str):
        s = raw.strip()
        if s == "":
            return None
    elif isinstance(raw, (int, float, Decimal)):
        s = str(raw)
    else:
        raise TypeError(f"unsupported raw price type {type(raw).__name__}")
    try:
        d = Decimal(s)
    except InvalidOperation as exc:
        raise MarketDataError(f"unparseable price {raw!r}") from exc
    if not d.is_finite():
        raise OutOfRangePrice(f"non-finite price {raw!r}")
    return d


def normalize_price(raw: object, scale: RawScale) -> Decimal | None:
    """Convert one raw venue price to a YES probability in [0, 1], exactly.

    Returns None for a missing value. Raises ``OutOfRangePrice`` for anything outside the
    scale's range, and ``AlreadyNormalizedError`` for a cents value that is clearly already
    a probability (e.g. "0.63" declared as cents), which is the double-normalization bug.
    """
    d = _to_decimal(raw)
    if d is None:
        return None
    if scale == "cents":
        if d < _ZERO or d > _HUNDRED:
            raise OutOfRangePrice(f"{raw!r} cents outside [0, 100]")
        if _ZERO < d < _ONE:
            raise AlreadyNormalizedError(
                f"{raw!r} declared as cents looks like a probability; normalize exactly once"
            )
        # Integer cents, or a half-cent midpoint of two integer-cent quotes.
        if (d / _HALF) != (d / _HALF).to_integral_value():
            raise MarketDataError(f"{raw!r} is not an integer or half-integer cent value")
        p = d / _HUNDRED
    elif scale in ("dollars", "decimal"):
        p = d
    else:  # pragma: no cover - guarded by the Literal type
        raise ValueError(f"unknown scale {scale!r}")
    if p < _ZERO or p > _ONE:
        raise OutOfRangePrice(f"{raw!r} ({scale}) normalizes to {p}, outside [0, 1]")
    return p


def parse_epoch(value: object, unit: Literal["s", "ms"]) -> datetime:
    """Parse a Unix epoch in the *declared* unit to an aware UTC datetime.

    Raises if the magnitude contradicts the declared unit (seconds that look like
    milliseconds or vice versa), so a unit mix-up fails loudly instead of shifting dates.
    """
    if isinstance(value, bool) or value is None:
        raise TypeError(f"invalid epoch {value!r}")
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise MarketDataError(f"unparseable epoch {value!r}") from exc
    if not d.is_finite() or d < 0:
        raise MarketDataError(f"invalid epoch {value!r}")
    if unit == "s":
        if d >= _S_MS_BOUNDARY:
            raise MarketDataError(f"epoch {value!r} declared as seconds looks like milliseconds")
        seconds = d
    elif unit == "ms":
        if d < _S_MS_BOUNDARY:
            raise MarketDataError(f"epoch {value!r} declared as milliseconds looks like seconds")
        seconds = d / Decimal(1000)
    else:  # pragma: no cover
        raise ValueError(f"unknown unit {unit!r}")
    whole = int(seconds)
    micros = int(((seconds - whole) * 1_000_000).to_integral_value())
    return datetime.fromtimestamp(whole, tz=UTC) + timedelta(microseconds=micros)


def parse_iso_utc(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp (``Z`` or offset, or Gamma's ``+00`` form) to UTC."""
    if value is None or value == "":
        return None
    s = value.strip().replace("Z", "+00:00")
    if ":" in s[:-3] and s[-3] in "+-" and s[-2:].isdigit():
        s = s + ":00"  # "2026-07-29 20:06:41+00" -> "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise MarketDataError(f"timestamp without timezone: {value!r}")
    return dt.astimezone(UTC)


def _fmt(d: Decimal) -> str:
    return format(d.normalize(), "f") if d != 0 else "0"


def normalize_quote(raw: RawQuote) -> NormalizedQuote | None:
    """Normalize one RawQuote exactly once. Returns None if it carries no usable price."""
    if isinstance(raw, NormalizedQuote):
        raise AlreadyNormalizedError("quote is already normalized; normalize exactly once")
    if not isinstance(raw, RawQuote):
        raise TypeError(f"expected RawQuote, got {type(raw).__name__}")

    scale = raw.raw_scale
    bid = normalize_price(raw.yes_bid, scale)
    ask = normalize_price(raw.yes_ask, scale)

    kind: str | None = None
    raw_price: str | None = None
    spread: float | None = None

    # A two-sided book needs a real bid (> 0) and a real ask (< 1) that are not crossed.
    # Kalshi reports an empty side as 0.0000 / 1.0000; a "midpoint" of those would be a
    # made-up 0.5, so it is not used.
    two_sided = bid is not None and ask is not None and bid > _ZERO and ask < _ONE and bid <= ask
    if two_sided:
        assert raw.yes_bid is not None and raw.yes_ask is not None
        raw_mid = (_to_decimal(raw.yes_bid) + _to_decimal(raw.yes_ask)) / 2  # type: ignore[operator]
        kind, raw_price = "midpoint", _fmt(raw_mid)
        spread = float(ask - bid)  # type: ignore[operator]
    elif normalize_price(raw.trade_close, scale) is not None:
        kind, raw_price = "candle_close", str(raw.trade_close).strip()
    elif normalize_price(raw.last_trade, scale) is not None:
        kind, raw_price = "last_trade", str(raw.last_trade).strip()
    elif normalize_price(raw.point, scale) is not None:
        kind, raw_price = "price_history_point", str(raw.point).strip()

    if kind is None or raw_price is None:
        return None
    p = normalize_price(raw_price, scale)
    assert p is not None
    return NormalizedQuote(
        venue=raw.venue,
        market_id=raw.market_id,
        url=raw.url,
        source_url=raw.source_url,
        outcome=raw.outcome,
        p_yes=float(p),
        quote_kind=kind,  # type: ignore[arg-type]
        ts=raw.ts,
        raw_price=raw_price,
        raw_scale=scale,
        raw_bid=raw.yes_bid,
        raw_ask=raw.yes_ask,
        spread=spread,
        volume=raw.volume,
        open_interest=raw.open_interest,
        period_seconds=raw.period_seconds,
        collected_at=raw.collected_at,
        raw_sha256=raw.raw_sha256,
    )


def normalize_quotes(raws: Iterable[RawQuote]) -> list[NormalizedQuote]:
    """Normalize many quotes, dropping observations that carry no price. Out-of-range raises."""
    out: list[NormalizedQuote] = []
    for r in raws:
        q = normalize_quote(r)
        if q is not None:
            out.append(q)
    return out


def select_quote(
    quotes: Iterable[NormalizedQuote],
    as_of: datetime,
    max_staleness: timedelta = DEFAULT_MAX_STALENESS,
) -> NormalizedQuote | None:
    """Last actual quote with ``as_of - max_staleness <= ts <= as_of``, else None.

    None means the market baseline is NOT AVAILABLE for this ``as_of``. Quotes after
    ``as_of`` are never considered. All quotes must belong to one venue/market.
    Accepts any iterable (including a one-shot generator): it is materialized once first.
    """
    quotes = list(quotes)
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if max_staleness < timedelta(0):
        raise ValueError("max_staleness must be non-negative")
    as_of = as_of.astimezone(UTC)
    if not quotes:
        return None
    for q in quotes:
        if not isinstance(q, NormalizedQuote):
            raise TypeError("select_quote needs NormalizedQuote values")
    ids = {(q.venue, q.market_id, q.outcome) for q in quotes}
    if len(ids) > 1:
        raise ValueError(f"select_quote got quotes for several markets: {sorted(ids)}")

    floor = as_of - max_staleness
    eligible = [q for q in quotes if floor <= q.ts <= as_of]
    if not eligible:
        return None
    latest_ts = max(q.ts for q in eligible)
    at_latest = [q for q in eligible if q.ts == latest_ts]
    best_rank = min(_KIND_RANK[q.quote_kind] for q in at_latest)
    best = [q for q in at_latest if _KIND_RANK[q.quote_kind] == best_rank]
    if len({q.raw_price for q in best}) > 1:
        raise MarketDataError(
            f"conflicting {best[0].quote_kind} quotes at {latest_ts.isoformat()}; refusing to pick one"
        )
    return best[0]
