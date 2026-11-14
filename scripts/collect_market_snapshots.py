#!/usr/bin/env python3
"""Offline snapshot collector for Kalshi + Polymarket price history (SPEC §4, MATH_MODEL §7, issue #51).

Collection is an OFFLINE step. Replay inference never runs this and never calls the venue APIs; it reads
the stored bytes under ``services/api/data/raw/``.

What it does, per market:

1. Fetch the market's metadata with the #12 adapters (public, read-only GETs). The metadata body carries
   settlement fields (Kalshi ``result``/``settlement_*``, Gamma ``outcomePrices`` ...). It is parsed in
   memory into ``MarketMeta`` (which has no outcome fields) and is **never stored**.
2. Work out the price window. Default rule ("T-7"): ``end`` = 00:00 UTC on the day of
   ``reference_close - 7 days``, ``start`` = ``end - lookback_days``. The window is refused if it ends later
   than ``reference_close - min_lead_days``, so stored files never contain near-settlement prices.
3. Skip if the manifest already holds a snapshot of the same endpoint and parameters that covers the window
   (idempotent). Otherwise fetch the price history, check every body for outcome keys, check that no price
   point lies after the window end, and store the exact bytes + a manifest entry via ``raw_store.store_raw``
   (exclusive create: files are never overwritten).

Subcommands::

    # one market, window from the market's own scheduled close (or --reference-close / --start --end)
    python scripts/collect_market_snapshots.py market --venue kalshi --market-id KXFEDDECISION-26JUL-H0
    # every candidate in the #51 plan (both venues, same window per pair)
    python scripts/collect_market_snapshots.py plan
    # offline: does a quote exist at T-7 (last quote <= as_of within 24h)? No network.
    python scripts/collect_market_snapshots.py report

It prints counts and availability only, never prices and never outcomes.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

API_DIR = Path(__file__).resolve().parents[1] / "services" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from markets.base import NOT_AVAILABLE, MarketDataError, MarketMeta, RawQuote  # noqa: E402
from markets.kalshi import KalshiProvider, parse_candlesticks  # noqa: E402
from markets.normalize import DEFAULT_MAX_STALENESS, normalize_quotes, parse_iso_utc, select_quote  # noqa: E402
from markets.polymarket import PolymarketProvider, parse_prices_history  # noqa: E402
from markets.raw_store import find_outcome_keys, load_manifest, store_raw  # noqa: E402

DEFAULT_RAW_ROOT = API_DIR / "data" / "raw"
DEFAULT_PLAN = DEFAULT_RAW_ROOT / "candidate_plan_51.json"
USER_AGENT = "faultline-research-client/0.1 (read-only)"
DEFAULT_T_MINUS_DAYS = 7
DEFAULT_LOOKBACK_DAYS = 3
DEFAULT_GRANULARITY_MIN = 60  # Kalshi period_interval / Polymarket fidelity, minutes
DEFAULT_MIN_LEAD_DAYS = 7
# Hard floor: no override may collect prices closer than this to a scheduled close.
LEAD_FLOOR_DAYS = 7

# Manifest endpoint labels that hold price history, and the names of their time-window params.
PRICE_ENDPOINTS: dict[str, tuple[str, str]] = {
    "kalshi.historical_candlesticks": ("start_ts", "end_ts"),
    "kalshi.live_candlesticks": ("start_ts", "end_ts"),
    "polymarket.clob_prices_history": ("startTs", "endTs"),
}


# --- windows -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    reference_close: datetime
    rule: str

    def as_notes(self) -> dict[str, str]:
        return {
            "window_rule": self.rule,
            "window_start": self.start.isoformat(),
            "window_end": self.end.isoformat(),
            "reference_close": self.reference_close.isoformat(),
        }


def _aware(dt: datetime, name: str) -> datetime:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MarketDataError(f"{name} must be timezone-aware (UTC)")
    return dt.astimezone(UTC)


def t_minus_window(
    reference_close: datetime,
    t_minus_days: int = DEFAULT_T_MINUS_DAYS,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> Window:
    """``end`` = 00:00 UTC on the day of ``reference_close - t_minus_days``; ``start = end - lookback_days``.

    Flooring to midnight keeps ``end <= reference_close - t_minus_days`` for any close time, and gives both
    venues of a pair the same window when they share a reference close.
    """
    if t_minus_days < 0 or lookback_days <= 0:
        raise MarketDataError("t_minus_days must be >= 0 and lookback_days > 0")
    ref = _aware(reference_close, "reference_close")
    lead = ref - timedelta(days=t_minus_days)
    end = lead.replace(hour=0, minute=0, second=0, microsecond=0)
    return Window(
        start=end - timedelta(days=lookback_days),
        end=end,
        reference_close=ref,
        rule=f"T-{t_minus_days}d: end = 00:00Z of (reference_close - {t_minus_days}d), lookback {lookback_days}d",
    )


def explicit_window(start: datetime, end: datetime, reference_close: datetime) -> Window:
    start, end = _aware(start, "start"), _aware(end, "end")
    if end <= start:
        raise MarketDataError("start must be before end")
    return Window(start, end, _aware(reference_close, "reference_close"), "explicit start/end")


def check_lead(window: Window, min_lead_days: int, label: str = "reference_close") -> None:
    """Refuse windows that reach into the last ``min_lead_days`` before the scheduled close."""
    latest = window.reference_close - timedelta(days=min_lead_days)
    if window.end > latest:
        raise MarketDataError(
            f"window ends {window.end.isoformat()}, later than {label} - {min_lead_days}d "
            f"({latest.isoformat()}); near-settlement prices are not collected"
        )


# --- HTTP ---------------------------------------------------------------------------------------


class RetryOn429(httpx.BaseTransport):
    """Retries HTTP 429 with backoff (unauthenticated rate limits are not published). GET only."""

    def __init__(
        self,
        inner: httpx.BaseTransport | None = None,
        retries: int = 5,
        backoff_s: float = 1.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.inner = inner or httpx.HTTPTransport()
        self.retries, self.backoff_s, self.sleep = retries, backoff_s, sleep

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            raise MarketDataError(f"read-only collector refuses {request.method} {request.url}")
        for attempt in range(self.retries + 1):
            resp = self.inner.handle_request(request)
            if resp.status_code != 429 or attempt == self.retries:
                return resp
            resp.read()
            resp.close()
            self.sleep(self.backoff_s * (attempt + 1))
        raise AssertionError("unreachable")

    def close(self) -> None:
        self.inner.close()


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        transport=RetryOn429(transport),
        timeout=30.0,
        headers={"User-Agent": USER_AGENT},
    )


def make_provider(venue: str, client: httpx.Client) -> KalshiProvider | PolymarketProvider:
    if venue == "kalshi":
        return KalshiProvider(client=client)
    if venue == "polymarket":
        return PolymarketProvider(client=client)
    raise MarketDataError(f"unknown venue {venue!r}")


# --- idempotence ------------------------------------------------------------------------------------


def _expected(venue: str, meta: MarketMeta, granularity: int) -> tuple[str, dict[str, Any]]:
    """Manifest endpoint label + the non-time params a history request for ``meta`` would carry."""
    if venue == "kalshi":
        endpoint = "kalshi.historical_candlesticks" if meta.data_tier == "historical" else "kalshi.live_candlesticks"
        return endpoint, {"period_interval": granularity}
    return "polymarket.clob_prices_history", {"market": meta.yes_token_id, "fidelity": granularity}


def covered(entries: Iterable[dict[str, Any]], endpoint: str, static: dict[str, Any], window: Window) -> bool:
    """True when stored entries of ``endpoint`` with identical non-time params cover ``window`` without gaps."""
    lo_key, hi_key = PRICE_ENDPOINTS[endpoint]
    spans = []
    for e in entries:
        p = e.get("params") or {}
        if e.get("endpoint") != endpoint or any(p.get(k) != v for k, v in static.items()):
            continue
        if lo_key in p and hi_key in p:
            spans.append((int(p[lo_key]), int(p[hi_key])))
    need_lo, need_hi = int(window.start.timestamp()), int(window.end.timestamp())
    reach = need_lo  # covered up to here, starting from the window start
    for lo, hi in sorted(spans):
        if lo > reach:
            return False  # gap
        reach = max(reach, hi)
        if reach >= need_hi:
            return True
    return False


def _entries(raw_root: Path, venue: str, market_id: str) -> list[dict[str, Any]]:
    try:
        return load_manifest(raw_root, venue, market_id)
    except FileNotFoundError:
        return []


# --- collection -----------------------------------------------------------------------------------------


@dataclass
class CollectResult:
    venue: str
    market_id: str
    status: str  # "stored" | "skipped_existing" | "dry_run" | "error"
    window: Window | None = None
    points: int | None = None
    paths: list[str] = field(default_factory=list)
    error: str | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "market_id": self.market_id,
            "status": self.status,
            "window_start": self.window.start.isoformat() if self.window else None,
            "window_end": self.window.end.isoformat() if self.window else None,
            "points": self.points,
            "paths": self.paths,
            "error": self.error,
        }


def collect_market(
    venue: str,
    market_id: str,
    *,
    provider: KalshiProvider | PolymarketProvider,
    raw_root: Path = DEFAULT_RAW_ROOT,
    reference_close: datetime | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    t_minus_days: int = DEFAULT_T_MINUS_DAYS,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    granularity: int = DEFAULT_GRANULARITY_MIN,
    min_lead_days: int = DEFAULT_MIN_LEAD_DAYS,
    dry_run: bool = False,
    check_venue_close: bool = True,
    extra_notes: dict[str, Any] | None = None,
) -> CollectResult:
    """Collect one market's price history for a pre-close window. Never stores metadata bodies."""
    if provider.venue != venue:
        raise MarketDataError(f"provider venue {provider.venue!r} != {venue!r}")
    if min_lead_days < LEAD_FLOOR_DAYS:
        raise MarketDataError(f"min_lead_days={min_lead_days} is below the {LEAD_FLOOR_DAYS}-day floor")
    if start is None and t_minus_days < LEAD_FLOOR_DAYS:
        raise MarketDataError(f"t_minus_days={t_minus_days} is below the {LEAD_FLOOR_DAYS}-day floor")
    meta = provider.get_market(market_id)  # in memory only; the raw body carries settlement fields
    if not meta.is_binary:
        raise MarketDataError(f"{venue} {market_id} is not a binary market (MVP collects binary only)")
    ref = reference_close or meta.close_time
    if ref is None:
        raise MarketDataError(f"{venue} {market_id}: no scheduled close; cannot enforce the pre-close lead")
    if (start is None) != (end is None):
        raise MarketDataError("give both start and end, or neither")
    window = explicit_window(start, end, ref) if start and end else t_minus_window(ref, t_minus_days, lookback_days)
    check_lead(window, min_lead_days)
    if check_venue_close and meta.close_time is not None:
        # The venue's own scheduled close must also be at least min_lead_days after the window end.
        check_lead(dataclasses.replace(window, reference_close=meta.close_time), min_lead_days,
                   label=f"the venue's own scheduled close {meta.close_time.isoformat()}")

    endpoint, static = _expected(venue, meta, granularity)
    if covered(_entries(raw_root, venue, meta.market_id), endpoint, static, window):
        return CollectResult(venue, meta.market_id, "skipped_existing", window)
    if dry_run:
        return CollectResult(venue, meta.market_id, "dry_run", window)

    responses = provider.fetch_history_raw(meta, window.start, window.end, granularity)
    quotes: list[RawQuote] = provider.parse_history(meta, responses, granularity)  # schema + conflict checks
    for resp in responses:
        leaked = find_outcome_keys(resp.body)
        if leaked:
            raise MarketDataError(f"{venue} {market_id}: history body has outcome keys {sorted(leaked)}; not stored")
    late = [q.ts for q in quotes if q.ts > window.end]
    if late:
        raise MarketDataError(f"{venue} {market_id}: venue returned points after window end ({max(late)}); not stored")

    notes: dict[str, Any] = {
        "collector": "scripts/collect_market_snapshots.py",
        **window.as_notes(),
        "venue_scheduled_close": meta.close_time.isoformat() if meta.close_time else None,
        "points_in_response_set": len(quotes),
        "min_lead_days": min_lead_days,
        "venue_close_check": "enforced" if check_venue_close else "DISABLED (--ignore-venue-close)",
    }
    if venue == "kalshi":
        notes["data_tier"] = meta.data_tier
        if meta.kalshi_tier_cutoff is not None:
            notes["kalshi_market_settled_cutoff"] = meta.kalshi_tier_cutoff.isoformat()
    notes.update(extra_notes or {})
    paths = [
        str(store_raw(raw_root, venue, meta.market_id, dataclasses.replace(r, extra=notes)).relative_to(raw_root))
        for r in responses
    ]
    return CollectResult(venue, meta.market_id, "stored", window, points=len(quotes), paths=paths)


