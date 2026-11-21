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
    monkeypatch.setattr(M, "official_report", lambda now: "official")

    def fake_reconcile(report, official, sched, players):
        seen.update(feed=report, official=official, reconciled=sched.game_id.tolist())
        return "reconciled report", [
            {"player": "A", "feed": "Out", "official": "Probable"}
        ]

    monkeypatch.setattr(M, "reconcile", fake_reconcile)

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
    out, availability = M.price_now(NOW, players, "games")
    assert len(out) == 2
    assert [day for day, _ in asked] == ["20261121", "20261122", "20261123"]
    assert {season for _, season in asked} == {2027}
    assert seen["games"] == [2, 4]
    assert seen["now"] == NOW
    assert len(seen["players"]) == 1  # no box score from after "now"
    # The injury feed is laid under the official report for the same games,
    # and the model prices from the result.
    assert (seen["feed"], seen["official"]) == ("report", "official")
    assert seen["reconciled"] == [2, 4] and seen["report"] == "reconciled report"
    assert availability["official_report"] is True
    assert availability["changes"][0]["official"] == "Probable"


def test_no_games_or_no_markets_means_no_model_run(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("the model must not run with nothing to price")

    monkeypatch.setattr(M, "price_markets", boom)
    monkeypatch.setattr(M, "injuries", boom)
    monkeypatch.setattr(M, "official_report", boom)
    monkeypatch.setattr(M, "snapshot", lambda series, now=None: None)
    players = pd.DataFrame({"tip_utc": pd.to_datetime(["2026-11-20T00:00Z"], utc=True)})
    ahead = schedule((2, "2026-11-22T00:30:00Z", False))
    for games, markets in (
        (schedule(), pd.DataFrame({"t": [1]})),
        (ahead, pd.DataFrame()),
    ):
        monkeypatch.setattr(M, "scoreboard", lambda day, season, games=games: games)
        monkeypatch.setattr(M, "parse", lambda raw, markets=markets: markets)
        nothing, availability = M.price_now(NOW, players, "games")
        assert nothing.empty and availability is None


def test_it_writes_one_file_and_none_of_the_projections_jobs(tmp_path, monkeypatch):
    out = tmp_path / "pool" / "model.json"
    box = tmp_path / "players.parquet"
    pd.DataFrame(
        {"tip_utc": pd.to_datetime(["2026-11-20T00:00Z"], utc=True)}
    ).to_parquet(box)
    notes = {"official_report": True, "changes": []}
    monkeypatch.setattr(M, "price_now", lambda now, players, games: (priced(), notes))
    monkeypatch.setattr(
        "sys.argv", ["m", "--players", str(box), "--games", str(box), "--out", str(out)]
    )
    monkeypatch.chdir(tmp_path)
    M.main()
    written = sorted(p.name for p in tmp_path.rglob("*") if p.is_file())
    assert written == ["model.json", "players.parquet"]
    saved = json.loads(out.read_text("utf-8"))
    assert saved["columns"] == D.SLATE_COLUMNS and len(saved["rows"]) == 2
    assert saved["availability"] == notes
    source = Path(M.__file__).read_text("utf-8")
    assert "from live.nba_projections import player_ids, price_markets\n" in source
    for forbidden in (
        "LEDGER",
        "post_orders",
        ".to_csv(",
        "write_bet_card",
        "publish(",
    ):
        assert forbidden not in source, forbidden


def box_scores():
    """Enough box score to tell who is who: one row per player, latest team."""
    rows = [
        (4065733, "Ty Jerome", "MEM"),
        (4433083, "Cam Spencer", "MEM"),
        (5041935, "Cameron Boozer", "MEM"),
        (3134908, "Jerami Grant", "MEM"),
        (11, "Jaden McDaniels", "MIN"),
        (21, "Marcus Smart", "LAL"),
        (22, "Marcus Smart", "BOS"),  # a namesake: the name alone settles nothing
    ]
    frame = pd.DataFrame(rows, columns=["player_id", "player", "team"])
    frame["tip_utc"] = pd.Timestamp("2026-11-20T01:00:00Z")
    return frame


def feed(*rows):
    frame = pd.DataFrame(
        rows, columns=["team", "player_id", "player", "status", "comment", "updated"]
    )
    frame["out"] = frame.status.str.lower().isin({"out", "doubtful"})
    return frame


def official(*rows):
    frame = pd.DataFrame(rows, columns=["game_date", "team_espn", "player", "status"])
    frame["player_key"] = frame.player.map(M.official_injuries.player_key)
    return frame


TONIGHT = pd.DataFrame(
    {
        "game_id": [7],
        "tip_utc": pd.to_datetime(
            ["2026-11-22T01:00:00Z"], utc=True
        ),  # 8pm Eastern, 21 Nov
        "home": ["MIN"],
        "away": ["MEM"],
    }
)


def test_the_official_report_overrides_a_stale_feed_for_tonights_games():
    """21 November 2026: the feed still had Ty Jerome out from two days
    earlier; the league's report had him probable."""
    report = feed(
        ("MEM", 4065733, "Ty Jerome", "Out", "ruled out for Thursday", "2026-11-19"),
        ("MEM", 3134908, "Jerami Grant", "Day-To-Day", "left Thursday's game", ""),
        ("MIN", 11, "Jaden McDaniels", "Out", "", ""),
    )
    league = official(
        ("11/21/2026", "MEM", "Jerome, Ty", "Probable"),
        ("11/21/2026", "MEM", "Grant, Jerami", "Out"),
        ("11/21/2026", "MEM", "Boozer, Cameron", "Out"),  # not in the feed at all
        ("11/21/2026", "MEM", "Spencer, Cam", "Available"),  # already expected
        ("11/21/2026", "MIN", "McDaniels, Jaden", "Doubtful"),  # both say out
        ("11/22/2026", "MEM", "Jerome, Ty", "Out"),  # tomorrow's game: not tonight's
        ("11/21/2026", "MEM", "Smart, Marcus", "Out"),  # two Marcus Smarts: left alone
        ("11/21/2026", "MEM", "Nobody, Known", "Out"),
        ("11/21/2026", "MEM", "", "NOT YET SUBMITTED"),
    )
    before = report.copy()
    out, changes = M.reconcile(report, league, TONIGHT, box_scores())
    assert report.equals(before)  # the feed's own table is not edited in place
    by_id = out.set_index("player_id")
    assert not by_id.at[4065733, "out"] and by_id.at[4065733, "status"] == "Probable"
    assert by_id.at[3134908, "out"] and by_id.at[3134908, "status"] == "Out"
    assert by_id.at[5041935, "out"] and by_id.at[5041935, "team"] == "MEM"
    assert by_id.at[11, "out"] and by_id.at[11, "status"] == "Out"  # untouched
    assert (
        4433083 not in by_id.index and 21 not in by_id.index and 22 not in by_id.index
    )
    assert changes == [
        {"player": "Ty Jerome", "team": "MEM", "feed": "Out", "official": "Probable"},
        {
            "player": "Jerami Grant",
            "team": "MEM",
            "feed": "Day-To-Day",
            "official": "Out",
        },
        {"player": "Cameron Boozer", "team": "MEM", "feed": None, "official": "Out"},
    ]
    json.dumps(changes, allow_nan=False)


def test_without_an_official_report_the_feed_stands(monkeypatch, capsys):
    report = feed(("MEM", 4065733, "Ty Jerome", "Out", "", ""))
    for league in (None, official()):
        out, changes = M.reconcile(report, league, TONIGHT, box_scores())
        assert out.equals(report) and changes == []

    # A report that cannot be fetched or read is a warning, never a crash.
    def broken(now, deadline=None):
        raise M.official_injuries.ReportError("no_report_found")

    monkeypatch.setattr(M.official_injuries, "report_at", broken)
    assert M.official_report(NOW) is None
    monkeypatch.setattr(M.official_injuries, "report_at", lambda *a, **k: 1 / 0)
    try:
        M.official_report(NOW)
    except ZeroDivisionError:
        pass  # a bug is not swallowed, only a missing or unreadable report
    assert "official injury report not read" in capsys.readouterr().out
    monkeypatch.setattr(
        M.official_injuries, "report_at", lambda now, deadline=None: ("issued", "table")
    )
    assert M.official_report(NOW) == "table"


def test_the_file_carries_what_was_overridden():
    notes = {
        "official_report": True,
        "changes": [
            {
                "player": "Ty Jerome",
                "team": "MEM",
                "feed": "Out",
                "official": "Probable",
            }
        ],
    }
    assert M.model_file(priced(), NOW, notes)["availability"] == notes
    assert M.model_file(pd.DataFrame(), NOW, notes)["availability"] == notes
    assert "availability" not in M.model_file(priced(), NOW)
