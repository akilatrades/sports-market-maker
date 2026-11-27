"""Read-only Kalshi sports-market data collector.

Polls public REST market, orderbook and trade endpoints and writes normalized JSONL.
No API keys, order endpoints, or trading logic are used. Requires explicit series tickers
so the user controls scope. Current books are observations, not exchange-timestamped
historical books; source_timestamp is collection time for snapshots.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from research.recorder import append_records

BASE = "https://external-api.kalshi.com/trade-api/v2"
USER_AGENT = "sports-market-maker-research-collector/1.0"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_json(
    path: str, params: dict[str, Any] | None = None, timeout: int = 12
) -> dict:
    query = urlencode(params or {}, doseq=True)
    url = f"{BASE}{path}" + (f"?{query}" if query else "")
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def market_list(series: str, limit: int = 100) -> list[dict]:
    payload = get_json(
        "/markets", {"series_ticker": series, "status": "open", "limit": limit}
    )
    return payload.get("markets", [])


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
        "raw_ticker": ticker,
    }


def collect_once(
    series_tickers: list[str],
    output: str,
    market_cap: int,
    trade_limit: int,
    seen_trade_ids: set[str],
) -> dict[str, int]:
    collected = 0
    markets_count = books_count = trades_count = errors = 0
    for series in series_tickers:
        try:
            markets = market_list(series, limit=min(max(market_cap * 3, 100), 1000))

            # Prioritize highest-volume contracts where numeric volume is parseable.
            def vol(m):
                try:
                    return float(m.get("volume_fp", m.get("volume", 0)) or 0)
                except (ValueError, TypeError):
                    return 0

            markets = sorted(markets, key=vol, reverse=True)[:market_cap]
        except Exception as exc:
            print(f"[warn] series {series} markets fetch failed: {exc}")
            errors += 1
            continue
        for market in markets:
            ticker = market.get("ticker")
            if not ticker:
                continue
            observed = now_iso()
            try:
                rec = normalize_market(market, observed)
                collected += append_records(output, [rec])
                markets_count += 1
            except Exception as exc:
                print(f"[warn] market record {ticker}: {exc}")
                errors += 1
            try:
                book_payload = get_json(f"/markets/{ticker}/orderbook", {"depth": 10})
                book = book_payload.get(
                    "orderbook", book_payload.get("orderbook_fp", {})
                )
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
                collected += append_records(output, [book_record])
                books_count += 1
            except Exception as exc:
                print(f"[warn] orderbook {ticker}: {exc}")
                errors += 1
            try:
                trades_payload = get_json(
                    "/markets/trades", {"ticker": ticker, "limit": trade_limit}
                )
                trades = trades_payload.get("trades", [])
                for trade in trades:
                    tid = str(trade.get("trade_id", trade.get("id", "")))
                    if tid and tid in seen_trade_ids:
                        continue
                    if tid:
                        seen_trade_ids.add(tid)
                    trade_time = trade.get("created_time") or observed
                    rec = {
                        "event_id": market.get("event_ticker", ticker),
                        "market_id": ticker,
                        "event_type": "public_trade",  # public tape, not personal fill
                        "source_timestamp": trade_time,
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
                    collected += append_records(output, [rec])
                    trades_count += 1
            except Exception as exc:
                print(f"[warn] trades {ticker}: {exc}")
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
    p.add_argument(
        "--series",
        required=True,
        help="Comma-separated Kalshi series tickers to record",
    )
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
    p.add_argument("--once", action="store_true", help="run one cycle then exit")
    args = p.parse_args()
    series = [s.strip() for s in args.series.split(",") if s.strip()]
    if not series:
        p.error("at least one series ticker required")
    if args.interval < 15:
        p.error("interval minimum is 15 seconds to reduce API load")
    if args.max_markets < 1 or args.max_markets > 50:
        p.error("--max-markets must be 1..50")
    if args.trade_limit < 1 or args.trade_limit > 1000:
        p.error("--trade-limit must be 1..1000")
    seen: set[str] = set()
    while True:
        started = time.monotonic()
        stats = collect_once(
            series, args.output, args.max_markets, args.trade_limit, seen
        )
        print(f"{now_iso()} cycle stats: {stats}")
        if args.once:
            break
        time.sleep(max(0.0, args.interval - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
