"""The Novig and ProphetX game-winner backtest: what is read, matched, scored
and spent. No network."""

import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kalshi import books
from research import exchange_winners as W

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/exchange-winners.yml").read_text("utf-8")
SNAP = datetime(2026, 1, 10, 15, 30, tzinfo=UTC)  # a Saturday
DAY = SNAP.date()
FRESH = "2026-01-10T15:20:00Z"
SPORTSBOOKS = ("draftkings", "fanduel", "betmgm")


def book(key, home, away, home_price, away_price, updated=FRESH):
    """A bookmaker's moneyline. Prices are the cost of a $1 payout."""
    return {
        "key": key,
        "last_update": updated,
        "markets": [
            {
                "key": "h2h",
                "last_update": updated,
                "outcomes": [
                    {"name": home, "price": 1 / home_price},
                    {"name": away, "price": 1 / away_price},
                ],
            }
        ],
    }


def feed_game(gid, home, away, start, bookmakers):
    return {
        "id": gid,
        "home_team": home,
        "away_team": away,
        "commence_time": start,
        "bookmakers": bookmakers,
    }


def espn_event(home, away, start, home_score, away_score, done=True, kind=2):
    def side(name, where, score, other):
        return {
            "homeAway": where,
            "score": str(score),
            "winner": done and score > other,
            "team": {"displayName": name},
        }

    return {
        "date": start,
        "season": {"type": kind},
        "competitions": [
            {
                "status": {"type": {"completed": done}},
                "competitors": [
                    side(home, "home", home_score, away_score),
                    side(away, "away", away_score, home_score),
                ],
            }
        ],
    }


def books_at(home, away, fair_home):
    """Three sportsbooks with a 4-point margin around ``fair_home``."""
    return [
        book(key, home, away, fair_home * 1.04, (1 - fair_home) * 1.04)
        for key in SPORTSBOOKS
    ]


# --- names and results ---------------------------------------------------------


def test_team_names_from_the_two_sources_meet():
    assert W.team_key("Michigan St Spartans") == W.team_key("Michigan State Spartans")
    assert W.team_key("San José State Spartans") == "san jose state spartans"
    assert W.team_key("Hawai'i Rainbow Warriors") == "hawaii rainbow warriors"
    # "St" at the front is a saint, not a state.
    assert W.team_key("St. John's Red Storm") == "st johns red storm"
    assert W.team_key("Texas A&M Aggies") == "texas a and m aggies"


def test_the_scoreboard_keeps_real_games_and_says_who_won():
    payload = {
        "events": [
            espn_event("Boston Celtics", "Miami Heat", "2026-01-10T20:00Z", 110, 99),
            espn_event(
                "Dallas Cowboys", "New York Giants", "2026-01-10T21:00Z", 20, 20
            ),
            espn_event("Utah Jazz", "Denver Nuggets", "2026-01-11T02:00Z", 0, 0, False),
            espn_event("Preseason A", "Preseason B", "2026-01-10T19:00Z", 3, 1, kind=1),
            {"date": "2026-01-10T19:00Z"},  # malformed: skipped, not fatal
        ]
    }
    games = W.parse_scoreboard(payload)
    assert [g["home"] for g in games] == [
        "boston celtics",
        "dallas cowboys",
        "utah jazz",
    ]
    assert [g["winner"] for g in games] == ["home", None, None]
    assert [g["final"] for g in games] == [True, True, False]
    with pytest.raises(ValueError):
        W.parse_scoreboard({"oops": 1})


