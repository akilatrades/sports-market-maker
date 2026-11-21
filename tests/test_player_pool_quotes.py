"""Kalshi quotes for the player-pool page: read-only, and it knows when to stop."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from research import player_pool_quotes as Q

NOW = datetime(2026, 11, 21, 23, 0, tzinfo=UTC)


def markets(*rows):
    columns = ["ticker", "yes_bid_dollars", "yes_ask_dollars", "occurrence_datetime"]
    return pd.DataFrame(rows, columns=columns)


def test_quotes_are_bid_and_ask_in_dollars_by_ticker():
    frame = markets(
        ("KXNBAPTS-26NOV21BOSNYK-BOSJTATUM0-25", 0.46, 0.47, "2026-11-22T03:00:00Z"),
        (
            "KXNBAREB-26NOV21BOSNYK-BOSJTATUM0-8",
            "0.3100",
            "0.3300",
            "2026-11-22T03:00:00Z",
        ),
    )
    out = Q.quote_file(frame, NOW)
    assert out["updated_utc"] == "2026-11-21T23:00:00+00:00"
    assert out["quotes"] == {
        "KXNBAPTS-26NOV21BOSNYK-BOSJTATUM0-25": [0.46, 0.47],
        "KXNBAREB-26NOV21BOSNYK-BOSJTATUM0-8": [0.31, 0.33],
    }
    json.dumps(out, allow_nan=False)  # raises on NaN


def test_an_empty_side_of_the_book_is_null_not_a_price():
    frame = markets(
        ("A", 0.0, 0.05, "2026-11-22T03:00:00Z"),  # no bid
        ("B", 0.99, 1.0, "2026-11-22T03:00:00Z"),  # no ask
        ("C", None, float("nan"), "2026-11-22T03:00:00Z"),
        ("", 0.5, 0.6, "2026-11-22T03:00:00Z"),  # no ticker: left out
    )
    quotes = Q.quote_file(frame, NOW)["quotes"]
    assert quotes == {"A": [None, 0.05], "B": [0.99, None], "C": [None, None]}


def test_it_stops_when_no_listed_game_is_still_ahead():
    # Kalshi dates a prop about three hours after its game tips off.
    tips_in_an_hour = markets(("A", 0.4, 0.5, "2026-11-22T03:00:00Z"))
    tipped_an_hour_ago = markets(("A", 0.4, 0.5, "2026-11-22T01:00:00Z"))
    assert Q.games_ahead(tips_in_an_hour, NOW) is True
    assert Q.games_ahead(tipped_an_hour_ago, NOW) is False
    assert Q.games_ahead(pd.concat([tips_in_an_hour, tipped_an_hour_ago]), NOW) is True
    assert Q.games_ahead(markets(), NOW) is False
    assert Q.games_ahead(markets(("A", 0.4, 0.5, "not a time")), NOW) is False


def test_one_pass_writes_the_file_and_reports_whether_to_continue(
    tmp_path, monkeypatch
):
    listed = markets(("A", 0.4, 0.5, "2099-01-01T00:00:00Z"))
    for frame, status in ((listed, 0), (markets(), Q.NO_GAMES_AHEAD)):
        out = tmp_path / f"quotes-{status}.json"
        monkeypatch.setattr(Q, "snapshot", lambda series, now=None, frame=frame: frame)
        monkeypatch.setattr("sys.argv", ["player_pool_quotes", "--out", str(out)])
        try:
            Q.main()
        except SystemExit as stop:
            assert stop.code == status
        else:
            raise AssertionError("main() should end with an exit status")
        assert set(json.loads(out.read_text())) == {"updated_utc", "quotes"}


def test_it_only_reads_public_market_data():
    source = Path(Q.__file__).read_text("utf-8")
    assert "from kalshi.api import snapshot" in source
    for forbidden in (
        "kalshi.trading",
        "portfolio",
        "orders",
        "KALSHI_KEY",
        "PRIVATE_KEY",
    ):
        assert forbidden not in source.replace("no orders", ""), forbidden
