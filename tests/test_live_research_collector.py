import unittest
from research.live_kalshi_collector import normalize_market, best_bid_levels
from research.research_monitor import summarize, price_to_dollars


class CollectorTests(unittest.TestCase):
    def test_normalize_market_uses_collection_time(self):
        row = normalize_market(
            {
                "ticker": "KXNBA-X",
                "event_ticker": "KXNBA-E",
                "yes_bid_dollars": "0.43",
                "volume_fp": "22",
            },
            "2026-11-26T12:00:00+00:00",
        )
        self.assertEqual(row["market_id"], "KXNBA-X")
        self.assertEqual(row["event_id"], "KXNBA-E")
        self.assertEqual(row["yes_bid_dollars"], "0.43")
        self.assertIn("collector_observation_time", row["snapshot_time_semantics"])

    def test_book_legacy_and_dollar_fields(self):
        self.assertEqual(
            best_bid_levels({"yes": [[40, 10]], "no": [[50, 5]]})["yes"], [[40, 10]]
        )
        self.assertEqual(
            best_bid_levels({"yes_dollars": [["0.4", 10]], "no_dollars": [["0.5", 5]]})[
                "no"
            ],
            [["0.5", 5]],
        )

    def test_legacy_one_cent_price_conversion(self):
        self.assertEqual(price_to_dollars(1), 0.01)
        self.assertEqual(price_to_dollars("0.43"), 0.43)

    def test_public_print_not_own_fill_semantics_in_dashboard(self):
        counts, markets, _ = summarize(
            [
                {"market_id": "M", "event_type": "public_trade"},
                {"market_id": "M", "event_type": "fill"},
            ]
        )
        self.assertEqual(counts["public_trade"], 1)
        self.assertEqual(markets["M"]["private_fill_count"], 1)


if __name__ == "__main__":
    unittest.main()


def test_select_markets_by_hours_to_tip_off():
    from datetime import datetime, timedelta, timezone

    from research.live_kalshi_collector import select_markets

    now = datetime(2026, 11, 28, 18, 0, tzinfo=timezone.utc)

    def m(ticker, hours_to_tip, vol=1):
        occ = now + timedelta(hours=hours_to_tip + 3)  # occurrence ~ end of game
        return {
            "ticker": ticker,
            "occurrence_datetime": occ.isoformat(),
            "volume_fp": vol,
        }

    markets = [
        m("FAR", 20, 999),
        m("SOON", 2),
        m("EDGE", 7),
        m("LIVE", -1),
        m("DONE", -5),
    ]
    assert [x["ticker"] for x in select_markets(markets, now, 5, within_hours=7)] == [
        "SOON",
        "EDGE",
    ]
    got = select_markets(markets, now, 5, within_hours=7, in_game_hours=3)
    assert [x["ticker"] for x in got] == ["LIVE", "SOON", "EDGE"]
    assert [x["ticker"] for x in select_markets(markets, now, 1)] == [
        "FAR"
    ]  # original rule


def test_daily_output_files():
    from datetime import datetime, timezone

    from research.live_kalshi_collector import dated

    when = datetime(2026, 11, 28, 1, tzinfo=timezone.utc)
    assert (
        dated("nba/live_events_{date}.jsonl", when)
        == "nba/live_events_2026-11-28.jsonl"
    )
    assert (
        dated("data/research/live_events.jsonl", when)
        == "data/research/live_events.jsonl"
    )