def test_a_result_needs_both_teams_and_the_right_game():
    finals = W.parse_scoreboard(
        {
            "events": [
                # A doubleheader: the same teams twice in a day.
                espn_event("New York Yankees", "Boston Red Sox", "2026-01-10T17:05Z", 2, 5),
                espn_event("New York Yankees", "Boston Red Sox", "2026-01-10T23:05Z", 7, 1),
                espn_event("Connecticut Huskies", "Duke Blue Devils", "2026-01-10T19:00Z", 70, 60),
                espn_event("LSU Tigers", "Auburn Tigers", "2026-01-10T19:00Z", 1, 0),
                espn_event("Dallas Cowboys", "New York Giants", "2026-01-10T21:00Z", 20, 20),
                espn_event("Utah Jazz", "Denver Nuggets", "2026-01-11T02:00Z", 0, 0, False),
            ]
        }
    )  # fmt: skip

    def result(home, away, start):
        return W.find_result(feed_game("g", home, away, start, []), finals)

    # The feed's home team can be ESPN's away team: the answer is the feed's.
    assert (
        result("Boston Red Sox", "New York Yankees", "2026-01-10T17:10:00Z") == "home"
    )
    assert (
        result("Boston Red Sox", "New York Yankees", "2026-01-10T23:00:00Z") == "away"
    )
    # Spelled differently: nicknames and start time agree, one candidate.
    assert result("UConn Huskies", "Duke Blue Devils", "2026-01-10T19:00:00Z") == "home"
    assert result("UConn Huskies", "Duke Blue Devils", "2026-01-10T22:00:00Z") is None
    # Same nickname on both sides: only an exact match will do.
    assert result("LSU Tigers", "Auburn Tigers", "2026-01-10T19:00:00Z") == "home"
    assert (
        result("Louisiana St Tigers", "Auburn Tigers", "2026-01-10T19:00:00Z") is None
    )
    assert result("Dallas Cowboys", "New York Giants", "2026-01-10T21:00:00Z") == "tie"
    assert result("Utah Jazz", "Denver Nuggets", "2026-01-11T02:00:00Z") is None
    assert result("Nobody FC", "Someone United", "2026-01-10T19:00:00Z") is None


# --- prices --------------------------------------------------------------------


def test_only_fresh_two_sided_prices_count():
    one_sided = book("prophetx", "A", "B", 0.5, 0.5)
    one_sided["markets"][0]["outcomes"].pop()
    game = feed_game(
        "g",
        "A",
        "B",
        "2026-01-10T20:00:00Z",
        [
            book("novig", "A", "B", 0.61, 0.41),
            book("kalshi", "A", "B", 0.6, 0.41, updated="2026-01-10T14:29:00Z"),
            book("fanduel", "A", "B", 0.62, 0.42, updated="2026-01-10T13:31:00Z"),
            book("betmgm", "A", "B", 0.62, 0.42, updated="2026-01-10T13:29:00Z"),
            book("draftkings", "A", "B", 0.62, 0.42, updated=None),
            one_sided,
        ],
    )
    quoted = W.quotes(game, SNAP)
    # Exchange: 60 minutes. Sportsbook: 2 hours. No time stamp: not used.
    assert set(quoted) == {"novig", "fanduel"}
    assert quoted["novig"] == pytest.approx((0.61, 0.41))
    assert set(W.two_sided(game)) == {"novig", "kalshi", "fanduel", "betmgm", "draftkings"}  # fmt: skip


def test_the_fair_price_needs_three_sportsbooks_and_no_exchange():
    quoted = {
        "draftkings": (0.624, 0.416),
        "fanduel": (0.63, 0.42),
        "novig": (0.9, 0.2),  # an exchange never enters the sportsbooks' price
    }
    fair, n = W.fair_home(quoted)
    assert fair is None and n == 2
    quoted["betmgm"] = (0.618, 0.412)
    fair, n = W.fair_home(quoted)
    assert n == 3 and fair == pytest.approx(0.6, abs=1e-9)


