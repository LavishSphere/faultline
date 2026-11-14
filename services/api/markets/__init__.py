"""Read-only prediction-market data layer (SPEC §4, MATH_MODEL §7).

Collection is an offline step. Replay inference must read saved snapshots, never these APIs.
"""

from .base import (
    MARKET_LABEL,
    NOT_AVAILABLE,
    SYNTHETIC_QUOTE_LABEL,
    AlreadyNormalizedError,
    EventMarketProvider,
    HistoryNotAvailable,
    MarketDataError,
    MarketMeta,
    NormalizedQuote,
    OutOfRangePrice,
    RawQuote,
    synthetic_quote_sha256,
)
from .normalize import (
    DEFAULT_MAX_STALENESS,
    normalize_price,
    normalize_quote,
    normalize_quotes,
    parse_epoch,
    select_quote,
)

__all__ = [
    "DEFAULT_MAX_STALENESS",
    "MARKET_LABEL",
    "NOT_AVAILABLE",
    "SYNTHETIC_QUOTE_LABEL",
    "AlreadyNormalizedError",
    "EventMarketProvider",
    "HistoryNotAvailable",
    "MarketDataError",
    "MarketMeta",
    "NormalizedQuote",
    "OutOfRangePrice",
    "RawQuote",
    "normalize_price",
    "normalize_quote",
    "normalize_quotes",
    "parse_epoch",
    "select_quote",
    "synthetic_quote_sha256",
]
