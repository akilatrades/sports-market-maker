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


def test_category_markets_list_each_series_and_keep_closes_in_the_horizon(monkeypatch):
    from datetime import datetime, timedelta, timezone

    import research.live_kalshi_collector as C

    now = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)
    iso = lambda h: (now + timedelta(hours=h)).isoformat()  # noqa: E731
    listed = {
        "KXTRUMPMENTION": [
            {"ticker": "A", "close_time": iso(5)},
            {"ticker": "FAR", "close_time": iso(80)},
        ],
        "KXEARNINGSMENTIONTSLA": [{"ticker": "B", "close_time": iso(30)}],
    }
    calls = []

    def fake_list(series, limit=100, max_pages=20):
        calls.append(series)
        if series == "KXBROKEN":
            raise OSError("timeout")
        return listed.get(series, [])

    monkeypatch.setattr(C, "market_list", fake_list)
    got = C.category_markets(set(listed) | {"KXBROKEN"}, now, 48)
    assert sorted(m["ticker"] for m in got) == ["A", "B"]
    assert sorted(calls) == sorted(set(listed) | {"KXBROKEN"})


def test_category_source_refreshes_on_schedule(monkeypatch):
    from datetime import datetime, timedelta, timezone

    import research.live_kalshi_collector as C

    now = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)
    calls = []

    def discover(category):
        calls.append(category)
        return [
            {"ticker": "SOON", "close_time": (now + timedelta(hours=3)).isoformat()},
            {
                "ticker": "LATER",
                "close_time": (now + timedelta(hours=80)).isoformat(),
                "occurrence_datetime": (now + timedelta(hours=7, minutes=5)).isoformat(),
            },
        ]

    monkeypatch.setattr(C, "discover_category", discover)
    src = C.CategorySource("Mentions", 7, 0, 200, "earliest", 0, refresh_minutes=30)
    got, fresh = src.markets(now)
    assert [m["ticker"] for m in got] == ["SOON"] and fresh
    got, fresh = src.markets(now + timedelta(minutes=10))
    assert [m["ticker"] for m in got] == ["SOON", "LATER"] and fresh
    assert calls == ["Mentions"]
    got, fresh = src.markets(now + timedelta(minutes=20))
    assert not fresh
    got, fresh = src.markets(now + timedelta(hours=4))
    assert fresh and [m["ticker"] for m in got] == ["LATER"]
    assert calls == ["Mentions", "Mentions"]


def test_discover_category_uses_events_and_preserves_distant_closes(monkeypatch):
    import research.live_kalshi_collector as C

    calls = []

    def fake(path, params=None):
        calls.append((path, params))
        if path == "/series":
            return {"series": [{"ticker": "S"}]}
        if path == "/events" and not params.get("cursor"):
            return {
                "events": [
                    {"event_ticker": "E", "series_ticker": "S"},
                    {"event_ticker": "OTHER", "category": "Sports"},
                ],
                "cursor": "next",
            }
        if path == "/events":
            return {"events": [{"event_ticker": "E", "category": "Mentions"}]}
        assert params == {"event_ticker": "E"}
        return {
            "markets": [
                {"ticker": "A", "status": "active", "close_time": "2027-01-01T00:00:00Z"},
                {"ticker": "B", "status": "closed"},
            ]
        }

    monkeypatch.setattr(C, "get_json", fake)
    assert [m["ticker"] for m in C.discover_category("Mentions")] == ["A"]
    assert [path for path, _ in calls] == ["/series", "/events", "/events", "/markets"]


def test_discover_category_rejects_incomplete_pagination(monkeypatch):
    import pytest

    import research.live_kalshi_collector as C

    monkeypatch.setattr(C, "category_series", lambda category: {"S"})
    monkeypatch.setattr(
        C, "get_json", lambda path, params: {"events": [], "cursor": "next"}
    )
    with pytest.raises(RuntimeError, match="pagination incomplete"):
        C.discover_category("Mentions", max_pages=1)


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


def test_get_json_backs_off_on_429_then_gives_up(monkeypatch):
    import io
    from urllib.error import HTTPError

    import pytest

    import research.live_kalshi_collector as C

    answers = [429, 429, 200]
    sleeps = []

    def fake_open(req, timeout=12):
        code = answers.pop(0)
        if code == 429:
            raise HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
        return io.BytesIO(b'{"ok": 1}')

    monkeypatch.setattr(C, "urlopen", fake_open)
    monkeypatch.setattr(C.time, "sleep", sleeps.append)
    monkeypatch.setattr(C, "_wait_turn", lambda: None)
    monkeypatch.delenv("KALSHI_SHARED_LIMIT_FILE", raising=False)
    assert C.get_json("/x") == {"ok": 1} and sleeps == [5.0, 10.0]
    sleeps.clear()
    answers[:] = [429] * 4
    with pytest.raises(HTTPError):
        C.get_json("/x")
    assert sleeps == [5.0, 10.0, 20.0]
    answers[:] = [500]

    def fail_500(req, timeout=12):
        raise HTTPError(req.full_url, 500, "boom", {}, None)

    monkeypatch.setattr(C, "urlopen", fail_500)
    with pytest.raises(HTTPError):  # other errors are not retried
        C.get_json("/x")


def test_series_mode_uses_the_event_time_rule(tmp_path, monkeypatch):
    """28 November 2026: --event-time was ignored in series mode, so Kalshi's
    15-minute crypto markets (occurrence = close + 5 min) were never chosen."""
    from datetime import datetime, timedelta, timezone

    import research.live_kalshi_collector as C

    now = datetime.now(timezone.utc)
    m = {
        "ticker": "KXBTC15M-X",
        "event_ticker": "KXBTC15M-X",
        "close_time": (now + timedelta(minutes=8)).isoformat(),
        "occurrence_datetime": (now + timedelta(minutes=13)).isoformat(),
    }

    def fake(path, params=None, timeout=12):
        if path == "/markets":
            return {"markets": [m]}
        if path.endswith("/orderbook"):
            return {
                "orderbook": {
                    "yes_dollars": [["0.86", "5"]],
                    "no_dollars": [["0.13", "5"]],
                }
            }
        return {"trades": []}

    monkeypatch.setattr(C, "get_json", fake)
    out = str(tmp_path / "c_{date}.jsonl")
    nba_rule = C.collect_once(
        ["KXBTC15M"], out, 8, 100, set(), within_hours=1, in_game_hours=0.5
    )
    assert nba_rule["books"] == 0  # occurrence - 3 h is long past
    earliest = C.collect_once(
        ["KXBTC15M"], out, 8, 100, set(), within_hours=1, in_game_hours=0.5,
        event_rule="earliest", event_offset_hours=0,
    )  # fmt: skip
    assert earliest["books"] == 1


def test_shared_slots_and_cooldown(tmp_path, monkeypatch):
    import research.live_kalshi_collector as C

    state = tmp_path / "rate-limit"
    clock = [100.0]
    monkeypatch.setenv("KALSHI_SHARED_LIMIT_FILE", str(state))
    monkeypatch.setenv("KALSHI_SHARED_RATE", "2")
    monkeypatch.setattr(C.time, "monotonic", lambda: clock[0])

    def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(C.time, "sleep", sleep)
    C._shared_slot()
    assert float(state.read_text()) == 100.5
    C._shared_slot()
    assert clock[0] == 100.5
    C._shared_slot(5.0)
    assert float(state.read_text()) == 105.5
    C._shared_slot()
    assert clock[0] == 105.5
    assert float(state.read_text()) == 106.0
