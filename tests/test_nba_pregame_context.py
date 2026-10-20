"""Pure-contract NBA pregame minutes and starting-lineup tests.

No paid credentials or exchange writes are required.
"""
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from live.nba_pregame_context import (
    enrich,
    historical_minutes_projection,
    load,
    parse_lineups,
    parse_minutes,
)

NOW = datetime(2026, 10, 20, 22, 0, tzinfo=UTC)
DATE = "2026-10-20"


def game(players=None, status=None):
    return {
        "Date": DATE,
        "Games": [{
            "DateTime": "2026-10-20T19:30:00-04:00",
            "Teams": [{
                "Code": "LAL",
                "LineupStatus": status,
                "Players": players if players is not None else [
                    {"FirstName": "Test", "LastName": "Player"},
                    {"FirstName": "Test", "LastName": "Second"},
                    {"FirstName": "Test", "LastName": "Third"},
                    {"FirstName": "Test", "LastName": "Fourth"},
                    {"FirstName": "Test", "LastName": "Fifth"},
                ],
            }],
        }],
    }


def minute_players():
    return game([
        {
            "FirstName": "Test",
            "LastName": "Player",
            "Projections": {"Minutes": 24},
        }
    ])


def test_explicit_minutes_and_lineups_are_separate():
    mins = parse_minutes(minute_players(), DATE)
    assert mins[(DATE, "LAL", "testplayer")] == 24
    tentative, statuses = parse_lineups(game(status="Projected"), DATE)
    assert tentative == {}
    assert statuses[(DATE, "LAL")] == "unverified"
    confirmed, statuses = parse_lineups(game(status="C"), DATE)
    assert len(confirmed[(DATE, "LAL")]) == 5
    assert statuses[(DATE, "LAL")] == "confirmed"


@pytest.mark.parametrize("minutes", [-1, 49, "unknown", None])
def test_bad_minute_values_never_become_forecasts(minutes):
    p = minute_players()
    p["Games"][0]["Teams"][0]["Players"][0]["Projections"]["Minutes"] = minutes
    with pytest.raises(ValueError):
        parse_minutes(p, DATE)


def test_duplicate_players_and_malformed_starters_fail_closed():
    p = minute_players()
    p["Games"][0]["Teams"][0]["Players"].append(
        p["Games"][0]["Teams"][0]["Players"][0]
    )
    with pytest.raises(ValueError, match="duplicate"):
        parse_minutes(p, DATE)
    with pytest.raises(ValueError, match="starting five"):
        parse_lineups(game(status="Confirmed", players=[{"FirstName": "One"}]), DATE)


def test_late_license_data_is_timestamped_and_identity_joined():
    frame = pd.DataFrame([{
        "tip_utc": pd.Timestamp("2026-10-20T23:30:00Z"),
        "team_espn": "LAL", "player": "Test Player",
    }])
    context = {
        "configured": True,
        "fetched_utc": NOW.isoformat(),
        "minutes": parse_minutes(minute_players(), DATE),
        "confirmed_starters": parse_lineups(game(status="Confirmed"), DATE)[0],
        "lineup_statuses": {(DATE, "LAL"): "confirmed"},
    }
    result = enrich(frame, context, NOW)
    assert result.projected_minutes.iloc[0] == 24
    assert result.lineup_confirmation_status.iloc[0] == "confirmed"
    assert bool(result.confirmed_starter.iloc[0]) is True
    with pytest.raises(ValueError, match="Stale"):
        enrich(frame, context, NOW + timedelta(minutes=16))


def test_no_api_key_is_explicitly_unverified(monkeypatch):
    monkeypatch.delenv("ROTOWIRE_API_KEY", raising=False)
    assert load({DATE}, NOW) == {
        "configured": False,
        "reason": "vendor_api_key_absent",
    }


def test_historical_minutes_is_a_prior_only_uncalibrated_estimate():
    f = pd.DataFrame([{
        "historical_minutes_baseline": 30,
        "last_game_minutes": 20,
        "recent_start_rate": 0.8,
    }])
    result = historical_minutes_projection(f)
    assert result.minutes_forecast_internal.iloc[0] == 28
    assert result.minutes_uncertainty_heuristic.iloc[0] == 11
    assert result.minutes_forecast_internal_source.iloc[0] == "prior_only_uncalibrated"
