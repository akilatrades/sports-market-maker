"""Download other sports' Kalshi player-prop ladders (RESEARCH_LOG.md,
2026-11-26, "Ladders, deeper", part B). Public market data only.

    python -m research.backfill_ladders --discover      # series to fetch, as JSON
    python -m research.backfill_ladders --series KXNFLRECYDS --minutes 300

For one series: settled markets from --start whose ticker ends in a plain
number; hourly candles from 14 hours before to 1 hour after each market's
occurrence time; trades from 14 to 3 hours before it. Resumable: finished
markets are skipped, and the run stops cleanly after --minutes. Prints
counts only.

Writes data/kalshi_history_ladders/{markets,candles,trades}_<series>.parquet.
"""

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kalshi.api import candles, fetch_markets, get_json, trades

OUT = Path("data/kalshi_history_ladders")
EXCLUDED = {"KXNBAPTS", "KXNBAREB", "KXNBAAST", "KXNBA3PT"}
STAT = re.compile(
    r"(PTS|REB|AST|3PT|PASSYDS|RECYDS|RSHYDS|RUSHYDS|REC|RECS|TDS|ANYTD|HITS|KS|TB|HR|"
    r"SOG|SHOTS|GOALS?|SAVES|BLK|STL|PRA|OUTS|RBI|RUNS)$"
)
NUMBER = re.compile(r"-\d+(\.\d+)?$")
BEFORE_HOURS, AFTER_HOURS, TRADES_UNTIL_HOURS = 14, 1, 3
FIELDS = ["ticker", "event_ticker", "result", "floor_strike", "strike_type", "yes_sub_title",
          "occurrence_datetime", "close_time", "expected_expiration_time", "volume_fp"]  # fmt: skip


def discover(get=get_json):
    """Sports series named after a player stat, other than the NBA four."""
    reply = get("/series", {"category": "Sports"}) or {}
    names = {str(s.get("ticker")) for s in reply.get("series") or [] if s.get("ticker")}
    return sorted(
        n for n in names if STAT.search(n.removeprefix("KX")) and n not in EXCLUDED
    )


def list_markets(series, start, fetch=fetch_markets):
    rows = {}
    for historical in (True, False):
        for m in fetch(
            series, status=None if historical else "settled", historical=historical
        ):
            if m.get("ticker"):
                rows[m["ticker"]] = {f: m.get(f) for f in FIELDS}
    frame = pd.DataFrame(list(rows.values()), columns=FIELDS)
    if frame.empty:
        return frame
    frame["series"] = series
    anchor = anchor_time(frame)
    keep = (
        frame.ticker.str.contains(NUMBER)
        & frame.result.isin(["yes", "no"])
        & (pd.to_numeric(frame.volume_fp, errors="coerce").fillna(0) > 0)
        & (anchor >= pd.Timestamp(start, tz="UTC"))
    )
    return frame[keep].reset_index(drop=True)


def anchor_time(frame):
    def utc(c):
        return pd.to_datetime(frame[c], utc=True, format="ISO8601", errors="coerce")

    return (
        utc("occurrence_datetime")
        .fillna(utc("expected_expiration_time"))
        .fillna(utc("close_time"))
    )


def save(frame, path):
    tmp = path.with_suffix(".tmp")
    frame.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)


def fetch_one(ticker, anchor, get_candles=candles, get_trades=trades):
    """Candles and trades for one market. Markets settled before Kalshi's
    historical cutoff are under /historical; newer ones are only on the live
    endpoints, so an empty historical answer falls back to the live one."""
    a = int(anchor.timestamp())
    lo, hi, t_hi = (
        a - BEFORE_HOURS * 3600,
        a + AFTER_HOURS * 3600,
        a - TRADES_UNTIL_HOURS * 3600,
    )
    got_c = get_candles(ticker, lo, hi) or get_candles(ticker, lo, hi, historical=False)
    got_t = get_trades(ticker, lo, t_hi) or get_trades(
        ticker, lo, t_hi, historical=False
    )
    return got_c or [], got_t or []


def run(series, start, minutes, workers):
    OUT.mkdir(parents=True, exist_ok=True)
    paths = {k: OUT / f"{k}_{series}.parquet" for k in ("markets", "candles", "trades")}
    if paths["markets"].exists():
        markets = pd.read_parquet(paths["markets"])
    else:
        markets = list_markets(series, start)
        save(markets, paths["markets"])
    print(f"{series}: {len(markets)} settled ladder markets since {start}")
    done_path = OUT / f"done_{series}.txt"
    done = set(done_path.read_text().split()) if done_path.exists() else set()
    todo = markets[~markets.ticker.isin(done)].copy()
    todo["anchor"] = anchor_time(todo)
    todo = todo[todo.anchor.notna()]
    deadline = time.monotonic() + 60 * minutes
    got_c, got_t, failed = [], [], 0
    with ThreadPoolExecutor(workers) as pool:
        it = iter(zip(todo.ticker, todo.anchor))
        pending = {}
        for _ in range(workers * 3):
            job = next(it, None)
            if job:
                pending[pool.submit(fetch_one, *job)] = job[0]
        while pending:
            for future in as_completed(list(pending)):
                ticker = pending.pop(future)
                try:
                    c, t = future.result()
                    got_c += c
                    got_t += t
                    done.add(ticker)
                except (OSError, ValueError, KeyError):
                    failed += 1
                if time.monotonic() < deadline:
                    job = next(it, None)
                    if job:
                        pending[pool.submit(fetch_one, *job)] = job[0]
                break
    for key, rows in (("candles", got_c), ("trades", got_t)):
        new = pd.DataFrame(rows)
        if paths[key].exists():
            new = pd.concat([pd.read_parquet(paths[key]), new], ignore_index=True)
        if len(new):
            subset = ["ticker", "end_ts"] if key == "candles" else None
            save(new.drop_duplicates(subset), paths[key])
    done_path.write_text("\n".join(sorted(done)) + "\n")
    remaining = len(markets) - len(done)
    print(
        f"::notice::{series}: done {len(done)}, remaining {remaining}, failed {failed}"
    )
    return remaining


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--discover", action="store_true")
    p.add_argument("--series")
    p.add_argument("--start", default="2025-09-01")
    p.add_argument("--minutes", type=float, default=300)
    p.add_argument("--workers", type=int, default=12)
    a = p.parse_args(argv)
    if a.discover:
        print(json.dumps(discover()))
        return 0
    run(a.series, a.start, a.minutes, a.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
