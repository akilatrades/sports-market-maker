"""live/paper_ladder.py with a fake Kalshi (no network, no orders)."""

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from live import paper_ladder as P

NOW = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


def ladder(hours_to_occurrence=8, mids=(0.90, 0.75, 0.58, 0.30, 0.12)):
    occ = (NOW + timedelta(hours=hours_to_occurrence)).isoformat()
    out = []
    for strike, mid in zip((9.5, 14.5, 19.5, 24.5, 29.5), mids):
        out.append({"ticker": f"KXNBAREB-26NOV27NYKBOS-NYKJBRUNSON11-{int(strike + 0.5)}",
                    "floor_strike": strike, "occurrence_datetime": occ,
                    "yes_bid_dollars": f"{mid - 0.02:.2f}", "yes_ask_dollars": f"{mid + 0.02:.2f}"})  # fmt: skip
    return out


class Kalshi:
    def __init__(self, markets):
        self.markets, self.trades, self.results = markets, [], {}

    def fetch_markets(self, series, status="open", historical=False):
        return self.markets if series == "KXNBAREB" else []

    def fetch_trades(self, ticker, start, end):
        return [t for t in self.trades if t["ticker"] == ticker]

    def fetch_market(self, ticker):
        return {"ticker": ticker, "result": self.results.get(ticker, "")}


def test_a_kinked_strike_rests_fills_and_settles():
    k = Kalshi(ladder())
    empty = pd.DataFrame(columns=P.COLUMNS)
    ledger, seen = P.run(
        NOW,
        k.fetch_markets,
        k.fetch_trades,
        k.fetch_market,
        empty,
        sleep=lambda s: None,
    )
    outlier = ledger[ledger.group == "outlier"]
    assert outlier.ticker.tolist() == ["KXNBAREB-26NOV27NYKBOS-NYKJBRUNSON11-20"]
    row = outlier.iloc[0]
    assert (
        row.price == 0.41 and row.yes_level == 0.59
    )  # NO bid 40c + 1c inside a 4c spread
    assert row.cancel_ts - row.placed_ts == 3600
    assert seen["KXNBAREB"]["posted_outlier"] == 1
    # A YES buyer lifts 60c for 7 contracts during the hour; the market settles NO.
    k.trades = [{"ticker": row.ticker, "created_time": (NOW + timedelta(minutes=10)).isoformat(),
                 "yes_price": 0.60, "count": 7.0, "taker_outcome_side": "yes"}]  # fmt: skip
    k.results[row.ticker] = "no"
    later = NOW + timedelta(hours=1, minutes=5)
    ledger, _ = P.run(
        later,
        k.fetch_markets,
        k.fetch_trades,
        k.fetch_market,
        ledger,
        sleep=lambda s: None,
    )
    done = ledger[ledger.ticker == row.ticker].iloc[0]
    assert (
        done.status == "settled"
        and float(done.traded) == 7.0
        and float(done.profit) > 0.55
    )
    assert (ledger.ticker == row.ticker).sum() == 1  # one order per market, ever
    v = P.verdict(ledger)
    assert v["state"] == "collecting" and v["primary_queue_5"]["fills"] == 1


def test_no_order_once_tip_off_is_within_the_hour():
    k = Kalshi(ladder(hours_to_occurrence=3.5))  # tip-off 30 minutes away
    empty = pd.DataFrame(columns=P.COLUMNS)
    ledger, _ = P.run(
        NOW,
        k.fetch_markets,
        k.fetch_trades,
        k.fetch_market,
        empty,
        sleep=lambda s: None,
    )
    assert ledger.empty


def test_the_bar():
    rows = [{"group": "outlier", "status": "settled", "traded": 6, "game": f"G{i % 70}",
             "profit": 0.10 if i % 2 else -0.02, "ticker": f"T{i}"} for i in range(320)]  # fmt: skip
    assert P.verdict(pd.DataFrame(rows))["state"] == "pass"
    for r in rows:
        r["profit"] = -0.08
    assert P.verdict(pd.DataFrame(rows))["state"] == "stop (early)"


def test_paper_only_and_in_the_hourly_job():
    tree = ast.parse((ROOT / "live/paper_ladder.py").read_text())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported <= {
        "datetime",
        "pathlib",
        "kalshi.maker",
        "kalshi.stats",
        "kalshi.api",
    }
    flow = (ROOT / ".github/workflows/paper-mentions.yml").read_text()
    assert (
        "python -m live.paper_ladder --due" in flow and "outputs/paper_ladder" in flow
    )
