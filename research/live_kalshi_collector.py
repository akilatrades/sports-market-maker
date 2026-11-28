"""Read-only Kalshi market data collector (sports series, or a whole category).

Polls public REST market, orderbook and trade endpoints and writes normalized JSONL.
No API keys, order endpoints, or trading logic are used. Requires explicit series tickers
so the user controls scope. Current books are observations, not exchange-timestamped
historical books; source_timestamp is collection time for snapshots.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from research.recorder import append_records

BASE = "https://external-api.kalshi.com/trade-api/v2"
USER_AGENT = "sports-market-maker-research-collector/1.0"
MAX_PER_SECOND = 10.0  # shared across worker threads; well under public limits
_LOCK = threading.Lock()
_NEXT = [0.0]
_RATE = [MAX_PER_SECOND]  # --max-per-second may lower it


def _wait_turn() -> None:
    with _LOCK:
        now = time.monotonic()
        wait = _NEXT[0] - now
        _NEXT[0] = max(now, _NEXT[0]) + 1.0 / _RATE[0]
    if wait > 0:
        time.sleep(wait)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


RETRIES_429 = 3  # Kalshi answers 429 (too many requests) under load: back off


def get_json(
    path: str, params: dict[str, Any] | None = None, timeout: int = 12
) -> dict:
    query = urlencode(params or {}, doseq=True)
    url = f"{BASE}{path}" + (f"?{query}" if query else "")
    for attempt in range(RETRIES_429 + 1):
        _wait_turn()
        req = Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        try:
            with urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code != 429 or attempt == RETRIES_429:
                raise
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError("unreachable")


def market_list(series: str, limit: int = 100, max_pages: int = 20) -> list[dict]:
    """Open markets in a series, following Kalshi's cursor (up to max_pages)."""
    markets, cursor = [], ""
    for _ in range(max_pages):
        params = {"series_ticker": series, "status": "open", "limit": limit}
        if cursor:
            params["cursor"] = cursor
        payload = get_json("/markets", params)
        markets += payload.get("markets", [])
        cursor = payload.get("cursor") or ""
        if not cursor:
            break
    return markets


def tip_estimate(market: dict, offset_hours: float = 3.0) -> datetime | None:
    """Kalshi sets the occurrence time near the END of an NBA game; tip-off is
    about three hours earlier (the backtests' rule)."""
    for field in ("occurrence_datetime", "expected_expiration_time"):
        text = market.get(field)
        if text:
            try:
                return datetime.fromisoformat(
                    str(text).replace("Z", "+00:00")
                ) - timedelta(hours=offset_hours)
            except ValueError:
                continue
    return None


def _parse(text: Any) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def event_time(
    market: dict, rule: str = "occurrence", offset_hours: float = 3.0
) -> datetime | None:
    """When the thing the market is about happens.

    "occurrence": the occurrence time (else expected expiration) minus
    offset_hours: NBA, where Kalshi sets it near the END of the game.
    "earliest": the earlier of the occurrence time and the close, minus
    offset_hours: categories like Mentions, where the market closes when the
    event ends (RESEARCH_LOG.md in akilatrades/kalshi-maker, 2026-11-27).
    """
    if rule == "occurrence":
        return tip_estimate(market, offset_hours)
    if rule != "earliest":
        raise ValueError(f"unknown event-time rule {rule!r}")
    times = [
        t
        for t in (
            _parse(market.get("occurrence_datetime")),
            _parse(market.get("close_time")),
        )
        if t is not None
    ]
    return min(times) - timedelta(hours=offset_hours) if times else None


def select_markets(
    markets: list[dict],
    now: datetime,
    cap: int,
    within_hours: float | None = None,
    in_game_hours: float = 0.0,
    rule: str = "occurrence",
    offset_hours: float = 3.0,
) -> list[dict]:
    """Without within_hours: the cap highest-volume markets (the original rule).
    With it: every market from within_hours before tip-off to in_game_hours
    after, nearest tip-off first, up to cap."""
    if within_hours is None:

        def vol(m):
            try:
                return float(m.get("volume_fp", m.get("volume", 0)) or 0)
            except (ValueError, TypeError):
                return 0

        return sorted(markets, key=vol, reverse=True)[:cap]
    keep = []
    for m in markets:
        tip = event_time(m, rule, offset_hours)
        if tip is None:
            continue
        hours = (tip - now).total_seconds() / 3600
        if -in_game_hours <= hours <= within_hours:
            keep.append((abs(hours), m))
    keep.sort(key=lambda x: x[0])
    return [m for _, m in keep[:cap]]


