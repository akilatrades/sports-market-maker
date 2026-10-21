"""Save Kalshi's public trade prints and results for one night's NBA prop markets.

Public market data only: every trade anyone made, with no account, order or
position information. Used to measure how much trading happened at a price
while an order rested there, which says what share of it a resting order
really gets (the replay assumed it was always first in line).

The night's markets come from the price snapshots in data/kalshi/<season>/
(live/log_kalshi.py), by the game date in each ticker ("26OCT21" = 21 Oct).
For each market, trades from 12 hours before its scheduled occurrence time
to that time are fetched (pre-game resting covers at most the last 6 hours
before tip-off). Same columns as data/kalshi_history/trades_*.parquet.

Also saves each market's final result (public market data), so props the bot
did not trade can be scored too.

Writes data/kalshi/<season>/trades/<night>.csv.gz and
data/kalshi/<season>/results/<night>.csv.gz (season named by the year it
ends). Prints counts only.

Run: python -m live.log_kalshi_trades [--night YYYY-MM-DD]  (default: yesterday, Eastern)
"""

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from kalshi.api import get_json, trades

ET = ZoneInfo("America/New_York")
OUT = Path("data/kalshi")
RESULT_COLUMNS = [
    "ticker",
    "event_ticker",
    "status",
    "result",
    "settlement_value_dollars",
    "last_price_dollars",
    "volume_fp",
    "occurrence_datetime",
    "close_time",
]
COLUMNS = [
    "ticker",
    "created_time",
    "yes_price",
    "count",
    "taker_outcome_side",
    "is_block_trade",
]
HOURS_BEFORE = 12
MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "JAN",
            "FEB",
            "MAR",
            "APR",
            "MAY",
            "JUN",
            "JUL",
            "AUG",
            "SEP",
            "OCT",
            "NOV",
            "DEC",
        ],
        1,
    )
}


def season_of(day):
    return day.year + 1 if day.month >= 8 else day.year


def game_date(ticker):
    """'KXNBAPTS-26OCT21ATLORL-...' -> date(2026, 10, 21); None if unreadable."""
    parts = str(ticker).split("-")
    match = re.match(r"(\d\d)([A-Z]{3})(\d\d)", parts[1]) if len(parts) > 1 else None
    if not match or match.group(2) not in MONTHS:
        return None
    try:
        return datetime(
            2000 + int(match.group(1)), MONTHS[match.group(2)], int(match.group(3))
        ).date()
    except ValueError:
        return None


def night_markets(night, folder=None):
    """{ticker: (min_ts, max_ts)} for the night's markets seen in any snapshot."""
    folder = folder or OUT  # looked up at call time
    windows = {}
    snapshots = sorted((folder / str(season_of(night))).glob("*.csv.gz"))
    for path in snapshots:
        frame = pd.read_csv(
            path, usecols=["ticker", "occurrence_datetime"], low_memory=False
        )
        for ticker, occurs in zip(frame.ticker, frame.occurrence_datetime):
            if game_date(ticker) != night:
                continue
            end = pd.to_datetime(occurs, utc=True, errors="coerce")
            if pd.isna(end):
                continue
            span = (
                int((end - pd.Timedelta(hours=HOURS_BEFORE)).timestamp()),
                int(end.timestamp()),
            )
            old = windows.get(ticker)
            windows[ticker] = (
                span if old is None else (min(old[0], span[0]), max(old[1], span[1]))
            )
    return windows


def fetch(ticker, window, fetch_trades=trades):
    rows = fetch_trades(ticker, *window, historical=False)
    if not rows:  # older markets move to Kalshi's historical store
        rows = fetch_trades(ticker, *window, historical=True)
    return rows


def night_results(tickers, get=get_json):
    """Final status and result of each market, fetched one game event at a time."""
    wanted = set(tickers)
    events = sorted({"-".join(t.split("-")[:2]) for t in wanted})
    rows = []
    for event in events:
        for path in ("/markets", "/historical/markets"):
            found, cursor = [], ""
            while True:
                params = {"event_ticker": event, "limit": 1000}
                if cursor:
                    params["cursor"] = cursor
                page = get(path, params) or {}
                found += page.get("markets", [])
                cursor = page.get("cursor") or ""
                if not cursor or not page.get("markets"):
                    break
            if found:
                break
        rows += [
            {c: m.get(c) for c in RESULT_COLUMNS}
            for m in found
            if m.get("ticker") in wanted
        ]
    return pd.DataFrame(rows, columns=RESULT_COLUMNS)


def main(argv=None, fetch_trades=trades, get=get_json):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--night", help="YYYY-MM-DD (Eastern game date)")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    night = (
        datetime.strptime(args.night, "%Y-%m-%d").date()
        if args.night
        else (datetime.now(ET) - timedelta(days=1)).date()
    )
    markets = night_markets(night)
    if not markets:
        print(
            f"::notice::No NBA prop markets found in snapshots for {night}; nothing saved"
        )
        return
    rows, failed = [], 0
    with ThreadPoolExecutor(args.workers) as pool:
        futures = {
            pool.submit(fetch, t, w, fetch_trades): t for t, w in markets.items()
        }
        for future in futures:
            try:
                rows.extend(future.result())
            except (OSError, ValueError, KeyError):
                failed += 1
    if failed > 0.05 * len(markets):
        # A partial file would understate trading; fail and let a rerun fill it.
        print(f"::error::{failed} of {len(markets)} markets failed; nothing saved")
        sys.exit(1)
    frame = pd.DataFrame(rows, columns=COLUMNS).drop_duplicates()
    folder = OUT / str(season_of(night))
    path = folder / "trades" / f"{night}.csv.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.sort_values(["ticker", "created_time"]).to_csv(path, index=False)
    results = night_results(markets, get)
    path = folder / "results" / f"{night}.csv.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    results.sort_values("ticker").to_csv(path, index=False)
    settled = int(results.result.isin(["yes", "no"]).sum())
    print(
        f"::notice::{night}: {len(frame)} trades in {frame.ticker.nunique()} of "
        f"{len(markets)} markets ({failed} failed); results for {settled} settled"
    )


if __name__ == "__main__":
    main()
