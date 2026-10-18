"""Roster membership and availability must fail closed before NFL order selection."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from markets.nfl.data import upcoming_rows
from markets.nfl.roster_guard import (
    availability,
    current_rosters,
    event_teams,
    parse_roster,
)


def espn_roster(names):
    return {
        "athletes": [
            {
                "position": "Wide Receiver",
                "items": [
                    {"displayName": name, "status": {"type": {"name": status}}}
                    for name, status in names
                ],
            }
        ]
    }


def schedule():
    return pd.DataFrame(
        {
            "game_id": ["2026_06_NYJ_NE"],
            "season": [2026],
            "week": [6],
            "gameday": ["2026-10-18"],
            "away_team": ["NYJ"],
            "home_team": ["NE"],
        }
    )


def injuries(status=None):
    return pd.DataFrame(
        [
            {
                "season": 2026,
                "week": 6,
                "team": "NE",
                "full_name": "A.J. Brown",
                "report_status": status,
            }
        ]
    )


def test_espn_group_roster_and_injured_reserve_or_questionable():
    roster = parse_roster(
        espn_roster([
            ("A.J. Brown", "ACTIVE"),
            ("Player Q", "QUESTIONABLE"),
            ("Player IR", "INJURED_RESERVE"),
        ])
    )
    assert roster["a j brown"] is True
    assert roster["player q"] is False
    assert roster["player ir"] is False
    with pytest.raises(ValueError):
        parse_roster({"athletes": []})


def test_verified_matchup_and_current_roster_membership():
    event = "KXNFLRECYDS-26OCT18NYJNE"
    game = event_teams(event, "2026-10-18", schedule())
    assert game == ("NYJ", "NE", 2026, 6)
    assert event_teams("KXNFLRECYDS-26OCT18NEBUF", "2026-10-18", schedule()) is None
    assert event_teams(event, "2026-10-19", schedule()) is None
    rosters = {"NYJ": {"garrett wilson": True}, "NE": {"a j brown": True}}
    assert availability("A.J. Brown", game, rosters, injuries()) == ("NE", "")
    assert availability("A.J. Brown", game, rosters, injuries("Questionable"))[1]
    assert availability("A.J. Brown", game, rosters, injuries("Out"))[1]
    assert availability("A.J. Brown", game, {"NYJ": {}, "NE": {}}, injuries())[1]
    assert availability("A.J. Brown", game, {"NYJ": {"a j brown": True}, "NE": {"a j brown": True}}, injuries())[1]


def test_cache_is_fresh_only_and_error_does_not_authorize_roster(tmp_path):
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    cache = tmp_path / "snapshot.json"
    counter = {"count": 0}

    def fetch(url):
        counter["count"] += 1
        return espn_roster([("A.J. Brown", "ACTIVE")])

    assert current_rosters(["NE"], now=now, cache=cache, fetch=fetch)["NE"]["a j brown"]
    assert current_rosters(
        ["NE"], now=now + timedelta(minutes=10), cache=cache, fetch=lambda _: 1
    )["NE"]["a j brown"]
    assert counter["count"] == 1

    def offline(url):
        raise OSError("provider offline")

    with pytest.raises(ValueError):
        current_rosters(
            ["NE"], now=now + timedelta(minutes=25), cache=cache, fetch=offline
        )
    with pytest.raises(ValueError):
        current_rosters(["NE", "BUF"], now=now, cache=cache, fetch=offline)


def test_current_roster_includes_returning_or_traded_player():
    games = pd.DataFrame(
        {
            "game_id": ["g1"],
            "season": [2026],
            "week": [6],
            "home_team": ["NE"],
            "away_team": ["NYJ"],
            "home_score": [np.nan],
            "result": [np.nan],
            "spread_line": [3.0],
            "total_line": [43.0],
            "home_moneyline": [-150],
            "away_moneyline": [130],
            "home_qb_id": ["qb_ne"],
            "away_qb_id": ["qb_nyj"],
            "home_qb_name": ["QB NE"],
            "away_qb_name": ["QB NYJ"],
        }
    )
    history = pd.DataFrame(
        {
            "player_id": ["aj", "other"],
            "player_display_name": ["A.J. Brown", "Other Receiver"],
            "position": ["WR", "WR"],
            "season": [2026, 2026],
            "week": [1, 5],
            "game_id": ["old1", "old2"],
            "team": ["PHI", "NYJ"],
        }
    )
    rows = upcoming_rows(
        games, history, 2026, 6,
        rosters={"NE": {"a j brown": True}, "NYJ": {"other receiver": True}},
    )
    brown = rows.loc[rows.player_id.eq("aj")].iloc[0]
    assert brown.team == "NE"
    assert brown.week == 6
    assert "other" in set(rows.player_id)
    assert "aj" not in set(upcoming_rows(games, history, 2026, 6).player_id)