def category_series(category: str, max_pages: int = 20) -> set[str]:
    """Every series ticker Kalshi lists under a category (e.g. "Mentions")."""
    out, cursor = set(), ""
    for _ in range(max_pages):
        params: dict[str, Any] = {"category": category, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        payload = get_json("/series", params)
        out |= {s["ticker"] for s in payload.get("series", []) if s.get("ticker")}
        cursor = payload.get("cursor") or ""
        if not cursor:
            break
    return out


def category_markets(
    series: set[str], now: datetime, horizon_hours: float, max_pages: int = 5
) -> list[dict]:
    """Open markets of every series in `series` that close within
    horizon_hours, listed series by series. (One unfiltered /markets listing
    does not work: tens of thousands of combo markets crowd out the rest.)
    A series that fails to list is skipped and retried at the next refresh."""
    until = now + timedelta(hours=horizon_hours)
    out = []
    for s in sorted(series):
        try:
            markets = market_list(s, limit=1000, max_pages=max_pages)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] series {s} markets fetch failed: {exc}")
            continue
        for m in markets:
            close = _parse(m.get("close_time"))
            if close is not None and now <= close <= until:
                out.append(m)
    return out


class CategorySource:
    """The markets to record for a category, rediscovered every refresh_minutes
    (series and markets) so each cycle only reads order books and trades."""

    def __init__(self, category, within_hours, in_game_hours, cap, rule, offset_hours,
                 refresh_minutes=30, horizon_hours=48):  # fmt: skip
        self.category, self.within, self.in_game, self.cap = (
            category,
            within_hours,
            in_game_hours,
            cap,
        )
        self.rule, self.offset = rule, offset_hours
        self.refresh = timedelta(minutes=refresh_minutes)
        self.horizon = horizon_hours
        self.chosen: list[dict] = []
        self.last: datetime | None = None

    def due(self, now: datetime) -> bool:
        return self.last is None or now - self.last >= self.refresh

    def markets(self, now: datetime) -> tuple[list[dict], bool]:
        """(markets to record, whether they were just rediscovered)."""
        if not self.due(now):
            keep = select_markets(
                self.chosen,
                now,
                self.cap,
                self.within,
                self.in_game,
                self.rule,
                self.offset,
            )
            return keep, False
        series = category_series(self.category)
        found = category_markets(series, now, self.horizon)
        self.chosen = select_markets(
            found, now, self.cap, self.within, self.in_game, self.rule, self.offset
        )
        self.last = now
        return self.chosen, True


def best_bid_levels(orderbook: dict) -> dict:
    # Supports the legacy integer-cent and newer fixed-point dollar fields.
    return {
        "yes": orderbook.get("yes_dollars", orderbook.get("yes", [])) or [],
        "no": orderbook.get("no_dollars", orderbook.get("no", [])) or [],
    }


def normalize_market(market: dict, observed_at: str) -> dict:
    ticker = market.get("ticker", "")
    event_ticker = market.get("event_ticker", ticker)
    return {
        "event_id": event_ticker,
        "market_id": ticker,
        "event_type": "market_snapshot",
        "source_timestamp": observed_at,
        "source": "kalshi_public_rest",
        "snapshot_time_semantics": "collector_observation_time; exchange snapshot timestamp not provided",
        "status": market.get("status"),
        "close_time": market.get("close_time"),
        "title": market.get("title"),
        "yes_bid_dollars": market.get("yes_bid_dollars", market.get("yes_bid")),
        "yes_ask_dollars": market.get("yes_ask_dollars", market.get("yes_ask")),
        "last_price_dollars": market.get(
            "last_price_dollars", market.get("last_price")
        ),
        "volume_fp": market.get("volume_fp", market.get("volume")),
        "open_interest_fp": market.get("open_interest_fp", market.get("open_interest")),
        "occurrence_datetime": market.get("occurrence_datetime"),
        "raw_ticker": ticker,
    }