# --- offline availability report ------------------------------------------------------------------------


def entry_quotes(raw_root: Path, venue: str, market_id: str, e: dict[str, Any]) -> list[RawQuote]:
    """Parse one stored price-history manifest entry from its saved bytes (offline)."""
    ep = e.get("endpoint")
    if ep not in PRICE_ENDPOINTS:
        return []
    body = (Path(raw_root) / e["path"]).read_bytes()
    collected_at = parse_iso_utc(e["collected_at"])
    p = e["params"]
    if venue == "kalshi":
        return parse_candlesticks(
            body,
            ticker=market_id,
            tier="historical" if ep == "kalshi.historical_candlesticks" else "live",
            source_url=e["url"],
            collected_at=collected_at,
            period_interval=int(p["period_interval"]),
        )
    return parse_prices_history(
        body,
        market_id=market_id,
        token_id=str(p["market"]),
        source_url=e["url"],
        collected_at=collected_at,
        fidelity_minutes=int(p["fidelity"]) if p.get("fidelity") else None,
    )


def stored_quotes(raw_root: Path, venue: str, market_id: str) -> list[RawQuote]:
    """Parse every stored price-history response for a market (offline, from saved bytes)."""
    return [q for e in _entries(raw_root, venue, market_id) for q in entry_quotes(raw_root, venue, market_id, e)]


