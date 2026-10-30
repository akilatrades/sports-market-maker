"""Shadow recorder: Kalshi spread-maker quotes beside sportsbook fair prices.

RESEARCH_LOG.md, 2026-10-30, "Spread maker v5". Read-only and record-only:
public Kalshi market listings (no key) and The Odds API head-to-head prices
(ODDS_API_KEY; one request per sport per run, about 5 credits). Rows go to a
CSV outside the repository (raw odds are licensed and never committed). No
order is placed, cancelled or sized from this.

    ODDS_API_KEY=... python -m research.spread_book_shadow record --out /home/trader/spread-book-shadow
"""

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from kalshi import api as kalshi_api
from kalshi import books
from kalshi import spread_books as sb
from live.prod_spread_auto import quote_prices, ticker_start

FIELDS = [
    "recorded_utc",
    "series",
    "ticker",
    "team",
    "start_utc",
    "yes_bid",
    "yes_ask",
    "our_yes",
    "our_no",
    "fair_yes",
    "books",
    "edge_yes",
    "edge_no",
    "reason",
]


def _cents(value):
    try:
        return round(float(value) * 100)
    except (TypeError, ValueError):
        return None


def rows_for(series, markets, events, now):
    out = []
    for m in markets:
        start = ticker_start(m.get("event_ticker", ""))
        bid, ask = _cents(m.get("yes_bid_dollars")), _cents(m.get("yes_ask_dollars"))
        prices = quote_prices(bid, ask)
        if start is None or prices is None or start <= now:
            continue
        got, why = sb.fair_yes(m, start, events)
        row = {
            "recorded_utc": now.isoformat(),
            "series": series,
            "ticker": m.get("ticker"),
            "team": m.get("yes_sub_title"),
            "start_utc": start.isoformat(),
            "yes_bid": bid,
            "yes_ask": ask,
            "our_yes": prices[0],
            "our_no": prices[1],
            "reason": why,
        }
        if got:
            row.update(
                fair_yes=got["p"],
                books=got["books"],
                edge_yes=round(got["p"] - prices[0] / 100, 4),
                edge_no=round((1 - got["p"]) - prices[1] / 100, 4),
            )
        out.append(row)
    return out


def record(out_dir):
    now = datetime.now(UTC)
    key = books.api_key()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"shadow_{now:%Y-%m-%d}.csv"
    new = not path.exists()
    counts = {}
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for series, sport in sb.SPORT_FOR_SERIES.items():
            markets = kalshi_api.fetch_markets(series, status="open") or []
            if not markets:
                counts[series] = 0
                continue
            events, _ = sb.fetch_h2h(key, sport)
            rows = rows_for(series, markets, events, now)
            w.writerows(rows)
            counts[series] = len(rows)
    print(json.dumps({"recorded_utc": now.isoformat(), "rows": counts}))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["record"])
    p.add_argument("--out", required=True, help="folder outside the repository")
    args = p.parse_args(argv)
    if Path(args.out).resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise SystemExit("Write raw odds outside the repository")
    record(args.out)


if __name__ == "__main__":
    main()