def test_rows_follow_the_window_the_limits_and_the_result():
    finals = W.parse_scoreboard(
        {
            "events": [
                espn_event("Home A", "Away A", "2026-01-10T20:00Z", 10, 3),
                espn_event("Home B", "Away B", "2026-01-10T21:00Z", 1, 9),
                espn_event("Home T", "Away T", "2026-01-10T22:00Z", 7, 7),
            ]
        }
    )
    games = [
        feed_game(
            "a",
            "Home A",
            "Away A",
            "2026-01-10T20:00:00Z",
            [book("novig", "Home A", "Away A", 0.58, 0.44)]
            + books_at("Home A", "Away A", 0.6),
        ),
        # ProphetX too wide (30 points), Novig a price over 98 cents: neither kept.
        feed_game(
            "b",
            "Home B",
            "Away B",
            "2026-01-10T21:00:00Z",
            [
                book("prophetx", "Home B", "Away B", 0.7, 0.6),
                book("novig", "Home B", "Away B", 0.985, 0.03),
                book("kalshi", "Home B", "Away B", 0.31, 0.7),
            ],
        ),
        feed_game("t", "Home T", "Away T", "2026-01-10T22:00:00Z", []),
        feed_game("x", "No Such", "Team Here", "2026-01-10T22:00:00Z", []),
        # Too soon (20 minutes) and too far (13 hours): not this snapshot's games.
        feed_game("soon", "Home A", "Away A", "2026-01-10T15:50:00Z", []),
        feed_game("far", "Home A", "Away A", "2026-01-11T04:30:00Z", []),
    ]
    rows, seen = W.day_rows("nba", DAY, games, SNAP, finals)
    assert seen == {"listed": 4, "unmatched": 1, "ties": 1, "priced": 2}
    frame = pd.DataFrame(rows)
    assert list(frame.columns) == W.ROW_COLUMNS
    a = frame[frame.game == "nba:a"].set_index("side")
    assert list(a.venue) == ["novig", "novig"]
    assert a.loc["home", "price"] == 0.58 and a.loc["home", "won"] == 1
    assert a.loc["away", "won"] == 0 and a.loc["home", "width"] == pytest.approx(0.02)
    assert a.loc["home", "fair"] == pytest.approx(0.6) and a.loc["home", "books"] == 3
    b = frame[frame.game == "nba:b"]
    assert set(b.venue) == {"kalshi"} and b.fair.isna().all()  # no sportsbooks there
    assert b.set_index("side").loc["away", "won"] == 1


# --- the score -----------------------------------------------------------------


def test_each_venue_is_charged_its_own_fee():
    price, won = np.array([0.4, 0.4]), np.array([1, 0])
    assert W.fees("novig", price, won).tolist() == [0.0, 0.0]
    assert W.fees("prophetx", price, won) == pytest.approx([0.012, 0.0])
    assert W.fees("kalshi", price, won) == pytest.approx([0.0168, 0.0168])
    assert np.isnan(W.fees("polymarket_us", price, won)).all()  # not confirmed


def rows_for(venue, sport, n, price, fair, wins, width=0.04, start=0):
    """``n`` one-team bets on ``n`` games, the first ``wins`` of them winners."""
    return [
        {
            "sport": sport,
            "day": (date(2026, 1, 1) + timedelta(days=i % 40)).isoformat(),
            "game": f"{sport}:{venue}:{start + i}",
            "venue": venue,
            "side": "home",
            "price": price,
            "fair": fair,
            "books": 3,
            "width": width,
            "won": int(i < wins),
        }
        for i in range(n)
    ]


