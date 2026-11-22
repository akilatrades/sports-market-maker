"""Game winners on Novig and ProphetX: what past prices cost, and whether a
price better than the sportsbooks' paid (RESEARCH_LOG.md, 2026-11-22, "Game
winners on Novig and ProphetX, a backtest").

Research only. It places no bet, reads no account and touches no live bot.
There is no model here that picks winners: the rules need none.

Past prices come from The Odds API's historical snapshots (sportsbooks in
``us``, exchanges in ``us_ex``); results come from ESPN's free scoreboard.

    python -m research.exchange_winners probe      # how far back do prices go?
    python -m research.exchange_winners backtest --max-credits 6000
    python -m research.exchange_winners score      # no credits: the cache again
    python -m research.exchange_winners results    # no credits: ESPN again, then score

- ``probe``: one past snapshot a month and sport, exchanges only (10 credits
  each, about 720 in all). Counts games priced and how wide the prices are.
  Reads no results.
- ``backtest``: one snapshot a day and sport (20 credits), in a fixed
  shuffled order, until the credit cap; then scores everything pulled so
  far. A day with no game in the window is found from ESPN first and costs
  nothing. A later run carries on where the last one stopped.

Raw odds are licensed and never committed. A row for each game, exchange and
team stays in ``state/exchange_winners/`` (an Actions cache, git-ignored),
with the team names, so results can be matched again without paying for the
odds twice; only counts, averages and tables go to
``outputs/exchange_winners/``.
"""

import argparse
import json
import math
import random
import re
import sys
import time
import unicodedata
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi import books
from kalshi.stats import clustered_mean_t
from markets.nba.live import get_json

OUT = Path("outputs/exchange_winners")
STATE = Path("state/exchange_winners")  # an Actions cache; never committed
ESPN = "https://site.api.espn.com/apis/site/v2/sports"

# --- the plan, fixed before any data (RESEARCH_LOG.md, 2026-11-22) -------------
START = date(2025, 9, 1)
SEED = 20261122
EXCHANGES = ("novig", "prophetx")  # the test
REFERENCE = ("kalshi", "polymarket_us")  # shown beside them, for cost only
VENUES = EXCHANGES + REFERENCE
VENUE_NAMES = {
    "novig": "Novig",
    "prophetx": "ProphetX",
    "kalshi": "Kalshi",
    "polymarket_us": "Polymarket US",
}
# Every key in the feed's exchange group. None of them is a sportsbook.
NOT_SPORTSBOOKS = frozenset(
    {
        "betopenly",
        "kalshi",
        "limitless",
        "novig",
        "polymarket",
        "polymarket_us",
        "prophetx",
    }
)
# months: the days the backtest may draw. probe: months certain to have games.
SPORTS = {
    "nfl": {
        "label": "NFL",
        "feed": "americanfootball_nfl",
        "espn": "football/nfl",
        "groups": None,
        "months": (9, 10, 11, 12, 1, 2),
        "probe": (9, 10, 11, 12, 1),
    },
    "cfb": {
        "label": "College football",
        "feed": "americanfootball_ncaaf",
        "espn": "football/college-football",
        "groups": 80,  # ESPN's group for the top division; the default is 25 teams
        "months": (8, 9, 10, 11, 12, 1),
        "probe": (9, 10, 11, 12),
    },
    "nba": {
        "label": "NBA",
        "feed": "basketball_nba",
        "espn": "basketball/nba",
        "groups": None,
        "months": (10, 11, 12, 1, 2, 3, 4, 5, 6),
        "probe": (11, 12, 1, 2, 3, 4),
    },
    "ncaamb": {
        "label": "College basketball (men)",
        "feed": "basketball_ncaab",
        "espn": "basketball/mens-college-basketball",
        "groups": 50,  # all of Division I
        "months": (11, 12, 1, 2, 3, 4),
        "probe": (11, 12, 1, 2, 3),
    },
    "ncaawb": {
        "label": "College basketball (women)",
        "feed": "basketball_wncaab",
        "espn": "basketball/womens-college-basketball",
        "groups": 50,
        "months": (11, 12, 1, 2, 3, 4),
        "probe": (11, 12, 1, 2, 3),
    },
    "mlb": {
        "label": "MLB",
        "feed": "baseball_mlb",
        "espn": "baseball/mlb",
        "groups": None,
        "months": (3, 4, 5, 6, 7, 8, 9, 10, 11),
        "probe": (4, 5, 6, 7, 8, 9),
    },
}
# The probe (22 November 2026) found women's college basketball all but absent
# from the feed: at most 6 games a snapshot, none priced by ProphetX and 3 by
# Novig. It is probed but not pulled; a snapshot there would buy nothing.
PULL_SPORTS = tuple(sport for sport in SPORTS if sport != "ncaawb")
WEEKEND_TIME, WEEKDAY_TIME = (15, 30), (21, 0)  # the day's snapshot, UTC
MIN_LEAD, MAX_LEAD = timedelta(minutes=30), timedelta(hours=12)
PRICE_RANGE = (0.02, 0.98)  # an exchange's price for a $1 payout
WIDTH_RANGE = (-0.02, 0.25)  # both prices together, less $1
EXCHANGE_MAX_AGE = timedelta(minutes=60)
BOOK_MAX_AGE = timedelta(minutes=120)
CLOCK_SLACK = timedelta(minutes=5)  # a quote stamped just after its snapshot
MIN_BOOKS = 3
VALUE_RULES = {"value 2": 0.02, "value 4": 0.04}
PASS_T, PASS_BETS, PASS_SPORTS, PASS_SPORT_BETS = 2.0, 300, 4, 30
PRICE_BANDS = ((0.0, 0.30), (0.30, 0.45), (0.45, 0.55), (0.55, 0.70), (0.70, 1.0))
ESPN_NOT_PLAYED_FOR_REAL = (1, 4)  # ESPN season types: preseason, off-season

