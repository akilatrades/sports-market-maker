"""live/paper_mentions.py with a fake Kalshi (no network, no orders)."""

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from live import paper_mentions as P

NOW = datetime(2026, 11, 24, 18, 0, tzinfo=UTC)


def market(ticker, hours, bid="0.30", ask="0.36"):
    return {"ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0], "title": "Will X be said?",
            "expected_expiration_time": (NOW + timedelta(hours=hours)).isoformat(),
            "yes_bid_dollars": bid, "yes_ask_dollars": ask}  # fmt: skip


class Kalshi:
    def __init__(self):
        self.listed = {
            "KXNFLMENTION": [
                market("KXNFLMENTION-26NOV24-A", 5),
                market("KXNFLMENTION-26NOV24-B", 9),  # too early
                market("KXNFLMENTION-26NOV24-C", 2),
            ]
        }  # too late
        self.trades, self.results = [], {}

    def fetch_markets(self, series, status="open", historical=False):
        return self.listed.get(series, [])

    def fetch_trades(self, ticker, start, end):
        return [t for t in self.trades if t["ticker"] == ticker]

    def fetch_market(self, ticker):
        return {"ticker": ticker, "result": self.results.get(ticker, "")}


def test_a_full_cycle_rests_fills_and_settles(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "LEDGER", tmp_path / "orders.csv")
    k = Kalshi()
    ledger, seen = P.run(
        NOW, k.fetch_markets, k.fetch_trades, k.fetch_market, sleep=lambda s: None
    )
    assert ledger.ticker.tolist() == ["KXNFLMENTION-26NOV24-A"]  # only the 4-7h window
    row = ledger.iloc[0]
    assert row.side == "no" and row.price == 0.65  # NO bid 64c + 1c
    assert row.cancel_ts - row.placed_ts == 3600  # rests one hour
    assert seen["KXNFLMENTION"] == {"open": 3, "posted": 1}
    ledger.to_csv(P.LEDGER, index=False)
    # An hour later: a YES buyer traded through at 35c (NO 65c), then it settles NO.
    later = NOW + timedelta(hours=1, minutes=5)
    k.trades = [
        {
            "ticker": "KXNFLMENTION-26NOV24-A",
            "created_time": (NOW + timedelta(minutes=20)).isoformat(),
            "yes_price": 0.35,
            "count": 50.0,
            "taker_outcome_side": "yes",
            "is_block_trade": False,
        }
    ]
    k.results["KXNFLMENTION-26NOV24-A"] = "no"
    k.listed = {}
    ledger, _ = P.run(
        later, k.fetch_markets, k.fetch_trades, k.fetch_market, sleep=lambda s: None
    )
    done = ledger[ledger.ticker == "KXNFLMENTION-26NOV24-A"].iloc[0]
    assert done.status == "settled" and done.filled_contracts >= 1
    assert float(done.profit) > 0
    v = P.verdict(ledger)
    assert (
        v["state"] == "collecting"
        and v["contracts"] >= 1
        and v["cents_per_contract"] > 0
    )


def test_the_bar_and_the_early_stop():
    rows = []
    for i in range(80):
        rows.append({"status": "settled", "filled_contracts": 5, "profit": 5 * (0.35 if i % 3 else -0.65),
                     "event_ticker": f"E{i}"})  # fmt: skip
    v = P.verdict(pd.DataFrame(rows))
    assert (
        v["contracts"] == 400
        and v["events"] == 80
        and v["state"] in ("pass", "inconclusive")
    )
    losing = pd.DataFrame([{"status": "settled", "filled_contracts": 10, "profit": -1.0, "event_ticker": f"E{i}"}
                           for i in range(25)])  # fmt: skip
    assert P.verdict(losing)["state"] == "stop (early)"
    assert (
        P.verdict(
            pd.DataFrame(
                columns=["status", "filled_contracts", "profit", "event_ticker"]
            )
        )["state"]
        == "waiting"
    )


def test_due_waits_50_minutes(tmp_path):
    path = tmp_path / "last.txt"
    assert P.due(NOW, path)
    path.write_text((NOW - timedelta(minutes=30)).isoformat())
    assert not P.due(NOW, path)
    path.write_text((NOW - timedelta(minutes=55)).isoformat())
    assert P.due(NOW, path)


def test_series_are_the_105_mention_series_and_nothing_trades():
    assert len(P.SERIES) == 105 == len(set(P.SERIES))
    assert all(s.endswith(("MENTION", "MENTIONB")) or "MENTION" in s for s in P.SERIES)
    tree = ast.parse(Path(P.__file__).read_text())
    names = {a.name if isinstance(n, ast.Import) else f"{n.module}.{a.name}"
             for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}  # fmt: skip
    assert {
        "kalshi.api.fetch_market",
        "kalshi.api.fetch_markets",
        "kalshi.api.fetch_trades",
    } <= names
    assert not any(
        "client" in n or "order" in n.lower() and "paper" not in n for n in names
    )
