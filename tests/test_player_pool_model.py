"""The stat model's prices for the player-pool page: same pricing, no side effects."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from research import nba_player_pool_dashboard as D
from research import player_pool_model as M

NOW = datetime(2026, 11, 21, 17, 0, tzinfo=UTC)


def priced():
    return pd.DataFrame(
        {
            "snapshot_utc": "2026-11-21T16:59:58.123456+00:00",
            "tip_utc": pd.to_datetime(["2026-11-22 00:30:00+00:00"] * 2, utc=True),
            "event_ticker": "KXNBAPTS-26NOV21PORNYK",
            "ticker": [
                "KXNBAPTS-26NOV21PORNYK-NYKJBRUNSON11-25",
                "KXNBAPTS-26NOV21PORNYK-PORDLILLARD0-20",
            ],
            "player": ["Jalen Brunson", "Damian Lillard Jr."],
            "team": ["NYK", "POR"],
            "stat": "points",
            "line": [24.5, 19.5],
            "model_mean": [26.812345, 21.5],
            "p_model": [0.5876543, 0.55],
            "yes_bid_dollars": [0.55, 0.52],
            "yes_ask_dollars": [0.57, 0.54],
            "injury_status": ["", "Day-To-Day"],
            "player_id": [3934672, 6606],
            "edge_yes": [0.01, 0.0],  # columns the page does not need are left out
        }
    )


def test_the_file_has_the_shape_the_page_reads_its_price_file_in():
    out = M.model_file(priced(), NOW)
    json.dumps(out, allow_nan=False)  # raises on NaN, timestamps or numpy types
    assert out["snapshot_utc"] == "2026-11-21T17:00:00+00:00"
    assert out["columns"] == D.SLATE_COLUMNS
    first = dict(zip(out["columns"], out["rows"][0], strict=True))
    assert first["ticker"] == "KXNBAPTS-26NOV21PORNYK-NYKJBRUNSON11-25"
    assert first["tip_utc"] == "2026-11-22 00:30:00+00:00"
    assert first["player_id"] == 3934672 and first["line"] == 24.5
    assert first["p_model"] == 0.5877 and first["model_mean"] == 26.8123
    assert first["injury_status"] is None  # blank, not the text "nan"
    second = dict(zip(out["columns"], out["rows"][1], strict=True))
    # The key sportsbook lines are matched on drops the suffix.
    assert second["player_key"] == "damian lillard"
    assert second["injury_status"] == "Day-To-Day"


def test_nothing_to_price_is_an_empty_file_not_an_error():
    out = M.model_file(pd.DataFrame(), NOW)
    assert out == {
        "snapshot_utc": "2026-11-21T17:00:00+00:00",
        "columns": D.SLATE_COLUMNS,
        "rows": [],
    }


def schedule(*games):
    frame = pd.DataFrame(games, columns=["game_id", "tip_utc", "completed"])
    frame["tip_utc"] = pd.to_datetime(frame.tip_utc, utc=True)
    frame["completed"] = frame.completed.astype(bool)  # as the real schedule is
    return frame


def test_it_prices_only_games_still_ahead_with_the_projections_function(monkeypatch):
    days = {
        "20261121": schedule(
            (1, "2026-11-21T16:00:00Z", False),  # tipped an hour ago
            (2, "2026-11-22T00:30:00Z", False),  # tonight
            (3, "2026-11-22T01:00:00Z", True),  # marked finished: left out
        ),
        "20261122": schedule((4, "2026-11-23T00:00:00Z", False)),
    }
    asked, seen = [], {}
    monkeypatch.setattr(
        M,
        "scoreboard",
        lambda day, season: (asked.append((day, season)), days.get(day, schedule()))[1],
    )
    monkeypatch.setattr(M, "snapshot", lambda series, now=None: "raw markets")
    monkeypatch.setattr(M, "parse", lambda raw: pd.DataFrame({"ticker": ["a"]}))
    monkeypatch.setattr(M, "injuries", lambda: "report")

    def fake_price(players, games, sched, markets, report, now=None):
        seen.update(
            players=players, games=sched.game_id.tolist(), report=report, now=now
        )
        return priced(), None

    monkeypatch.setattr(M, "price_markets", fake_price)
    players = pd.DataFrame(
        {
            "tip_utc": pd.to_datetime(
                ["2026-11-20T00:00Z", "2026-11-22T00:00Z"], utc=True
            )
        }
    )
    out = M.price_now(NOW, players, "games")
    assert len(out) == 2
    assert [day for day, _ in asked] == ["20261121", "20261122", "20261123"]
    assert {season for _, season in asked} == {2027}
    assert seen["games"] == [2, 4]
    assert seen["report"] == "report" and seen["now"] == NOW
    assert len(seen["players"]) == 1  # no box score from after "now"


def test_no_games_or_no_markets_means_no_model_run(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("the model must not run with nothing to price")

    monkeypatch.setattr(M, "price_markets", boom)
    monkeypatch.setattr(M, "injuries", boom)
    monkeypatch.setattr(M, "snapshot", lambda series, now=None: None)
    players = pd.DataFrame({"tip_utc": pd.to_datetime(["2026-11-20T00:00Z"], utc=True)})
    ahead = schedule((2, "2026-11-22T00:30:00Z", False))
    for games, markets in (
        (schedule(), pd.DataFrame({"t": [1]})),
        (ahead, pd.DataFrame()),
    ):
        monkeypatch.setattr(M, "scoreboard", lambda day, season, games=games: games)
        monkeypatch.setattr(M, "parse", lambda raw, markets=markets: markets)
        assert M.price_now(NOW, players, "games").empty


def test_it_writes_one_file_and_none_of_the_projections_jobs(tmp_path, monkeypatch):
    out = tmp_path / "pool" / "model.json"
    box = tmp_path / "players.parquet"
    pd.DataFrame(
        {"tip_utc": pd.to_datetime(["2026-11-20T00:00Z"], utc=True)}
    ).to_parquet(box)
    monkeypatch.setattr(M, "price_now", lambda now, players, games: priced())
    monkeypatch.setattr(
        "sys.argv", ["m", "--players", str(box), "--games", str(box), "--out", str(out)]
    )
    monkeypatch.chdir(tmp_path)
    M.main()
    written = sorted(p.name for p in tmp_path.rglob("*") if p.is_file())
    assert written == ["model.json", "players.parquet"]
    saved = json.loads(out.read_text("utf-8"))
    assert saved["columns"] == D.SLATE_COLUMNS and len(saved["rows"]) == 2
    source = Path(M.__file__).read_text("utf-8")
    assert "from live.nba_projections import price_markets\n" in source
    for forbidden in (
        "LEDGER",
        "post_orders",
        ".to_csv(",
        "write_bet_card",
        "publish(",
    ):
        assert forbidden not in source, forbidden