# --- spending ------------------------------------------------------------------
SNAPSHOT_CREDITS = 20  # 10 a region: sportsbooks and exchanges, one market
PROBE_CREDITS = 10  # exchanges only
MIN_REMAINING = 30_000  # of the plan's 100,000 a month; the NBA bot comes first
TIME_BUDGET_SECONDS = 48 * 60  # the job's own limit is 60 minutes
ESPN_PAUSE_SECONDS = 0.1  # ESPN is free; do not hammer it
MAX_FAILURES_IN_A_ROW = 3
PROBE_FROM = date(2024, 9, 1)
PROBE_HOUR = 15  # UTC, on the second Saturday of the month
# One row for each game, venue and team. Team names and the start are kept so
# that results can be matched again later without paying for the odds twice.
ROW_COLUMNS = [
    "sport",
    "day",
    "game",
    "home",
    "away",
    "start",
    "venue",
    "side",
    "price",
    "fair",
    "books",
    "width",
]
# A full slate in each sport: ESPN must show finished games on these days, or
# the scoreboard reader is broken and nothing may be spent.
CANARY_DAYS = {
    "nfl": date(2025, 12, 14),
    "cfb": date(2025, 10, 11),
    "nba": date(2026, 1, 10),
    "ncaamb": date(2026, 1, 10),
    "mlb": date(2026, 6, 13),
}
CANARY_MIN_GAMES = 3


# --- small helpers -------------------------------------------------------------


def _when(text):
    """An ISO time from either source as an aware UTC datetime, or None."""
    try:
        stamp = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return stamp.astimezone(UTC) if stamp.tzinfo else None


def credits(usage):
    """Credits left on the plan as a number, or None if the feed did not say."""
    try:
        return int(float(usage.get("remaining")))
    except (AttributeError, TypeError, ValueError):
        return None


