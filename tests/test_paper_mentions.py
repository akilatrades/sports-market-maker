"""live/paper_mentions.py with a fake Kalshi (no network, no orders)."""

import ast
import json
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
    assert seen["KXNFLMENTION"] == {
        "open": 3, "posted": 1, "two_sided": 3, "in_window": 1,
        "hours_to_expiry_min": 2.0, "hours_to_expiry_median": 5.0,
    }  # fmt: skip
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


def test_the_game_day_watcher_starts_the_paper_test():
    root = Path(__file__).resolve().parents[1]
    watcher = (root / ".github/workflows/player-pool-page.yml").read_text()
    assert "gh workflow run paper-mentions.yml" in watcher
    flow = (root / ".github/workflows/paper-mentions.yml").read_text()
    assert "workflow_dispatch:" in flow and "--due" in flow


def test_discover_pages_through_open_events_and_keeps_matches():
    pages = {
        "": {"events": [{"series_ticker": "KXNFLMENTION"}, {"series_ticker": "KXNBAGAME"}],
             "cursor": "p2"},
        "p2": {"events": [{"series_ticker": "KXNFLGAMEMENTION"}, {"series_ticker": None}],
               "cursor": ""},
    }  # fmt: skip
    asked = []

    def get_json(path, params):
        assert path == "/events" and params["status"] == "open"
        asked.append(params.get("cursor", ""))
        return pages[params.get("cursor", "")]

    assert P.discover(get_json) == {"KXNFLMENTION", "KXNFLGAMEMENTION"}
    assert asked == ["", "p2"]


def test_main_adds_found_series_and_reports_them(tmp_path, monkeypatch):
    import kalshi.api as api

    k = Kalshi()
    k.listed = {"KXNEWMENTION": [market("KXNEWMENTION-26NOV24-A", 5)]}
    monkeypatch.setattr(api, "fetch_markets", k.fetch_markets)
    monkeypatch.setattr(api, "fetch_trades", k.fetch_trades)
    monkeypatch.setattr(api, "fetch_market", k.fetch_market)
    monkeypatch.setattr(
        api,
        "get_json",
        lambda path, params: {"events": [{"series_ticker": "KXNEWMENTION"}]},
    )
    monkeypatch.setattr(
        P, "datetime", type("D", (), {"now": staticmethod(lambda tz: NOW)})
    )
    P.main([], out=tmp_path)
    card = json.loads((tmp_path / "scorecard.json").read_text())
    assert card["series_added_since_plan"] == ["KXNEWMENTION"]
    assert card["series_checked"] == len(P.SERIES) + 1
    assert pd.read_csv(tmp_path / "orders.csv").ticker.tolist() == [
        "KXNEWMENTION-26NOV24-A"
    ]
    assert (tmp_path / "last_run.txt").exists()


def test_racing_uses_its_own_folder_series_and_filter():
    from live import paper_racing as R

    assert R.OUT != P.OUT and len(R.SERIES) == 31
    assert R.is_racing("KXNASCARRACE") and R.is_racing("KXF1POLE")
    assert not R.is_racing("KXNCAAF1HWINNER") and not R.is_racing("KXTFF1LIGGAME")
    text = (Path(__file__).resolve().parents[1] / "live/paper_racing.py").read_text()
    imported = {
        n.module for n in ast.walk(ast.parse(text)) if isinstance(n, ast.ImportFrom)
    }
    assert imported == {"pathlib", "live"}  # no order code, no client


def test_the_job_runs_both_paper_tests_and_commits_both_folders():
    flow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/paper-mentions.yml"
    ).read_text()
    assert (
        "python -m live.paper_racing --due" in flow
        and "python -m live.paper_racing\n" in flow
    )
    assert "git add -A outputs/paper_mentions outputs/paper_racing" in flow


def test_racing_judges_at_20_events_mentions_at_40():
    from live import paper_racing as R

    rows = [{"ticker": f"T{i}", "event_ticker": f"E{i % 25}", "status": "settled",
             "filled_contracts": 1, "profit": 0.05 if i % 3 else -0.02} for i in range(420)]  # fmt: skip
    ledger = pd.DataFrame(rows)
    assert P.verdict(ledger)["state"] == "collecting"  # 25 events < 40
    assert P.verdict(ledger, R.PASS_EVENTS)["state"] == "pass"


def test_sports_talk_finds_renamed_mention_series():
    events = [
        ("KXNFLANNOUNCERS", "What will the announcers say during DAL vs KC?"),
        ("KXNFLGAME", "Dallas at Kansas City"),
        ("KXEARNINGSMENTIONNVDA", "What will NVIDIA say on its earnings call?"),
        ("KXNCAAFWORDS", "Which word will be said on the broadcast?"),
    ]
    assert P.sports_talk(events) == ["KXNCAAFWORDS", "KXNFLANNOUNCERS"]
    assert P.discover(None, events=events) == {"KXEARNINGSMENTIONNVDA"}


def test_why_not_explains_markets_outside_the_window():
    far = [
        market("KXEARNINGSMENTIONNVDA-26DEC01-A", 70),
        market("X-B", 30, bid="0", ask="0.1"),
    ]
    why = P.why_not(far, NOW)
    assert why == {"two_sided": 1, "in_window": 0, "hours_to_expiry_min": 30.0,
                   "hours_to_expiry_median": 70.0}  # fmt: skip