def test_buying_every_team_costs_half_the_width_plus_the_fee():
    rows = []
    for i in range(50):
        for side, price, won in (("home", 0.62, 1), ("away", 0.42, 0)):
            for venue in ("novig", "prophetx"):
                rows.append(
                    {
                        "sport": "nba",
                        "day": "2026-01-10",
                        "game": f"nba:{i}",
                        "venue": venue,
                        "side": side,
                        "price": price,
                        "fair": None,
                        "books": 0,
                        "width": 0.04,
                        "won": won,
                    }
                )
    cost = W.score(pd.DataFrame(rows))["cost"]
    assert cost["novig"]["all"]["before_fees_cents"] == pytest.approx(-2.0)
    assert cost["novig"]["all"]["after_fees_cents"] == pytest.approx(-2.0)
    # ProphetX: 2% of the winner's 38 cents, shared over the two bets.
    assert cost["prophetx"]["all"]["after_fees_cents"] == pytest.approx(-2.38)
    assert cost["novig"]["nba"]["width_pct"] == pytest.approx(4.0)
    assert cost["novig"]["all"]["games"] == 50 and "t" not in cost["novig"]["all"]


def test_the_value_rules_and_the_bar():
    rows = []
    # Novig: 80 bets a sport in five sports, bought at 45 with a fair of 50
    # (5 points of value) and winning 60%: a clear, broad profit.
    for k, sport in enumerate(("nfl", "cfb", "nba", "ncaamb", "mlb")):
        rows += rows_for("novig", sport, 80, 0.45, 0.50, 48, start=1000 * k)
    # ProphetX: 3 points of value, 40 bets, winning 45% at a price of 47.
    rows += rows_for("prophetx", "nba", 40, 0.47, 0.50, 18)
    # No value: never a bet under either rule.
    rows += rows_for("novig", "nba", 30, 0.52, 0.50, 30, start=9000)
    result = W.score(pd.DataFrame(rows))
    novig = result["value"]["novig"]
    assert novig["value 2"]["all"]["bets"] == 400 == novig["value 4"]["all"]["bets"]
    assert novig["value 4"]["all"]["after_fees_cents"] == pytest.approx(15.0)
    assert novig["value 4"]["all"]["t"] > 2
    assert novig["value 4"]["nba"]["bets"] == 80
    halves = novig["value 4"]["first half"]["bets"] + novig["value 4"]["second half"]["bets"]  # fmt: skip
    assert halves == 400
    verdict = result["verdict"]["novig"]["value 4"]
    assert verdict["passes"] is True and verdict["sports_positive"] == 5
    px = result["value"]["prophetx"]
    assert px["value 2"]["all"]["bets"] == 40 and px["value 4"]["all"]["bets"] == 0
    lost = result["verdict"]["prophetx"]["value 2"]
    assert lost["passes"] is False and lost["enough_bets"] is False
    assert result["verdict"]["prophetx"]["value 4"]["passes"] is False
    # Exploratory table: every Novig team at 45 cents is in the 45-55 band.
    assert result["by_price"]["novig"]["45-55c"]["bets"] == 430


def test_a_profit_in_too_few_sports_does_not_pass():
    rows = rows_for("novig", "nba", 400, 0.45, 0.50, 240)
    verdict = W.score(pd.DataFrame(rows))["verdict"]["novig"]["value 4"]
    assert verdict["enough_bets"] and verdict["t_at_least_2"]
    assert verdict["sports_positive"] == 1 and verdict["passes"] is False


def test_nothing_pulled_still_scores_and_writes_strict_json(tmp_path):
    result = W.score(pd.DataFrame(columns=W.ROW_COLUMNS))
    assert result["verdict"]["novig"]["value 2"]["passes"] is False
    W.write_json({"a": float("nan"), "b": np.bool_(True), "c": np.int64(3)}, tmp_path / "x.json")  # fmt: skip
    assert json.loads((tmp_path / "x.json").read_text()) == {"a": None, "b": True, "c": 3}  # fmt: skip
    text = W.render_backtest(
        result, {"note": "n", "days_done": 0, "days_in_plan": 9, "credits_spent_in_all": 0}
    )  # fmt: skip
    assert "does not pass" in text and "simulated" in text


# --- the plan and the pull -----------------------------------------------------


