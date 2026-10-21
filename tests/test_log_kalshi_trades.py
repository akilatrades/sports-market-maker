"""Public trade-print logger: which markets, which time window, what is saved."""

from datetime import date

import pandas as pd
import pytest

from live import log_kalshi_trades as log


def snapshot(folder, name, rows):
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["ticker", "occurrence_datetime", "title"]).to_csv(
        folder / name, index=False, compression="gzip"
    )


def test_game_date_comes_from_the_ticker():
    assert log.game_date("KXNBAPTS-26OCT21ATLORL-ATLJJOHNSON1-10") == date(2026, 10, 21)
    assert log.game_date("KXNBAREB-27JAN03BOSNYK-X-5") == date(2027, 1, 3)
    assert log.game_date("KXNBAPTS-BAD") is None
    assert log.game_date("nonsense") is None
    assert log.season_of(date(2026, 10, 21)) == 2027
    assert log.season_of(date(2027, 3, 1)) == 2027


@pytest.fixture
def snapshots(tmp_path, monkeypatch):
    monkeypatch.setattr(log, "OUT", tmp_path)
    season = tmp_path / "2027"
    snapshot(
        season,
        "2026-10-21T1700Z.csv.gz",
        [
            ("KXNBAPTS-26OCT21ATLORL-A-10", "2026-10-22T02:00:00Z", "x"),
            ("KXNBAPTS-26OCT22CLEPHI-B-10", "2026-10-23T02:00:00Z", "y"),  # tomorrow
        ],
    )
    snapshot(
        season,
        "2026-10-21T2300Z.csv.gz",
        [
            ("KXNBAPTS-26OCT21ATLORL-A-10", "2026-10-22T02:30:00Z", "x"),  # moved later
            ("KXNBAREB-26OCT21ATLORL-C-5", "2026-10-22T02:00:00Z", "z"),
        ],
    )
    return tmp_path


def test_night_markets_and_windows(snapshots):
    windows = log.night_markets(date(2026, 10, 21))
    assert sorted(windows) == [
        "KXNBAPTS-26OCT21ATLORL-A-10",
        "KXNBAREB-26OCT21ATLORL-C-5",
    ]
    start, end = windows["KXNBAPTS-26OCT21ATLORL-A-10"]
    assert end == int(pd.Timestamp("2026-10-22T02:30:00Z").timestamp())
    assert start == int(
        pd.Timestamp("2026-10-21T14:00:00Z").timestamp()
    )  # 12 h before 02:00


def test_saves_public_trades_only(snapshots):
    calls = []

    def fake(ticker, min_ts, max_ts, historical):
        calls.append((ticker, historical))
        if historical:
            return []
        return [
            {
                "ticker": ticker,
                "created_time": "2026-10-21T20:00:00Z",
                "yes_price": 0.45,
                "count": 3.0,
                "taker_outcome_side": "yes",
                "is_block_trade": False,
            }
        ]

    def markets(path, params):
        if path != "/markets":
            return {}
        event = params["event_ticker"]
        return {
            "markets": [
                {"ticker": f"{event}-A-10", "event_ticker": event, "result": "no"},
                {"ticker": f"{event}-C-5", "event_ticker": event, "result": "yes"},
                {"ticker": "NOT-WANTED", "event_ticker": event, "result": "yes"},
            ]
        }

    log.main(["--night", "2026-10-21"], fetch_trades=fake, get=markets)
    results = pd.read_csv(snapshots / "2027/results/2026-10-21.csv.gz")
    assert list(results.columns) == log.RESULT_COLUMNS
    assert dict(zip(results.ticker, results.result)) == {
        "KXNBAPTS-26OCT21ATLORL-A-10": "no",
        "KXNBAREB-26OCT21ATLORL-C-5": "yes",
    }  # only the night's markets, one request per game event
    saved = pd.read_csv(snapshots / "2027/trades/2026-10-21.csv.gz")
    assert list(saved.columns) == log.COLUMNS
    assert sorted(saved.ticker) == [
        "KXNBAPTS-26OCT21ATLORL-A-10",
        "KXNBAREB-26OCT21ATLORL-C-5",
    ]


def test_empty_live_answer_falls_back_to_the_historical_store(snapshots):
    asked = []

    def fake(ticker, min_ts, max_ts, historical):
        asked.append(historical)
        return [] if not historical else [{"ticker": ticker, "count": 1}]

    rows = log.fetch("T", (0, 1), fake)
    assert asked == [False, True] and rows == [{"ticker": "T", "count": 1}]


def test_many_failures_save_nothing(snapshots):
    def broken(*args, **kwargs):
        raise OSError("down")

    with pytest.raises(SystemExit):
        log.main(["--night", "2026-10-21"], fetch_trades=broken)
    assert not (snapshots / "2027/trades").exists()