def fetch_market_data(ticker: str, trade_limit: int, want_trades: bool) -> tuple:
    """(orderbook payload or exception, trades payload or exception)."""
    try:
        book = get_json(f"/markets/{ticker}/orderbook", {"depth": 10})
    except Exception as exc:  # noqa: BLE001 - reported by the caller
        book = exc
    trades: Any = {"trades": []}
    if want_trades:
        try:
            trades = get_json(
                "/markets/trades", {"ticker": ticker, "limit": trade_limit}
            )
        except Exception as exc:  # noqa: BLE001
            trades = exc
    return book, trades


def dated(output: str, when: datetime) -> str:
    """'data/nba/live_events_{date}.jsonl' -> one file per UTC day."""
    return output.replace("{date}", when.strftime("%Y-%m-%d"))


def collect_once(
    series_tickers: list[str],
    output: str,
    market_cap: int,
    trade_limit: int,
    seen_trade_ids: set[str],
    within_hours: float | None = None,
    in_game_hours: float = 0.0,
    workers: int = 1,
    want_trades: bool = True,
    chosen_markets: list[dict] | None = None,
    write_market_snapshots: bool = True,
    event_rule: str = "occurrence",
    event_offset_hours: float = 3.0,
) -> dict[str, int]:
    collected = 0
    markets_count = books_count = trades_count = errors = 0
    now = datetime.now(timezone.utc)
    path = dated(output, now)
    chosen = list(chosen_markets) if chosen_markets is not None else []
    for series in series_tickers if chosen_markets is None else []:
        try:
            markets = market_list(series, limit=min(max(market_cap * 3, 100), 1000))
            chosen += select_markets(
                markets,
                now,
                market_cap,
                within_hours,
                in_game_hours,
                event_rule,
                event_offset_hours,
            )
        except Exception as exc:
            print(f"[warn] series {series} markets fetch failed: {exc}")
            errors += 1
    chosen = [m for m in chosen if m.get("ticker")]
    with ThreadPoolExecutor(max(1, workers)) as pool:
        fetched = list(
            pool.map(
                lambda m: fetch_market_data(m["ticker"], trade_limit, want_trades),
                chosen,
            )
        )
    for market, (book_payload, trades_payload) in zip(chosen, fetched):
        ticker = market["ticker"]
        observed = now_iso()
        if write_market_snapshots:  # a stale listing is not re-written each minute
            try:
                collected += append_records(path, [normalize_market(market, observed)])
                markets_count += 1
            except Exception as exc:
                print(f"[warn] market record {ticker}: {exc}")
                errors += 1
        if isinstance(book_payload, Exception):
            print(f"[warn] orderbook {ticker}: {book_payload}")
            errors += 1
        else:
            book = book_payload.get("orderbook", book_payload.get("orderbook_fp", {}))
            levels = best_bid_levels(book)
            book_record = {
                "event_id": market.get("event_ticker", ticker),
                "market_id": ticker,
                "event_type": "book_snapshot",
                "source_timestamp": observed,
                "source": "kalshi_public_rest",
                "snapshot_time_semantics": "collector_observation_time; exchange snapshot timestamp not provided",
                "yes_bid_levels": levels["yes"],
                "no_bid_levels": levels["no"],
            }
            try:
                collected += append_records(path, [book_record])
                books_count += 1
            except Exception as exc:
                print(f"[warn] book record {ticker}: {exc}")
                errors += 1
        if isinstance(trades_payload, Exception):
            print(f"[warn] trades {ticker}: {trades_payload}")
            errors += 1
            continue
        for trade in trades_payload.get("trades", []):
            tid = str(trade.get("trade_id", trade.get("id", "")))
            if tid and tid in seen_trade_ids:
                continue
            if tid:
                seen_trade_ids.add(tid)
            rec = {
                "event_id": market.get("event_ticker", ticker),
                "market_id": ticker,
                "event_type": "public_trade",  # public tape, not personal fill
                "source_timestamp": trade.get("created_time") or observed,
                "observed_at": observed,
                "source": "kalshi_public_trade_tape",
                "trade_id": tid or None,
                "public_trade": True,
                "yes_price_dollars": trade.get(
                    "yes_price_dollars", trade.get("yes_price")
                ),
                "count_fp": trade.get("count_fp", trade.get("count")),
                "taker_outcome_side": trade.get("taker_outcome_side"),
            }
            try:
                collected += append_records(path, [rec])
                trades_count += 1
            except Exception as exc:
                print(f"[warn] trade record {ticker}: {exc}")
                errors += 1
    return {
        "records": collected,
        "markets": markets_count,
        "books": books_count,
        "public_trades": trades_count,
        "errors": errors,
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="Read-only Kalshi sports market recorder; no orders."
    )
    scope = p.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--series", help="Comma-separated Kalshi series tickers to record"
    )
    scope.add_argument(
        "--category",
        help='a Kalshi category (e.g. "Mentions"): its series and markets are '
        "rediscovered every --refresh-minutes",
    )
    p.add_argument(
        "--event-time",
        choices=["occurrence", "earliest"],
        default="occurrence",
        help="occurrence: occurrence time minus the offset (NBA); earliest: the "
        "earlier of occurrence and close, minus the offset",
    )
    p.add_argument("--event-offset-hours", type=float, default=3.0)
    p.add_argument("--refresh-minutes", type=float, default=30)
    p.add_argument(
        "--close-horizon-hours",
        type=float,
        default=48,
        help="category mode: look at open markets closing within this many hours",
    )
    p.add_argument("--max-per-second", type=float, default=MAX_PER_SECOND)
    p.add_argument("--output", default="data/research/live_events.jsonl")
    p.add_argument(
        "--interval", type=float, default=60, help="seconds between cycles (minimum 15)"
    )
    p.add_argument(
        "--max-markets",
        type=int,
        default=10,
        help="per-series cap; highest-volume open markets",
    )
    p.add_argument("--trade-limit", type=int, default=100)
    p.add_argument(
        "--within-hours",
        type=float,
        default=None,
        help="every market from this many hours before tip-off (instead of top volume)",
    )
    p.add_argument(
        "--in-game-hours",
        type=float,
        default=0.0,
        help="keep markets this long after tip-off",
    )
    p.add_argument("--workers", type=int, default=1, help="parallel requests (1-8)")
    p.add_argument(
        "--trades-every", type=int, default=1, help="fetch trades every Nth cycle"
    )
    p.add_argument("--once", action="store_true", help="run one cycle then exit")
    args = p.parse_args()
    series = [s.strip() for s in (args.series or "").split(",") if s.strip()]
    if args.series is not None and not series:
        p.error("at least one series ticker required")
    if args.category is not None and args.within_hours is None:
        p.error("--category needs --within-hours")
    if not 0.5 <= args.max_per_second <= MAX_PER_SECOND:
        p.error(f"--max-per-second must be 0.5..{MAX_PER_SECOND}")
    if args.refresh_minutes < 5:
        p.error("--refresh-minutes minimum is 5")
    _RATE[0] = args.max_per_second
    source = (
        CategorySource(
            args.category,
            args.within_hours,
            args.in_game_hours,
            args.max_markets,
            args.event_time,
            args.event_offset_hours,
            args.refresh_minutes,
            args.close_horizon_hours,
        )
        if args.category
        else None
    )
    if args.interval < 15:
        p.error("interval minimum is 15 seconds to reduce API load")
    top = 50 if args.within_hours is None else 400
    if args.max_markets < 1 or args.max_markets > top:
        p.error(f"--max-markets must be 1..{top}")
    if not 1 <= args.workers <= 8:
        p.error("--workers must be 1..8")
    if args.trade_limit < 1 or args.trade_limit > 1000:
        p.error("--trade-limit must be 1..1000")
    seen: set[str] = set()
    cycle = 0
    while True:
        started = time.monotonic()
        chosen, fresh = None, True
        if source is not None:
            try:
                chosen, fresh = source.markets(datetime.now(timezone.utc))
            except Exception as exc:  # keep the last list; try again next cycle
                print(f"[warn] {args.category} discovery failed: {exc}")
                chosen, fresh = source.chosen, False
                source.last = None
        stats = collect_once(
            series,
            args.output,
            args.max_markets,
            args.trade_limit,
            seen,
            within_hours=args.within_hours,
            in_game_hours=args.in_game_hours,
            workers=args.workers,
            want_trades=cycle % max(1, args.trades_every) == 0,
            chosen_markets=chosen,
            write_market_snapshots=fresh,
            event_rule=args.event_time,
            event_offset_hours=args.event_offset_hours,
        )
        cycle += 1
        if len(seen) > 300_000:  # bounded memory on a small server
            seen.clear()
        print(f"{now_iso()} cycle stats: {stats}")
        if args.once:
            break
        time.sleep(max(0.0, args.interval - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
