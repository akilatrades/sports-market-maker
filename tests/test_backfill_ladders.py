"""Other sports' ladder download: series choice and market filter (no network)."""

from pathlib import Path

from research import backfill_ladders as B


def test_discover_keeps_player_stat_series_except_the_nba_four():
    reply = {"series": [{"ticker": t} for t in (
        "KXNFLRECYDS", "KXNHLSOG", "KXMLBKS", "KXWNBAPTS", "KXNBAPTS", "KXNFLGAME", "KXNBASPREAD",
    )]}  # fmt: skip
    assert B.discover(lambda path, params: reply) == [
        "KXMLBKS",
        "KXNFLRECYDS",
        "KXNHLSOG",
        "KXWNBAPTS",
    ]


def test_markets_keep_settled_numbered_ladders_since_the_start():
    def fetch(series, status=None, historical=False):
        base = {
            "result": "no",
            "volume_fp": "5",
            "occurrence_datetime": "2025-11-02T21:00:00Z",
        }
        if historical:
            return [{**base, "ticker": "KXNFLRECYDS-25NOV02X-PLAYER-50"},
                    {**base, "ticker": "KXNFLRECYDS-25AUG02X-PLAYER-60", "occurrence_datetime": "2025-08-02T21:00:00Z"},
                    {**base, "ticker": "KXNFLRECYDS-25NOV02X-PLAYER-T50"},
                    {**base, "ticker": "KXNFLRECYDS-25NOV02X-PLAYER-70", "result": "scalar"}]  # fmt: skip
        return [
            {
                **base,
                "ticker": "KXNFLRECYDS-26NOV22X-PLAYER-40",
                "occurrence_datetime": "2026-11-22T21:00:00Z",
            }
        ]

    got = B.list_markets("KXNFLRECYDS", "2025-09-01", fetch=fetch)
    assert sorted(got.ticker) == [
        "KXNFLRECYDS-25NOV02X-PLAYER-50",
        "KXNFLRECYDS-26NOV22X-PLAYER-40",
    ]


def test_the_download_job_is_read_only_and_resumable():
    text = (
        Path(__file__).resolve().parents[1] / "research/backfill_ladders.py"
    ).read_text()
    assert "/portfolio" not in text and "create_order" not in text
    flow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/backfill-ladders.yml"
    ).read_text()
    assert "--discover" in flow and "data/kalshi_history_ladders" in flow


def test_ladder_why_marks_round_strikes_and_hours_to_tip(monkeypatch):
    import pandas as pd

    from research import ladder_why as W

    r = pd.DataFrame({"game": ["26JAN05NYKBOS"] * 2, "end_ts": [1_767_650_400] * 2,
                      "floor_strike": [19.5, 22.5], "yes_bid": [0.50, 0.40], "yes_ask": [0.54, 0.44],
                      "mid": [0.52, 0.42], "resid": [0.04, 0.0]})  # fmt: skip
    monkeypatch.setattr(
        W.L, "tips", lambda: pd.Series({"26JAN05|BOS": "2026-01-06T00:00:00Z"})
    )
    got = W.with_tip(r)
    assert got.round5.tolist() == [True, False] and got.round10.tolist() == [
        True,
        False,
    ]
    assert got.hours_to_tip.round(1).tolist() == [2.0, 2.0]
    assert got.bid_above_curve.tolist() == [True, False]


def test_recent_markets_fall_back_to_the_live_endpoints():
    """26 November 2026: every NBA market since 20 October came back empty,
    because only /historical was asked."""
    import pandas as pd

    calls = []

    def fake(kind):
        def get(ticker, lo, hi, historical=True):
            calls.append((kind, historical))
            return [] if historical else [{"ticker": ticker, "kind": kind}]

        return get

    c, t = B.fetch_one(
        "KXNBAPTS-26NOV25AB-X-20",
        pd.Timestamp("2026-11-26T06:00:00Z"),
        get_candles=fake("c"),
        get_trades=fake("t"),
    )
    assert c == [{"ticker": "KXNBAPTS-26NOV25AB-X-20", "kind": "c"}] and len(t) == 1
    assert calls == [("c", True), ("c", False), ("t", True), ("t", False)]


def test_old_markets_use_historical_only():
    import pandas as pd

    calls = []

    def get(ticker, lo, hi, historical=True):
        calls.append(historical)
        return [{"x": 1}]

    B.fetch_one("KXNFLREC-25NOV02X-P-5", pd.Timestamp("2025-11-02T21:00:00Z"), get, get)
    assert calls == [True, True]