def test_snapshot_times_and_the_fixed_order():
    assert W.snapshot_time(date(2026, 1, 10)) == SNAP  # Saturday
    assert W.snapshot_time(date(2026, 1, 12)).hour == 21  # Monday
    order = W.plan(date(2025, 9, 1), date(2026, 11, 21))
    assert order == W.plan(date(2025, 9, 1), date(2026, 11, 21))  # the same every run
    assert [sport for sport, _ in order[:6]] == list(
        W.SPORTS
    )  # one sport after another
    assert len(set(order)) == len(order)
    for sport, day in order:
        assert day.month in W.SPORTS[sport]["months"]
    assert not any(sport == "nfl" and day.month == 6 for sport, day in order)


class Feed:
    """A fake odds feed and scoreboard for two NBA game days and an off day."""

    def __init__(self, remaining=80_000):
        self.remaining, self.calls = remaining, []
        self.game_days = {date(2026, 1, 10), date(2026, 1, 12)}

    def finals(self, sport, day):
        if sport != "nba" or day not in self.game_days:
            return []
        start = (W.snapshot_time(day) + timedelta(hours=3)).isoformat()
        return W.parse_scoreboard({"events": [espn_event("Home A", "Away A", start, 9, 1)]})  # fmt: skip

    def odds(self, key, feed, when, regions):
        assert key == "k" and regions == "us,us_ex" and feed == "basketball_nba"
        self.calls.append(when)
        self.remaining -= W.SNAPSHOT_CREDITS
        start = (when + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        stamp = (when - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        game = feed_game(
            f"g{when:%d}",
            "Home A",
            "Away A",
            start,
            [book("novig", "Home A", "Away A", 0.55, 0.47, updated=stamp)]
            + [
                book(k, "Home A", "Away A", 0.624, 0.416, updated=stamp)
                for k in SPORTSBOOKS
            ],
        )
        return [game], stamp, {"remaining": str(self.remaining)}


def run_pull(feed, tmp_path, max_credits, **more):
    settings = {
        "start": date(2026, 1, 9),
        "remaining": feed.remaining,
        "get_odds": feed.odds,
        "get_finals": feed.finals,
        "sleep": lambda seconds: None,
        "state": tmp_path / "state",
    }
    return W.pull("k", date(2026, 1, 13), max_credits, **{**settings, **more})


def test_a_pull_pays_only_for_game_days_and_carries_on_later(tmp_path):
    feed = Feed()
    rows, summary = run_pull(feed, tmp_path, 20)
    # One paid snapshot fits the cap; every empty day before it was free.
    assert summary["credits_spent_this_run"] == 20 and len(feed.calls) == 1
    assert summary["note"].startswith("stopped: this run's cap")
    assert len(rows) == 2 and set(rows.venue) == {"novig"}
    rows, summary = run_pull(feed, tmp_path, 1000)
    assert len(feed.calls) == 2 and summary["credits_spent_this_run"] == 20
    assert summary["credits_spent_in_all"] == 40 and len(rows) == 4
    assert summary["note"].startswith("finished")
    assert summary["days_done"] == summary["days_in_plan"]
    assert summary["by_sport"]["nba"] == {
        "days_pulled": 2, "games_in_window": 2, "no_result_found": 0, "ties": 0,
    }  # fmt: skip
    # A third run finds nothing left and spends nothing.
    rows, summary = run_pull(feed, tmp_path, 1000)
    assert len(feed.calls) == 2 and summary["credits_spent_this_run"] == 0
    assert len(rows) == 4
    # The rows live only in the cache folder, never under outputs/.
    assert (tmp_path / "state/rows.csv").exists()
    result = W.score(rows)
    assert result["value"]["novig"]["value 4"]["all"]["bets"] == 2  # fair 60, paid 55


def test_a_pull_never_draws_the_shared_key_below_the_floor(tmp_path):
    feed = Feed(remaining=W.MIN_REMAINING + 25)
    rows, summary = run_pull(feed, tmp_path, 1000)
    assert len(feed.calls) == 1  # the second would leave fewer than the floor
    assert "credits would be left" in summary["note"]
    assert summary["credits_remaining"] == W.MIN_REMAINING + 5


def test_a_pull_stops_when_a_source_keeps_failing(tmp_path):
    feed = Feed()

    def refused(*args):
        raise books.BooksError("odds api: HTTP 422 out of range")

    rows, summary = run_pull(feed, tmp_path, 1000, get_odds=refused)
    assert rows.empty and summary["credits_spent_this_run"] == 0
    # Two refused days: not enough to stop, and not marked done, so a later
    # run tries them again.
    assert summary["note"] == (
        "went through the plan: 2 days could not be read; run again"
    )
    done = json.loads((tmp_path / "state/done.json").read_text())
    assert all(d["credits"] == 0 for d in done.values())
    assert "nba|2026-01-10" not in done and "nba|2026-01-12" not in done
    assert summary["days_done"] == summary["days_in_plan"] - 2

    def broken(sport, day):
        raise OSError("down")

    rows, summary = W.pull(
        "k", date(2026, 1, 13), 1000, start=date(2026, 1, 9), get_odds=feed.odds,
        get_finals=broken, sleep=lambda s: None, state=tmp_path / "other",
    )  # fmt: skip
    assert "ESPN's scoreboard kept failing" in summary["note"] and not feed.calls


def test_a_pull_stops_at_its_time_budget(tmp_path):
    feed = Feed()
    ticks = iter([0, 0, W.TIME_BUDGET_SECONDS + 1, W.TIME_BUDGET_SECONDS + 2])
    rows, summary = run_pull(feed, tmp_path, 1000, clock=lambda: next(ticks))
    assert summary["note"] == "stopped: out of time for one run"


# --- the probe -----------------------------------------------------------------


def test_probe_dates_are_second_saturdays_in_season():
    times = W.probe_times("nba", date(2026, 11, 22))
    assert times[0] == datetime(2024, 11, 9, 15, 0, tzinfo=UTC)
    assert times[-1] == datetime(2026, 11, 14, 15, 0, tzinfo=UTC)
    assert all(t.weekday() == 5 and 8 <= t.day <= 14 for t in times)
    assert {t.month for t in times} == set(W.SPORTS["nba"]["probe"])
    total = sum(len(W.probe_times(s, date(2026, 11, 22))) for s in W.SPORTS)
    assert total * W.PROBE_CREDITS == 720  # the cost quoted in the research log
    # This month's Saturday is used only once it is in the past.
    assert W.probe_times("nba", date(2026, 11, 14))[-1].month == 4


def test_the_probe_counts_prices_and_reads_no_results():
    asked = []

    def odds(key, feed, when, regions):
        assert regions == "us_ex"
        asked.append((feed, when))
        if feed == "basketball_wncaab":
            raise books.BooksError("odds api: HTTP 422 no data for this sport")
        if when < datetime(2025, 10, 1, tzinfo=UTC):
            return [], when.strftime("%Y-%m-%dT%H:%M:%SZ"), {"remaining": "70000"}
        stamp = when.strftime("%Y-%m-%dT%H:%M:%SZ")
        soon = (when + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        past = (when - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        games = [
            feed_game("1", "A", "B", soon, [book("novig", "A", "B", 0.52, 0.5, stamp)]),
            feed_game("2", "C", "D", soon, [book("novig", "C", "D", 0.6, 0.44, past)]),
            feed_game("3", "E", "F", past, [book("prophetx", "E", "F", 0.5, 0.5)]),
        ]
        return games, stamp, {"remaining": "70000"}

    report = W.probe("k", date(2026, 11, 22), 5000, remaining=70_000, get_odds=odds)
    assert report["note"] == "finished" and len(asked) == 72
    assert report["credits_spent"] == 720 - 11 * W.PROBE_CREDITS  # refused: free
    seen = report["first_month_priced"]
    assert seen["nba"]["novig"] == "2025-11" and seen["nfl"]["novig"] == "2025-10"
    assert seen["nba"]["prophetx"] is None  # its only game had already started
    assert seen["ncaawb"] == dict.fromkeys(W.VENUES)
    row = next(r for r in report["snapshots"] if r["asked_utc"].startswith("2025-11-08"))  # fmt: skip
    assert row["games_ahead"] == 2
    assert row["bookmakers"]["novig"] == {
        "games": 2,
        "updated_in_last_hour": 2,
        "median_width_pct": pytest.approx(3.0),
        "median_age_minutes": pytest.approx(30.0),
    }
    refused = [r for r in report["snapshots"] if "error" in r]
    assert len(refused) == 11 and all(r["sport"] == "ncaawb" for r in refused)
    text = W.render_probe(report)
    assert "| NBA | 2025-11 | never |" in text and "refused" in text
    assert math.isfinite(json.loads(json.dumps(W.clean(report)))["credits_spent"])


def test_the_probe_respects_its_cap_and_the_floor():
    def odds(key, feed, when, regions):
        return [], None, {"remaining": "50000"}

    report = W.probe("k", date(2026, 11, 22), 25, get_odds=odds)
    assert report["credits_spent"] == 20 and "cap of 25" in report["note"]
    low = W.probe("k", date(2026, 11, 22), 5000, remaining=W.MIN_REMAINING + 5, get_odds=odds)  # fmt: skip
    assert low["credits_spent"] == 0 and "credits would be left" in low["note"]


# --- what may be committed, and who may spend ----------------------------------


def test_raw_odds_stay_in_the_cache_and_out_of_the_repository():
    source = (ROOT / "research/exchange_winners.py").read_text("utf-8")
    assert "to_csv(OUT" not in source and 'STATE = Path("state/exchange_winners")' in source  # fmt: skip
    ignored = (ROOT / ".gitignore").read_text("utf-8").splitlines()
    assert "/state/" in ignored
    # The job caches the rows and commits only the tables.
    assert "path: state/exchange_winners" in WORKFLOW
    assert "git add -A outputs/exchange_winners" in WORKFLOW
    assert "git add -A ." not in WORKFLOW and "git add state" not in WORKFLOW
    assert "upload-artifact" not in WORKFLOW  # an artifact here would be public


def test_only_the_owner_can_start_it_and_it_never_runs_by_itself():
    assert "workflow_dispatch:" in WORKFLOW
    assert "schedule:" not in WORKFLOW and "workflow_run:" not in WORKFLOW
    assert "github.ref == 'refs/heads/main'" in WORKFLOW
    assert "github.actor == 'akilatrades'" in WORKFLOW
    assert "github.triggering_actor == 'akilatrades'" in WORKFLOW
    # Inputs reach the shell as environment values, never pasted into the script.
    run_step = WORKFLOW.split("- name: Run", 1)[1].split("- uses:", 1)[0]
    assert "${{ inputs." not in run_step.split("run: |", 1)[1]
    assert WORKFLOW.count("secrets.ODDS_API_KEY") == 1
    assert "secrets.ODDS_API_KEY" in run_step
    assert 'default: "800"' in WORKFLOW and "default: probe" in WORKFLOW


def test_no_order_or_account_code_is_touched():
    import ast

    tree = ast.parse((ROOT / "research/exchange_winners.py").read_text("utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported |= {f"{node.module}.{alias.name}" for alias in node.names}
    project = ("kalshi", "live", "markets", "tools", "research")
    ours = {name for name in imported if name.split(".")[0] in project}
    # The odds-feed reader, the statistics helper and a plain web GET. No
    # Kalshi client, no order code, nothing from live/.
    assert ours == {
        "kalshi.books",
        "kalshi.stats.clustered_mean_t",
        "markets.nba.live.get_json",
    }