def availability(
    raw_root: Path,
    venue: str,
    market_id: str,
    as_of: datetime,
    max_staleness: timedelta = DEFAULT_MAX_STALENESS,
) -> dict[str, Any]:
    """Is there a stored quote with ``as_of - max_staleness <= ts <= as_of``? Reports no price values."""
    if not _entries(raw_root, venue, market_id):
        return {"status": NOT_AVAILABLE, "reason": "no snapshot collected", "points": 0}
    raw = stored_quotes(raw_root, venue, market_id)
    # Same observation can appear in overlapping snapshots; keep the first per timestamp.
    by_ts: dict[datetime, RawQuote] = {}
    for q in raw:
        by_ts.setdefault(q.ts, q)
    norm = normalize_quotes(by_ts[t] for t in sorted(by_ts))
    q = select_quote(norm, as_of, max_staleness)
    if q is None:
        hours = int(max_staleness.total_seconds() // 3600)
        if not raw:
            reason = "venue returned no price points in the window"
        elif not norm:
            reason = f"venue returned {len(by_ts)} observations, none priced (no two-sided book and no trade)"
        else:
            reason = f"no priced observation in the {hours}h before as_of"
        return {"status": NOT_AVAILABLE, "reason": reason, "points": len(norm)}
    return {"status": "AVAILABLE", "quote_ts": q.ts.isoformat(), "quote_kind": q.quote_kind, "points": len(norm)}


# --- plan -----------------------------------------------------------------------------------------------------


def load_plan(path: Path) -> dict[str, Any]:
    plan = json.loads(Path(path).read_text("utf-8"))
    leaked = find_outcome_keys(json.dumps(plan).encode())
    if leaked:
        raise MarketDataError(f"plan {path} contains outcome keys {sorted(leaked)}")
    return plan


def iter_plan_pairs(plan: dict[str, Any]):
    for g in plan["groups"]:
        for p in g.get("pairs", []):
            yield g, p


def run_plan(
    plan: dict[str, Any],
    *,
    client: httpx.Client,
    raw_root: Path = DEFAULT_RAW_ROOT,
    only: str | None = None,
    dry_run: bool = False,
    pause_s: float = 0.2,
    sleep: Callable[[float], None] = time.sleep,
) -> list[CollectResult]:
    rule = plan["window_rule"]
    providers = {v: make_provider(v, client) for v in ("kalshi", "polymarket")}
    results: list[CollectResult] = []
    for g, p in iter_plan_pairs(plan):
        if only and only not in g["group"]:
            continue
        ref = parse_iso_utc(p["reference_close"])
        for venue in ("kalshi", "polymarket"):
            mid = p[venue]["market_id"]
            try:
                r = collect_market(
                    venue,
                    mid,
                    provider=providers[venue],
                    raw_root=raw_root,
                    reference_close=ref,
                    t_minus_days=rule["t_minus_days"],
                    lookback_days=rule["lookback_days"],
                    granularity=rule["granularity_minutes"],
                    min_lead_days=rule["min_lead_days"],
                    dry_run=dry_run,
                    extra_notes={"plan_group": g["group"], "plan_leg": p["leg"]},
                )
            except (MarketDataError, httpx.HTTPError) as exc:
                r = CollectResult(venue, mid, "error", error=f"{type(exc).__name__}: {exc}")
            results.append(r)
            print(json.dumps(r.summary()), flush=True)
            sleep(pause_s)
    return results


def report_rows(plan: dict[str, Any], raw_root: Path = DEFAULT_RAW_ROOT) -> list[dict[str, Any]]:
    """Per pair and venue: T-minus availability from stored snapshots only (no network)."""
    t_minus = timedelta(days=plan["window_rule"]["t_minus_days"])
    rows = []
    for g, p in iter_plan_pairs(plan):
        as_of = parse_iso_utc(p["reference_close"]) - t_minus
        row = {"group": g["group"], "leg": p["leg"], "as_of": as_of.isoformat()}
        for venue in ("kalshi", "polymarket"):
            row[venue] = {"market_id": p[venue]["market_id"],
                          **availability(raw_root, venue, p[venue]["market_id"], as_of)}
        rows.append(row)
    return rows


# --- CLI --------------------------------------------------------------------------------------------------------


def _dt(s: str) -> datetime:
    dt = parse_iso_utc(s)
    if dt is None:
        raise argparse.ArgumentTypeError(f"not an ISO-8601 UTC timestamp: {s!r}")
    return dt


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("market", help="collect one market")
    m.add_argument("--venue", choices=("kalshi", "polymarket"), required=True)
    m.add_argument("--market-id", required=True, help="Kalshi ticker or Polymarket Gamma market id")
    m.add_argument("--reference-close", type=_dt, help="defaults to the market's scheduled close")
    m.add_argument("--start", type=_dt)
    m.add_argument("--end", type=_dt)
    m.add_argument("--t-minus-days", type=int, default=DEFAULT_T_MINUS_DAYS, help=f"floor {LEAD_FLOOR_DAYS}")
    m.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    m.add_argument("--granularity", type=int, default=DEFAULT_GRANULARITY_MIN, help="minutes")
    m.add_argument("--min-lead-days", type=int, default=DEFAULT_MIN_LEAD_DAYS, help=f"floor {LEAD_FLOOR_DAYS}")
    m.add_argument("--ignore-venue-close", action="store_true",
                   help="only enforce the lead against --reference-close (venue close metadata known to be wrong)")
    m.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("plan", help="collect every pair in the candidate plan")
    p.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    p.add_argument("--only", help="substring of a group name")
    p.add_argument("--dry-run", action="store_true")

    r = sub.add_parser("report", help="offline T-minus availability from stored snapshots")
    r.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    return ap


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "report":
        for row in report_rows(load_plan(args.plan), args.raw_root):
            print(json.dumps(row))
        return 0
    with make_client(transport) as client:
        if args.cmd == "market":
            try:
                r = collect_market(
                    args.venue,
                    args.market_id,
                    provider=make_provider(args.venue, client),
                    raw_root=args.raw_root,
                    reference_close=args.reference_close,
                    start=args.start,
                    end=args.end,
                    t_minus_days=args.t_minus_days,
                    lookback_days=args.lookback_days,
                    granularity=args.granularity,
                    min_lead_days=args.min_lead_days,
                    dry_run=args.dry_run,
                    check_venue_close=not args.ignore_venue_close,
                )
            except (MarketDataError, httpx.HTTPError) as exc:
                print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}))
                return 1
            print(json.dumps(r.summary()))
            return 0
        results = run_plan(load_plan(args.plan), client=client, raw_root=args.raw_root, only=args.only,
                           dry_run=args.dry_run)
        return 1 if any(r.status == "error" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