def test_a_cycle_pages_selects_and_writes(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timedelta, timezone

    import research.live_kalshi_collector as C

    occ = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    pages = {
        "": {"markets": [{"ticker": "A", "occurrence_datetime": occ}], "cursor": "p2"},
        "p2": {"markets": [{"ticker": "B", "occurrence_datetime": occ}], "cursor": ""},
    }

    def fake(path, params=None, timeout=12):
        if path == "/markets":
            return pages[params.get("cursor", "")]
        if path.endswith("/orderbook"):
            return {"orderbook": {"yes": [[40, 5]], "no": [[55, 3]]}}
        return {
            "trades": [{"trade_id": "t1", "yes_price_dollars": "0.41", "count_fp": "2"}]
        }

    monkeypatch.setattr(C, "get_json", fake)
    out = str(tmp_path / "ev_{date}.jsonl")
    stats = C.collect_once(
        ["KXNBAPTS"], out, 100, 100, set(), within_hours=7, workers=4
    )
    assert stats["markets"] == 2 and stats["books"] == 2 and stats["public_trades"] == 1
    files = list(tmp_path.glob("ev_*.jsonl"))
    assert len(files) == 1 and len(files[0].read_text().splitlines()) == 5
    assert all(
        "order" not in json.loads(line).get("event_type", "")
        for line in files[0].read_text().splitlines()
    )


def test_event_time_rules():
    from datetime import datetime, timezone

    from research.live_kalshi_collector import event_time

    m = {
        "occurrence_datetime": "2026-11-28T20:00:00Z",
        "close_time": "2026-11-28T18:00:00Z",
    }
    assert event_time(m) == datetime(2026, 11, 28, 17, tzinfo=timezone.utc)  # NBA rule
    assert event_time(m, "earliest", 0) == datetime(
        2026, 11, 28, 18, tzinfo=timezone.utc
    )
    assert event_time(
        {"close_time": "2026-11-28T18:00:00Z"}, "earliest", 0
    ) == datetime(2026, 11, 28, 18, tzinfo=timezone.utc)
    assert event_time({}, "earliest", 0) is None


def test_category_markets_page_and_keep_only_the_category(monkeypatch):
    from datetime import datetime, timezone

    import research.live_kalshi_collector as C

    calls = []
    pages = {
        "": {
            "markets": [
                {"ticker": "A", "event_ticker": "KXTRUMPMENTION-26NOV28"},
                {"ticker": "X", "event_ticker": "KXNBAPTS-26NOV28LALBOS"},
            ],
            "cursor": "p2",
        },
        "p2": {
            "markets": [{"ticker": "B", "event_ticker": "KXEARNINGSMENTIONTSLA-26"}]
        },
    }

    def fake(path, params=None, timeout=12):
        calls.append((path, dict(params)))
        return pages[params.get("cursor", "")]

    monkeypatch.setattr(C, "get_json", fake)
    now = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)
    got = C.category_markets({"KXTRUMPMENTION", "KXEARNINGSMENTIONTSLA"}, now, 48)
    assert [m["ticker"] for m in got] == ["A", "B"]
    first = calls[0][1]
    assert (
        first["status"] == "open"
        and first["max_close_ts"] - first["min_close_ts"] == 48 * 3600
    )


def test_category_source_refreshes_on_schedule(monkeypatch):
    from datetime import datetime, timedelta, timezone

    import research.live_kalshi_collector as C

    now = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)
    soon = (now + timedelta(hours=3)).isoformat()
    later = (now + timedelta(hours=30)).isoformat()
    counts = {"series": 0, "markets": 0}

    def series(category):
        counts["series"] += 1
        return {"KXTRUMPMENTION"}

    def markets(s, n, h):
        counts["markets"] += 1
        return [
            {"ticker": "SOON", "event_ticker": "KXTRUMPMENTION-1", "close_time": soon},
            {
                "ticker": "LATER",
                "event_ticker": "KXTRUMPMENTION-2",
                "close_time": later,
            },
        ]

    monkeypatch.setattr(C, "category_series", series)
    monkeypatch.setattr(C, "category_markets", markets)
    src = C.CategorySource("Mentions", 7, 0, 200, "earliest", 0, refresh_minutes=30)
    got, fresh = src.markets(now)
    assert [m["ticker"] for m in got] == ["SOON"] and fresh
    got, fresh = src.markets(now + timedelta(minutes=10))
    assert not fresh and counts == {"series": 1, "markets": 1}
    got, fresh = src.markets(now + timedelta(hours=4))  # past the event, rediscovered
    assert fresh and got == [] and counts == {"series": 2, "markets": 2}


def test_a_category_cycle_reads_only_books_and_trades(tmp_path, monkeypatch):
    import json

    import research.live_kalshi_collector as C

    seen_paths = []

    def fake(path, params=None, timeout=12):
        seen_paths.append(path)
        if path.endswith("/orderbook"):
            return {
                "orderbook": {
                    "yes_dollars": [["0.40", "5"]],
                    "no_dollars": [["0.55", "3"]],
                }
            }
        return {"trades": []}

    monkeypatch.setattr(C, "get_json", fake)
    out = str(tmp_path / "m_{date}.jsonl")
    stats = C.collect_once(
        [], out, 200, 100, set(), within_hours=7,
        chosen_markets=[{"ticker": "A", "event_ticker": "E"}], write_market_snapshots=False,
    )  # fmt: skip
    assert stats["markets"] == 0 and stats["books"] == 1
    assert "/markets" not in seen_paths  # no listing on a non-refresh cycle
    lines = [
        json.loads(x) for x in next(tmp_path.glob("m_*.jsonl")).read_text().splitlines()
    ]
    assert [x["event_type"] for x in lines] == ["book_snapshot"]
