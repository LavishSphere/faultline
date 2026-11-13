"""Read-only Polymarket (decentralized, polymarket.com) adapter. Public GET endpoints only.

Verified on 2026-11-12 (full record in markets/README.md):

* Gamma ``https://gamma-api.polymarket.com``: ``GET /markets/{id}`` and ``GET /markets/slug/{slug}``
  return a Market object (docs.polymarket.com/api-spec/gamma-openapi.yaml). ``outcomes``,
  ``outcomePrices`` and ``clobTokenIds`` are JSON-encoded *strings*; entries at the same index
  describe the same outcome, and for binary markets index 0 is YES, index 1 is NO
  (docs.polymarket.com/market-data/market-details.md). For ``version == "v2"`` markets the
  identifiers are in ``positionIds`` (an array) instead of ``clobTokenIds``.
* CLOB ``GET https://clob.polymarket.com/prices-history`` (clob-openapi.yaml, ``security: []``):
  ``market`` (asset/token id, required), ``startTs``/``endTs`` (unix timestamps, optional),
  ``interval`` (max|all|1m|1w|1d|6h|1h, optional), ``fidelity`` (minutes, default 1).
  Response ``{"history": [{"t": uint32, "p": float}]}``. ``t`` is unix SECONDS: the Polymarket
  Institute guide's example shows ``"t":1784493604`` and our own collected responses confirm it.
* The docs do not say whether ``p`` is a midpoint or a last trade, so quotes from it are labelled
  ``price_history_point``, never ``midpoint``/``last_trade``.
* polymarket.us is a separate exchange with separate APIs and data; it is not handled here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import httpx

from .base import HistoryNotAvailable, MarketDataError, MarketMeta, RawQuote
from .normalize import parse_epoch, parse_iso_utc
from .raw_store import RawResponse, sha256_hex

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
CLOB_BASE_URL = "https://clob.polymarket.com"
USER_AGENT = "faultline-research-client/0.1 (read-only)"
# The CLOB spec documents no maximum startTs/endTs span. The newer data-api v2 endpoint caps
# explicit ranges at 15 days, so we chunk conservatively at 14 days.
CHUNK = timedelta(days=14)


def _json_list(v: Any, field: str) -> list[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        parsed = json.loads(v)
        if not isinstance(parsed, list):
            raise MarketDataError(f"Gamma field {field!r} is not a JSON list")
        return parsed
    raise MarketDataError(f"Gamma field {field!r} has unexpected type {type(v).__name__}")


def parse_gamma_market(body: bytes, *, source_url: str) -> MarketMeta:
    """Parse a Gamma Market into MarketMeta. Drops outcomePrices, closedTime, UMA status etc."""
    m = json.loads(body)
    if isinstance(m, list):  # /markets?id=... returns a list
        if len(m) != 1:
            raise MarketDataError(f"expected exactly one market, got {len(m)}")
        m = m[0]
    if not isinstance(m, dict) or "id" not in m:
        raise MarketDataError("Gamma market response missing 'id'")
    labels = [str(x) for x in _json_list(m.get("outcomes"), "outcomes")]
    if m.get("version") == "v2":
        ids = [str(x) for x in (m.get("positionIds") or [])]
    else:
        ids = [str(x) for x in _json_list(m.get("clobTokenIds"), "clobTokenIds")]
    is_binary = [lbl.lower() for lbl in labels] == ["yes", "no"]
    yes_token = None
    if is_binary:
        if len(ids) != 2:
            raise MarketDataError(f"binary market {m['id']} has {len(ids)} token ids, expected 2")
        yes_token = ids[0]  # docs: index 0 is YES for binary markets
    return MarketMeta(
        venue="polymarket",
        market_id=str(m["id"]),
        # Web URL scheme for a single market is not documented; the API resource URL is used.
        url=source_url,
        title=m.get("question") or str(m["id"]),
        yes_label=labels[0] if labels else None,
        rules=m.get("description") or None,
        reference_source=m.get("resolutionSource") or None,
        is_binary=is_binary,
        sides=tuple(labels),
        open_time=parse_iso_utc(m.get("startDate")),
        close_time=parse_iso_utc(m.get("endDate")),  # scheduled end, not the post-hoc closedTime
        mutually_exclusive_group=m.get("negRisk"),
        group_id=m.get("negRiskMarketID") or None,
        yes_token_id=yes_token,
        source_url=source_url,
    )


def parse_prices_history(
    body: bytes,
    *,
    market_id: str,
    token_id: str,
    source_url: str,
    collected_at: datetime,
    fidelity_minutes: int | None,
    market_url: str | None = None,
) -> list[RawQuote]:
    """Parse ``{"history": [{"t", "p"}]}``. ``t`` is unix seconds; ``p`` kept as exact text."""
    digest = sha256_hex(body)
    data = json.loads(body, parse_float=Decimal)
    hist = data.get("history") if isinstance(data, dict) else None
    if not isinstance(hist, list):
        raise MarketDataError("prices-history response missing 'history' list")
    out: list[RawQuote] = []
    for i, pt in enumerate(hist):
        try:
            t, p = pt["t"], pt["p"]
        except (KeyError, TypeError) as exc:
            raise MarketDataError(f"history point {i} missing t/p") from exc
        if isinstance(p, bool) or not isinstance(p, (int, Decimal, str)):
            raise MarketDataError(f"history point {i} has non-numeric p {p!r}")
        out.append(
            RawQuote(
                venue="polymarket",
                market_id=market_id,
                url=market_url or source_url,
                source_url=source_url,
                ts=parse_epoch(t, "s"),
                raw_scale="decimal",
                point=str(p),
                period_seconds=fidelity_minutes * 60 if fidelity_minutes else None,
                collected_at=collected_at,
                raw_sha256=digest,
            )
        )
    return out


class PolymarketProvider:
    """EventMarketProvider for Polymarket. ``market_id`` is the Gamma market id."""

    venue: Literal["polymarket"] = "polymarket"

    def __init__(
        self,
        client: httpx.Client | None = None,
        gamma_base_url: str = GAMMA_BASE_URL,
        clob_base_url: str = CLOB_BASE_URL,
    ) -> None:
        self.gamma = gamma_base_url.rstrip("/")
        self.clob = clob_base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT})

    def _get(self, url: str, params: dict[str, Any] | None, endpoint: str) -> RawResponse:
        r = self._client.get(url, params=params or None)
        resp = RawResponse(
            url=url,
            params=dict(params or {}),
            status_code=r.status_code,
            body=r.content,
            collected_at=datetime.now(UTC),
            endpoint=endpoint,
        )
        if resp.status_code != 200:
            raise MarketDataError(f"GET {url} -> HTTP {resp.status_code}: {resp.body[:200]!r}")
        return resp

    def fetch_market(self, market_id: str) -> RawResponse:
        """NOTE: the body contains outcomePrices/closedTime/UMA status; never store it in data/raw."""
        return self._get(f"{self.gamma}/markets/{market_id}", None, "polymarket.gamma_market")

    def get_market(self, market_id: str) -> MarketMeta:
        resp = self.fetch_market(market_id)
        return parse_gamma_market(resp.body, source_url=resp.url)

    def fetch_history_raw(
        self, meta: MarketMeta, start: datetime, end: datetime, fidelity_minutes: int = 60
    ) -> list[RawResponse]:
        if not meta.is_binary or not meta.yes_token_id:
            raise MarketDataError(f"{meta.market_id} is not a binary market with a YES token id")
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise MarketDataError("start/end must be aware datetimes with start < end")
        out: list[RawResponse] = []
        lo = start
        while lo < end:
            hi = min(lo + CHUNK, end)
            params = {
                "market": meta.yes_token_id,
                "startTs": int(lo.timestamp()),
                "endTs": int(hi.timestamp()),
                "fidelity": fidelity_minutes,
            }
            out.append(self._get(f"{self.clob}/prices-history", params, "polymarket.clob_prices_history"))
            lo = hi
        return out

    def parse_history(
        self, meta: MarketMeta, responses: list[RawResponse], fidelity_minutes: int
    ) -> list[RawQuote]:
        assert meta.yes_token_id is not None
        quotes: dict[datetime, RawQuote] = {}
        for resp in responses:
            for q in parse_prices_history(
                resp.body,
                market_id=meta.market_id,
                token_id=meta.yes_token_id,
                source_url=resp.url,
                collected_at=resp.collected_at,
                fidelity_minutes=fidelity_minutes,
                market_url=meta.url,
            ):
                prev = quotes.get(q.ts)
                if prev is not None and prev.point != q.point:
                    raise MarketDataError(f"conflicting points at {q.ts.isoformat()} across chunks")
                quotes.setdefault(q.ts, q)
        return [quotes[k] for k in sorted(quotes)]

    def get_history(
        self, market_id: str, start: datetime, end: datetime, fidelity_minutes: int = 60
    ) -> list[RawQuote]:
        meta = self.get_market(market_id)
        quotes = self.parse_history(
            meta, self.fetch_history_raw(meta, start, end, fidelity_minutes), fidelity_minutes
        )
        if not quotes:
            raise HistoryNotAvailable(
                f"CLOB prices-history returned no points for {market_id} in [{start}, {end}]"
            )
        return quotes