def clean(value):
    """Strict JSON: numpy numbers become plain ones, NaN becomes null."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if not math.isfinite(value) else round(float(value), 4)
    return value


def write_json(obj, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(obj), indent=1, allow_nan=False) + "\n", "utf-8")


# --- the two sources -----------------------------------------------------------


def historical_odds(key, feed, when, regions):
    """Every game of one sport as the feed showed it at ``when``: (games, the
    snapshot's own time, usage). Costs 10 credits a region."""
    data, usage = books._get(
        f"/historical/sports/{feed}/odds",
        {
            "apiKey": key,
            "regions": regions,
            "markets": "h2h",
            "oddsFormat": "decimal",
            "date": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    if not isinstance(data, dict):
        raise books.BooksError("odds api: historical reply is not an object")
    return data.get("data") or [], data.get("timestamp"), usage


def feed_status(key):
    """(credits left, the feed's sport keys). This request is free."""
    data, usage = books._get("/sports", {"apiKey": key, "all": "true"})
    keys = {s.get("key") for s in data if isinstance(s, dict)}
    return credits(usage), keys


def team_key(name):
    """One spelling for a team from either source: 'Michigan St Spartans' and
    'Michigan State Spartans' are the same, as are 'San José' and 'San Jose'."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = text.encode("ascii", "ignore").decode().lower().replace("&", " and ")
    words = re.sub(r"[^a-z0-9 ]", "", text).split()
    return " ".join("state" if w == "st" and i else w for i, w in enumerate(words))


def parse_scoreboard(payload):
    """ESPN's games for a day: start, the two teams, whether it is final and
    which side won (None: a tie, or not finished)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError("scoreboard has no events list")
    games = []
    for event in payload["events"]:
        try:
            if (event.get("season") or {}).get("type") in ESPN_NOT_PLAYED_FOR_REAL:
                continue
            competition = event["competitions"][0]
            sides = {c["homeAway"]: c for c in competition["competitors"]}
            home, away = sides["home"], sides["away"]
            final = bool(competition["status"]["type"].get("completed"))
            names = [
                c["team"].get("displayName")
                or f"{c['team'].get('location', '')} {c['team'].get('name', '')}"
                for c in (home, away)
            ]
        except (KeyError, IndexError, TypeError, AttributeError):
            continue
        start = _when(event.get("date"))
        if start is None:
            continue
        winner = None
        if final:
            flags = (home.get("winner") is True, away.get("winner") is True)
            if flags == (True, False):
                winner = "home"
            elif flags == (False, True):
                winner = "away"
            else:
                try:
                    h, a = float(home.get("score")), float(away.get("score"))
                    winner = "home" if h > a else "away" if a > h else None
                except (TypeError, ValueError):
                    final = False  # no winner and no score: not a result
        games.append(
            {
                "start": start,
                "home": team_key(names[0]),
                "away": team_key(names[1]),
                "final": final,
                "winner": winner,
            }
        )
    return games


def espn_day(sport, day, get=get_json):
    """ESPN's scoreboard for one US-Eastern date. Free, no key."""
    spec = SPORTS[sport]
    url = f"{ESPN}/{spec['espn']}/scoreboard?dates={day:%Y%m%d}&limit=500"
    if spec["groups"]:
        url += f"&groups={spec['groups']}"
    return parse_scoreboard(get(url))


def find_result(game, finals):
    """Who won a feed game, in the feed's terms: 'home', 'away', 'tie', or None
    when ESPN has no finished game for it. Both teams must match."""
    home, away = team_key(game.get("home_team")), team_key(game.get("away_team"))
    start = _when(game.get("commence_time"))
    if start is None or not home or not away or home == away:
        return None

    def gap(final):
        return abs(final["start"] - start)

    def nick(key):
        return key.split()[-1]

    exact = [
        f
        for f in finals
        if {f["home"], f["away"]} == {home, away} and gap(f) <= timedelta(hours=3)
    ]
    if exact:
        final = min(exact, key=gap)  # a doubleheader: the game nearest in time
        feed_home_is = "home" if final["home"] == home else "away"
    else:
        # The two sources spell some schools differently (UConn, Connecticut).
        # Both nicknames and the start time must then agree, with one candidate.
        if nick(home) == nick(away):
            return None
        loose = [
            f
            for f in finals
            if {nick(f["home"]), nick(f["away"])} == {nick(home), nick(away)}
            and gap(f) <= timedelta(minutes=90)
        ]
        if len(loose) != 1:
            return None
        final = loose[0]
        feed_home_is = "home" if nick(final["home"]) == nick(home) else "away"
    if not final["final"]:
        return None
    if final["winner"] is None:
        return "tie"
    return "home" if final["winner"] == feed_home_is else "away"


# --- prices --------------------------------------------------------------------


def two_sided(game):
    """{bookmaker: (home price, away price, last update)} for moneylines that
    price both teams. A price is the cost of a $1 payout."""
    home, away = game.get("home_team"), game.get("away_team")
    out = {}
    if not home or not away or home == away:
        return out
    for book in game.get("bookmakers") or []:
        market = next(
            (m for m in book.get("markets") or [] if m.get("key") == "h2h"), None
        )
        if not book.get("key") or market is None:
            continue
        prices = {}
        for outcome in market.get("outcomes") or []:
            price = outcome.get("price")
            if (
                outcome.get("name") in (home, away)
                and isinstance(price, (int, float))
                and not isinstance(price, bool)
                and price > 1
            ):
                prices[outcome["name"]] = 1 / float(price)
        if len(prices) == 2:
            updated = _when(market.get("last_update") or book.get("last_update"))
            out[book["key"]] = (prices[home], prices[away], updated)
    return out


def quotes(game, snapshot):
    """The fresh two-sided moneylines: {bookmaker: (home price, away price)}."""
    out = {}
    for key, (home, away, updated) in two_sided(game).items():
        limit = EXCHANGE_MAX_AGE if key in NOT_SPORTSBOOKS else BOOK_MAX_AGE
        if updated is not None and -CLOCK_SLACK <= snapshot - updated <= limit:
            out[key] = (home, away)
    return out


def fair_home(quoted):
    """(the sportsbooks' fair chance of the home team, how many books): each
    book's margin removed in proportion, then averaged. None under 3 books."""
    fair = [
        home / (home + away)
        for key, (home, away) in quoted.items()
        if key not in NOT_SPORTSBOOKS and home + away >= 1.0
    ]
    return (float(np.mean(fair)) if len(fair) >= MIN_BOOKS else None), len(fair)


def venue_ok(home, away):
    low, high = PRICE_RANGE
    width = home + away - 1
    return (
        low < home < high
        and low < away < high
        and (WIDTH_RANGE[0] <= width <= WIDTH_RANGE[1])
    )


def day_rows(sport, day, games, snapshot):
    """(rows, counts) for one snapshot: a row for each game, venue and team,
    for games in the window that a venue priced. No results here."""
    rows = []
    seen = {"listed": 0, "priced": 0}
    for game in games:
        start = _when(game.get("commence_time"))
        if start is None or not MIN_LEAD < start - snapshot <= MAX_LEAD:
            continue
        seen["listed"] += 1
        quoted = quotes(game, snapshot)
        fair, n_books = fair_home(quoted)
        before = len(rows)
        for venue in VENUES:
            if venue not in quoted or not venue_ok(*quoted[venue]):
                continue
            home, away = quoted[venue]
            for side, price, chance in (
                ("home", home, fair),
                ("away", away, None if fair is None else 1 - fair),
            ):
                rows.append(
                    {
                        "sport": sport,
                        "day": day.isoformat(),
                        "game": f"{sport}:{game.get('id')}",
                        "home": game.get("home_team"),
                        "away": game.get("away_team"),
                        "start": start.isoformat(timespec="minutes"),
                        "venue": venue,
                        "side": side,
                        "price": round(price, 4),
                        "fair": None if chance is None else round(chance, 4),
                        "books": n_books,
                        "width": round(home + away - 1, 4),
                    }
                )
        seen["priced"] += len(rows) > before
    return rows, seen


def with_results(rows, finals):
    """(rows with ``won``, counts by sport). A game with no finished ESPN game
    for both of its teams, or a tie, is dropped and counted."""
    counts = {
        sport: {"games_priced": 0, "with_a_result": 0, "no_result_found": 0, "ties": 0}
        for sport in PULL_SPORTS
    }
    winners = {}
    games = rows.drop_duplicates("game")
    for g in games.itertuples(index=False):
        tally = counts.setdefault(
            g.sport,
            {"games_priced": 0, "with_a_result": 0, "no_result_found": 0, "ties": 0},
        )
        tally["games_priced"] += 1
        result = find_result(
            {"home_team": g.home, "away_team": g.away, "commence_time": g.start},
            finals.get(f"{g.sport}|{g.day}", []),
        )
        if result is None:
            tally["no_result_found"] += 1
        elif result == "tie":
            tally["ties"] += 1
        else:
            tally["with_a_result"] += 1
            winners[g.game] = result
    out = rows[rows.game.isin(winners)].copy()
    out["won"] = (out.side == out.game.map(winners)).astype(int)
    return out, counts


# --- the pull ------------------------------------------------------------------


def snapshot_time(day):
    hour, minute = WEEKEND_TIME if day.weekday() >= 5 else WEEKDAY_TIME
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def plan(start, end, seed=SEED):
    """Every (sport, day) to pull, in the fixed order: each sport's season
    days shuffled, then taken one sport after another."""
    per_sport = {}
    for sport in PULL_SPORTS:
        days = [
            start + timedelta(days=i)
            for i in range((end - start).days + 1)
            if (start + timedelta(days=i)).month in SPORTS[sport]["months"]
        ]
        random.Random(f"{seed}:{sport}").shuffle(days)
        per_sport[sport] = days
    longest = max((len(days) for days in per_sport.values()), default=0)
    return [
        (sport, days[i])
        for i in range(longest)
        for sport, days in per_sport.items()
        if i < len(days)
    ]


def load_state(state=None):
    """(rows, the days done, ESPN's games for each pulled day) from the cache."""
    state = state or STATE
    done, finals, rows = {}, {}, pd.DataFrame(columns=ROW_COLUMNS)
    try:
        done = json.loads((state / "done.json").read_text("utf-8"))
    except (OSError, ValueError):
        done = {}
    try:
        stored = json.loads((state / "finals.json").read_text("utf-8"))
        finals = {
            tag: [{**g, "start": _when(g["start"])} for g in games]
            for tag, games in stored.items()
        }
    except (OSError, ValueError, KeyError, TypeError):
        finals = {}
    try:
        rows = pd.read_csv(state / "rows.csv")
    except (OSError, ValueError):
        pass
    return rows, done, finals


def save_state(rows, done, finals, state=None):
    state = state or STATE
    state.mkdir(parents=True, exist_ok=True)
    rows.to_csv(state / "rows.csv", index=False)
    (state / "done.json").write_text(json.dumps(done, sort_keys=True), "utf-8")
    stored = {
        tag: [{**g, "start": g["start"].isoformat()} for g in games]
        for tag, games in finals.items()
    }
    (state / "finals.json").write_text(json.dumps(stored, sort_keys=True), "utf-8")


def pulled_days(done):
    """The (sport, day) pairs a snapshot was paid for."""
    out = []
    for tag, entry in done.items():
        if entry.get("credits"):
            sport, day = tag.split("|")
            out.append((sport, date.fromisoformat(day)))
    return out


def espn_canary(get_finals=espn_day):
    """Raise unless ESPN shows finished games on a known full day in every
    sport. Free; run before anything is spent."""
    for sport in PULL_SPORTS:
        day = CANARY_DAYS[sport]
        try:
            games = get_finals(sport, day)
        except Exception as error:
            raise books.BooksError(
                f"ESPN's {sport} scoreboard could not be read ({type(error).__name__})"
            ) from error
        finished = sum(1 for g in games if g["final"] and g["winner"])
        if finished < CANARY_MIN_GAMES:
            raise books.BooksError(
                f"ESPN's {sport} scoreboard shows {finished} finished games on "
                f"{day.isoformat()}; expected a full day. Nothing was spent."
            )


def pull(
    key,
    end,
    max_credits,
    *,
    start=START,
    remaining=None,
    get_odds=historical_odds,
    get_finals=espn_day,
    clock=time.monotonic,
    sleep=time.sleep,
    state=None,
):
    """Pull days in the plan's order until the cap, the floor or the time
    budget. Returns (all rows so far, ESPN's games by day, this run's summary)."""
    rows, done, finals = load_state(state)
    fresh, spent, failures, unread = [], 0, 0, 0
    note = "finished: every day in the plan has been pulled"
    began = clock()
    for sport, day in plan(start, end):
        tag = f"{sport}|{day.isoformat()}"
        if tag in done:
            continue
        if clock() - began > TIME_BUDGET_SECONDS:
            note = "stopped: out of time for one run; run again to carry on"
            break
        when = snapshot_time(day)
        try:
            games_that_day = get_finals(sport, day)
            sleep(ESPN_PAUSE_SECONDS)
        except Exception as error:  # ESPN is free; a bad day is left for later
            failures += 1
            if failures >= MAX_FAILURES_IN_A_ROW:
                note = (
                    f"stopped: ESPN's scoreboard kept failing ({type(error).__name__})"
                )
                break
            unread += 1
            continue
        if not any(
            f["final"] and MIN_LEAD < f["start"] - when <= MAX_LEAD
            for f in games_that_day
        ):
            done[tag] = {"listed": 0, "credits": 0}  # nothing to price: no spend
            failures = 0
            continue
        if spent + SNAPSHOT_CREDITS > max_credits:
            note = f"stopped: this run's cap of {max_credits} credits"
            break
        if remaining is not None and remaining - SNAPSHOT_CREDITS < MIN_REMAINING:
            note = f"stopped: fewer than {MIN_REMAINING} credits would be left"
            break
        try:
            games, stamp, usage = get_odds(key, SPORTS[sport]["feed"], when, "us,us_ex")
        except books.BooksError as error:
            failures += 1
            if failures >= MAX_FAILURES_IN_A_ROW:
                note = f"stopped: the odds feed kept refusing ({str(error)[:90]})"
                break
            unread += 1
            continue
        failures = 0
        spent += SNAPSHOT_CREDITS
        left = credits(usage)
        remaining = left if left is not None else remaining
        new, seen = day_rows(sport, day, games, _when(stamp) or when)
        fresh += new
        finals[tag] = games_that_day
        done[tag] = {"credits": SNAPSHOT_CREDITS, **seen}
    if unread and note.startswith("finished"):
        note = f"went through the plan: {unread} days could not be read; run again"
    if fresh:
        rows = pd.concat(
            [rows, pd.DataFrame(fresh, columns=ROW_COLUMNS)], ignore_index=True
        )
    save_state(rows, done, finals, state)
    summary = progress(done, start, end)
    summary.update(
        {"note": note, "credits_spent_this_run": spent, "credits_remaining": remaining}
    )
    return rows, finals, summary


def progress(done, start, end):
    """How far the pull has got, from the days done."""

    def total(sport, field):
        return sum(
            entry.get(field, 0)
            for tag, entry in done.items()
            if tag.startswith(f"{sport}|")
        )

    return {
        "credits_spent_in_all": sum(d.get("credits", 0) for d in done.values()),
        "days_in_plan": len(plan(start, end)),
        "days_done": len(done),
        "by_sport": {
            sport: {
                "days_pulled": total(sport, "credits") // SNAPSHOT_CREDITS,
                "games_in_window": total(sport, "listed"),
                "games_priced": total(sport, "priced"),
            }
            for sport in PULL_SPORTS
        },
    }


def refetch_results(done, get_finals=espn_day, sleep=time.sleep):
    """ESPN's games again for every pulled day. Free."""
    finals = {}
    for sport, day in pulled_days(done):
        finals[f"{sport}|{day.isoformat()}"] = get_finals(sport, day)
        sleep(ESPN_PAUSE_SECONDS)
    return finals


# --- the score -----------------------------------------------------------------


def fees(venue, price, won):
    """Fee for each contract, in dollars. NaN where the rate is not confirmed."""
    price, won = np.asarray(price, dtype=float), np.asarray(won, dtype=float)
    if venue == "novig":
        return np.zeros_like(price)  # none before a game starts
    if venue == "prophetx":
        return 0.02 * (1 - price) * won  # 2% of a winning bet's net winnings
    if venue == "kalshi":
        return 0.07 * price * (1 - price)
    return np.full_like(price, np.nan)


def _line(frame):
    """One group of bets: how many, at what price, and what they made."""
    if frame.empty:
        return {"bets": 0, "games": 0}
    out = {
        "bets": len(frame),
        "games": int(frame.game.nunique()),
        "avg_price_cents": 100 * frame.price.mean(),
        "won_pct": 100 * frame.won.mean(),
        "before_fees_cents": 100 * frame.gross.mean(),
    }
    if frame.pnl.notna().all():
        mean, t = clustered_mean_t(frame.pnl.to_numpy(), frame.game.to_numpy())
        out["after_fees_cents"] = 100 * mean
        out["t"] = t
        out["return_on_stake_pct"] = 100 * frame.pnl.sum() / frame.price.sum()
    return out


def score(rows):
    """The plan's tables from the pulled rows. Historical and simulated: every
    bet is assumed to fill at the shown price."""
    rows = rows.copy()
    for column in ("price", "fair", "width", "won"):
        rows[column] = pd.to_numeric(rows[column], errors="coerce")
    rows["gross"] = rows.won - rows.price
    rows["pnl"] = np.nan
    for venue, index in rows.groupby("venue").groups.items():
        part = rows.loc[index]
        rows.loc[index, "pnl"] = part.gross - fees(venue, part.price, part.won)
    sports = [s for s in SPORTS if (rows.sport == s).any()]
    out = {"cost": {}, "value": {}, "by_price": {}, "verdict": {}}

    # 1. What a bet with no opinion costs: every team at the venue's price.
    for venue in VENUES:
        at = rows[rows.venue == venue]
        table = {}
        for sport in ["all", *sports]:
            part = at if sport == "all" else at[at.sport == sport]
            if part.empty:
                continue
            line = _line(part)
            line.pop("t", None)  # both teams of a game: a cost, not a test
            line["width_pct"] = 100 * part.drop_duplicates("game").width.median()
            line["with_a_fair_price_pct"] = 100 * part.fair.notna().mean()
            table[sport] = line
        out["cost"][venue] = table

    # 2. Value: the exchange's price is under the sportsbooks' fair price.
    for venue in EXCHANGES:
        at = rows[(rows.venue == venue) & rows.fair.notna()]
        out["value"][venue], out["verdict"][venue] = {}, {}
        for rule, edge in VALUE_RULES.items():
            bets = at[at.fair - at.price >= edge - 1e-9]
            table = {"all": _line(bets)}
            for sport in sports:
                table[sport] = _line(bets[bets.sport == sport])
            if len(bets):
                middle = sorted(bets.day)[len(bets) // 2]
                table["first half"] = _line(bets[bets.day < middle])
                table["second half"] = _line(bets[bets.day >= middle])
            out["value"][venue][rule] = table
            pooled = table["all"]
            judged = [
                table[s]
                for s in sports
                if table[s].get("bets", 0) >= PASS_SPORT_BETS
                and "after_fees_cents" in table[s]
            ]
            positive = sum(1 for line in judged if line["after_fees_cents"] > 0)
            checks = {
                "bets": pooled.get("bets", 0),
                "enough_bets": pooled.get("bets", 0) >= PASS_BETS,
                "profit_after_fees": pooled.get("after_fees_cents", 0) > 0,
                "t_at_least_2": (pooled.get("t") or 0) >= PASS_T
                and math.isfinite(pooled.get("t") or math.nan),
                "sports_judged": len(judged),
                "sports_positive": positive,
                "enough_sports_positive": positive >= PASS_SPORTS,
            }
            checks["passes"] = all(
                checks[k]
                for k in (
                    "enough_bets",
                    "profit_after_fees",
                    "t_at_least_2",
                    "enough_sports_positive",
                )
            )
            out["verdict"][venue][rule] = checks

    # 3. Exploratory: every team, by the price paid.
    for venue in EXCHANGES:
        at = rows[rows.venue == venue]
        out["by_price"][venue] = {
            f"{round(100 * low)}-{round(100 * high)}c": _line(
                at[(at.price >= low) & (at.price < high)]
            )
            for low, high in PRICE_BANDS
        }
    return out


# --- the probe -----------------------------------------------------------------


def probe_times(sport, today):
    """15:00 UTC on the second Saturday of each month the sport is certain to
    be playing, from September 2024 to last month."""
    out = []
    year, month = PROBE_FROM.year, PROBE_FROM.month
    while (year, month) <= (today.year, today.month):
        if month in SPORTS[sport]["probe"]:
            first = date(year, month, 1)
            saturday = first + timedelta(days=(5 - first.weekday()) % 7 + 7)
            if saturday < today:
                out.append(
                    datetime(year, month, saturday.day, PROBE_HOUR, 0, tzinfo=UTC)
                )
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def probe_snapshot(games, snapshot):
    """Counts for one past snapshot: games ahead, and for each bookmaker how
    many it priced on both teams, how fresh and how wide. No results."""
    ahead = [
        g
        for g in games
        if (start := _when(g.get("commence_time"))) is not None
        and timedelta(0) < start - snapshot <= timedelta(days=7)
    ]
    per = {}
    for game in ahead:
        for key, (home, away, updated) in two_sided(game).items():
            entry = per.setdefault(key, {"widths": [], "ages": [], "fresh": 0})
            entry["widths"].append(home + away - 1)
            if updated is not None:
                age = (snapshot - updated).total_seconds() / 60
                entry["ages"].append(age)
                entry["fresh"] += -5 <= age <= 60
    return {
        "games_ahead": len(ahead),
        "bookmakers": {
            key: {
                "games": len(entry["widths"]),
                "updated_in_last_hour": entry["fresh"],
                "median_width_pct": 100 * float(np.median(entry["widths"])),
                "median_age_minutes": (
                    float(np.median(entry["ages"])) if entry["ages"] else None
                ),
            }
            for key, entry in sorted(per.items())
        },
    }


def probe(key, today, max_credits, *, remaining=None, get_odds=historical_odds):
    """One exchanges-only snapshot a month and sport. Returns the report."""
    rows, spent, note = [], 0, "finished"
    for sport, spec in SPORTS.items():
        for when in probe_times(sport, today):
            if spent + PROBE_CREDITS > max_credits:
                note = f"stopped: this run's cap of {max_credits} credits"
                break
            if remaining is not None and remaining - PROBE_CREDITS < MIN_REMAINING:
                note = f"stopped: fewer than {MIN_REMAINING} credits would be left"
                break
            row = {"sport": sport, "asked_utc": when.isoformat(timespec="minutes")}
            try:
                games, stamp, usage = get_odds(key, spec["feed"], when, "us_ex")
            except books.BooksError as error:
                row["error"] = str(error)[:120]  # a refused request costs nothing
                rows.append(row)
                continue
            spent += PROBE_CREDITS
            left = credits(usage)
            remaining = left if left is not None else remaining
            snapshot = _when(stamp) or when
            row["snapshot_utc"] = snapshot.isoformat(timespec="minutes")
            row.update(probe_snapshot(games, snapshot))
            rows.append(row)
        else:
            continue
        break
    first_seen = {}
    for sport in SPORTS:
        first_seen[sport] = {}
        for venue in VENUES:
            months = [
                r["asked_utc"][:7]
                for r in rows
                if r["sport"] == sport
                and r.get("bookmakers", {}).get(venue, {}).get("games", 0) > 0
            ]
            first_seen[sport][venue] = min(months) if months else None
    return {
        "note": note,
        "credits_spent": spent,
        "credits_remaining": remaining,
        "first_month_priced": first_seen,
        "snapshots": rows,
    }


# --- reports -------------------------------------------------------------------


def _cents(value):
    return "" if value is None else f"{value:+.1f}¢"


def render_probe(report):
    lines = [
        "# Novig and ProphetX game winners: how far back the feed's prices go",
        "",
        f"{report['note']}. Credits spent: {report['credits_spent']}.",
        "Counts only: no results were read.",
        "",
        "## First month with a game priced on both teams",
        "",
        "| Sport | " + " | ".join(VENUE_NAMES[v] for v in VENUES) + " |",
        "|---|" + "---|" * len(VENUES),
    ]
    for sport, spec in SPORTS.items():
        seen = report["first_month_priced"].get(sport, {})
        cells = " | ".join(seen.get(v) or "never" for v in VENUES)
        lines.append(f"| {spec['label']} | {cells} |")
    lines += [
        "",
        "## Each snapshot (games priced on both teams; median width)",
        "",
        "| Sport | Snapshot (UTC) | Games ahead | "
        + " | ".join(VENUE_NAMES[v] for v in VENUES)
        + " |",
        "|---|---|---:|" + "---|" * len(VENUES),
    ]
    for row in report["snapshots"]:
        label = SPORTS[row["sport"]]["label"]
        if "error" in row:
            lines.append(f"| {label} | {row['asked_utc']} | refused | | | | |")
            continue
        cells = []
        for venue in VENUES:
            entry = row["bookmakers"].get(venue)
            cells.append(
                f"{entry['games']} ({entry['median_width_pct']:.1f}%)" if entry else "0"
            )
        lines.append(
            f"| {label} | {row['snapshot_utc']} | {row['games_ahead']} | "
            + " | ".join(cells)
            + " |"
        )
    return "\n".join(lines) + "\n"


def render_backtest(result, summary):
    lines = [
        "# Game winners on Novig and ProphetX: backtest",
        "",
        "Historical and simulated: every bet is assumed to fill at the shown",
        "price. Not live results, and not a forecast. The plan and the pass",
        "bar were written first (RESEARCH_LOG.md, 2026-11-22).",
        "",
        f"Pull: {summary['note']}. {summary['days_done']} of "
        f"{summary['days_in_plan']} days done, "
        f"{summary['credits_spent_in_all']} credits in all.",
        "",
        "## Games behind the tables",
        "",
        "| Sport | Days pulled | Games priced | With a result | No result found | Ties |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for sport in PULL_SPORTS:
        days = summary.get("by_sport", {}).get(sport, {}).get("days_pulled", 0)
        m = summary.get("results", {}).get(sport, {})
        lines.append(
            f"| {SPORTS[sport]['label']} | {days} | {m.get('games_priced', 0)} | "
            f"{m.get('with_a_result', 0)} | {m.get('no_result_found', 0)} | "
            f"{m.get('ties', 0)} |"
        )
    lines += [
        "",
        "## What a bet with no opinion costs (every team, every game)",
        "",
        "| Venue | Sport | Games | Width | Before fees | After fees |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for venue in VENUES:
        for sport, line in result["cost"].get(venue, {}).items():
            label = "All" if sport == "all" else SPORTS[sport]["label"]
            lines.append(
                f"| {VENUE_NAMES[venue]} | {label} | {line['games']} | "
                f"{line['width_pct']:.1f}% | {_cents(line['before_fees_cents'])} | "
                f"{_cents(line.get('after_fees_cents'))} |"
            )
    lines += [
        "",
        "## Value: buying a team priced under the sportsbooks' fair price",
        "",
        "| Venue | Rule | Group | Bets | Avg price | Won | After fees | t |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for venue in EXCHANGES:
        for rule, table in result["value"].get(venue, {}).items():
            for group, line in table.items():
                if not line.get("bets"):
                    continue
                label = SPORTS[group]["label"] if group in SPORTS else group.title()
                t = line.get("t")
                lines.append(
                    f"| {VENUE_NAMES[venue]} | {rule} | {label} | {line['bets']} | "
                    f"{line['avg_price_cents']:.0f}¢ | {line['won_pct']:.1f}% | "
                    f"{_cents(line.get('after_fees_cents'))} | "
                    f"{'' if t is None or not math.isfinite(t) else f'{t:+.1f}'} |"
                )
    lines += ["", "## Verdict against the bar", ""]
    for venue in EXCHANGES:
        for rule, checks in result["verdict"].get(venue, {}).items():
            word = "PASSES" if checks["passes"] else "does not pass"
            lines.append(
                f"- {VENUE_NAMES[venue]}, {rule}: **{word}** ({checks['bets']} bets; "
                f"positive in {checks['sports_positive']} of "
                f"{checks['sports_judged']} sports with {PASS_SPORT_BETS}+ bets)."
            )
    lines += [
        "",
        "## Exploratory: every team, by the price paid",
        "",
        "| Venue | Price | Bets | Won | After fees | t |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for venue in EXCHANGES:
        for band, line in result["by_price"].get(venue, {}).items():
            if not line.get("bets"):
                continue
            t = line.get("t")
            lines.append(
                f"| {VENUE_NAMES[venue]} | {band} | {line['bets']} | "
                f"{line['won_pct']:.1f}% | {_cents(line.get('after_fees_cents'))} | "
                f"{'' if t is None or not math.isfinite(t) else f'{t:+.1f}'} |"
            )
    return "\n".join(lines) + "\n"


# --- command line --------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("stage", choices=("probe", "backtest", "score", "results"))
    parser.add_argument(
        "--max-credits", type=int, default=800, help="this run's spending cap"
    )
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    today = now.date()
    end = today - timedelta(days=1)

    try:
        if args.stage == "probe":
            key = books.api_key()
            remaining, listed = feed_status(key)  # free
            report = probe(key, today, args.max_credits, remaining=remaining)
            report["updated_utc"] = now.isoformat(timespec="minutes")
            report["sports_in_feed"] = {
                sport: spec["feed"] in listed for sport, spec in SPORTS.items()
            }
            write_json(report, OUT / "probe.json")
            (OUT / "probe.md").write_text(render_probe(report), "utf-8")
            brief = {k: report[k] for k in ("note", "credits_spent")}
            brief["first_month_priced"] = report["first_month_priced"]
            print("::notice::" + json.dumps(clean(brief)))
            return 0
        if args.stage == "backtest":
            key = books.api_key()
            espn_canary()  # free; stops here if the scoreboard reader is broken
            remaining, _ = feed_status(key)  # free
            rows, finals, summary = pull(
                key, end, args.max_credits, remaining=remaining
            )
        else:
            rows, done, finals = load_state()
            summary = progress(done, START, end)
            summary["note"] = "scored again from the cache; nothing pulled"
            if args.stage == "results":
                finals = refetch_results(done)  # free
                save_state(rows, done, finals)
                summary["note"] = "results read again from ESPN; nothing pulled"
    except books.BooksError as error:
        print(f"::error::exchange winners: {error}")
        return 1

    scored, matched = with_results(rows, finals)
    summary["results"] = matched
    result = score(scored)
    write_json(
        {
            "updated_utc": now.isoformat(timespec="minutes"),
            "kind": "historical, simulated; fills assumed at the shown price",
            "pull": summary,
            "result": result,
        },
        OUT / "backtest.json",
    )
    (OUT / "backtest.md").write_text(render_backtest(result, summary), "utf-8")
    brief = {
        "note": summary["note"],
        "days_done": summary["days_done"],
        "credits_spent_in_all": summary["credits_spent_in_all"],
        "games_with_a_result": sum(m["with_a_result"] for m in matched.values()),
    }
    print("::notice::" + json.dumps(clean(brief)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
