"""research/pickem_probe.py: counts only, a hard credit ceiling, owner-started."""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from kalshi.books import BooksError
from research import pickem_probe as P

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 24, 18, 0, tzinfo=UTC)
WORKFLOW = (ROOT / ".github/workflows/pickem-probe.yml").read_text("utf-8")


def book(key, market, quotes):
    outcomes = [
        {"name": side, "description": player, "point": line, "price": -110}
        for player, line in quotes
        for side in ("Over", "Under")
    ]
    return {"key": key, "markets": [{"key": market, "outcomes": outcomes}]}


def reply():
    return {
        "bookmakers": [
            book(
                "draftkings", "player_shots_on_goal", [("A One", 2.5), ("B Two", 3.5)]
            ),
            book("fanduel", "player_shots_on_goal", [("A One", 2.5)]),
            book(
                "prizepicks", "player_shots_on_goal", [("a one", 2.5), ("B Two", 2.5)]
            ),
            book("underdog", "player_shots_on_goal", [("C Three", 1.5)]),
            book("prizepicks", "player_goals", [("A One", 0.5)]),
            {"key": "fanduel", "markets": [{"key": "player_goals", "outcomes": []}]},
        ]
    }


def test_counts_books_app_lines_and_exact_matches():
    counts = P.count_event(reply())
    shots = counts["player_shots_on_goal"]
    assert shots["sportsbooks"] == 2 and shots["sportsbook_lines"] == 2
    assert shots["PrizePicks_lines"] == 2
    # Names are matched whatever their capitals; B Two's app line is not quoted.
    assert shots["PrizePicks_lines_a_sportsbook_also_quotes"] == 1
    assert shots["Underdog_lines"] == 1
    assert shots["Underdog_lines_a_sportsbook_also_quotes"] == 0
    goals = counts["player_goals"]
    assert goals["sportsbooks"] == 0 and goals["PrizePicks_lines"] == 1
    # Counts only: no price and no player survives.
    text = json.dumps(counts)
    assert "-110" not in text and "One" not in text


def feed(listed, fail=()):
    calls = []

    def events(key, sport):
        if sport in fail:
            raise BooksError(f"odds api /sports/{sport}/events: HTTP 404")
        return listed, {"remaining": str(60_000 - 10 * len(calls))}

    def event_odds(key, event_id, sport, markets, regions):
        calls.append((sport, event_id, tuple(markets), regions))
        return reply(), {"remaining": str(60_000 - 10 * len(calls))}

    return events, event_odds, calls


def games(*hours):
    return [
        {"id": f"g{i}", "commence_time": (NOW + timedelta(hours=h)).isoformat()}
        for i, h in enumerate(hours)
    ]


def test_it_asks_about_the_two_nearest_games_in_each_sport():
    events, event_odds, calls = feed(games(30, 5, -2, 100, 1), fail={"soccer_usa_mls"})
    report = P.probe(NOW, "k", events, event_odds)
    assert set(report["sports"]) == set(P.SPORTS)
    nhl = report["sports"]["icehockey_nhl"]
    assert nhl["games_listed"] == 5 and nhl["games_asked"] == 2
    asked = [c for c in calls if c[0] == "icehockey_nhl"]
    # Nearest first; not the game that has started nor the one four days out.
    assert [c[1] for c in asked] == ["g4", "g1"]
    assert all(c[3] == "us,us_dfs" for c in calls)
    assert nhl["markets"]["player_shots_on_goal"]["PrizePicks_lines"] == 4
    assert nhl["markets"]["player_shots_on_goal"]["sportsbooks"] == 2
    # A sport the feed does not list is noted and costs nothing.
    mls = report["sports"]["soccer_usa_mls"]
    assert mls["games_asked"] == 0 and "not listed" in mls["note"]
    assert report["credits_spent"] == 10 * len(calls)
    assert len(calls) == P.GAMES_PER_SPORT * (len(P.SPORTS) - 1)


def test_it_spends_nothing_when_credits_are_low():
    def events(key, sport):
        return games(1, 2), {"remaining": str(P.MIN_CREDITS_LEFT - 1)}

    def event_odds(*args, **kwargs):
        raise AssertionError("no paid call when credits are low")

    report = P.probe(NOW, "k", events, event_odds)
    assert "stopped" in report["note"]
    assert P.MIN_CREDITS_LEFT >= 15_000


def test_the_ceiling_is_small_and_tennis_is_left_out():
    # Two groups, two games, every market returned: the most it can cost.
    assert P.MAX_CREDITS == 2 * P.GAMES_PER_SPORT * sum(map(len, P.SPORTS.values()))
    assert P.MAX_CREDITS <= 200
    assert not any("tennis" in sport for sport in P.SPORTS)
    assert all("alternate" not in m for markets in P.SPORTS.values() for m in markets)


def test_the_workflow_is_started_by_the_owner_only_and_writes_one_file():
    head = WORKFLOW[: WORKFLOW.index("\njobs:")]
    assert "workflow_dispatch:" in head
    for trigger in ("schedule:", "push:", "pull_request", "workflow_run:"):
        assert trigger not in head, trigger
    assert "github.ref == 'refs/heads/main'" in WORKFLOW
    assert "github.actor == 'akilatrades'" in WORKFLOW
    assert "github.triggering_actor == 'akilatrades'" in WORKFLOW
    assert re.findall(r"git add (.+)", WORKFLOW) == ["outputs/pickem/probe.json"]
    assert WORKFLOW.count("secrets.ODDS_API_KEY") == 1
    assert "python -m research.pickem_probe" in WORKFLOW
