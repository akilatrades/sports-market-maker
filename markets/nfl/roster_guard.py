"""NFL team membership and availability from current ESPN roster snapshots.

Public read-only roster checks are *not* official 90-minute game-day inactives.
A missing, stale, ambiguous, or unrecognized roster entry must never authorize
a new NFL demo order. Cache is intentionally short-lived and stored off GitHub.
"""

import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path

from markets.nfl.kalshi import normalize_name

ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams"
CACHE = Path("/tmp/smm-nfl-rosters-cache.json")
CACHE_MINUTES = 20
BAD_STATUS = (
    "inactive",
    "injured",
    "reserve",
    "suspend",
    "out",
    "doubtful",
    "questionable",
    "pup",
    "non-football",
)
ALIASES = {
    "JAC": "JAX",
    "WSH": "WAS",
    "LAR": "LA",
    "STL": "LA",
    "OAK": "LV",
    "SD": "LAC",
}
ESPN_CODES = {"LA": "lar", "WAS": "wsh"}


def canonical(team):
    return ALIASES.get(str(team).upper(), str(team).upper())


def _status(record):
    fields = [record.get("status"), record.get("injuryStatus")]
    for item in record.get("injuries") or []:
        if isinstance(item, dict):
            fields.extend([item.get("status"), item.get("type")])
    strings = []

    def visit(value):
        if isinstance(value, str):
            strings.append(value.lower())
        elif isinstance(value, dict):
            for k in ("name", "displayName", "description", "type", "abbreviation"):
                visit(value.get(k))

    for field in fields:
        visit(field)
    if record.get("active") is False:
        strings.append("inactive")
    return " ".join(strings)


def parse_roster(payload):
    """Map normalized player names to availability; duplicate names are unsafe."""
    groups = payload.get("athletes")
    if not isinstance(groups, list) or not groups:
        raise ValueError("Empty or unrecognized ESPN NFL roster")
    players = {}
    for group in groups:
        entries = group.get("items", []) if isinstance(group, dict) else []
        for item in entries:
            if not isinstance(item, dict):
                continue
            item = item.get("athlete", item)
            name = item.get("displayName") or item.get("fullName")
            if not name:
                continue
            key = normalize_name(name)
            status = _status(item)
            eligible = not any(word in status for word in BAD_STATUS)
            if key in players:  # Ambiguous identity: never infer which one.
                players[key] = False
            else:
                players[key] = eligible
    if not players:
        raise ValueError("No named athletes in ESPN NFL roster")
    return players


def _one(team, fetch=None):
    code = ESPN_CODES.get(team, team.lower())
    url = f"{ESPN}/{code}/roster"
    if fetch is None:

        def fetch(url):
            request = urllib.request.Request(
                url, headers={"User-Agent": "smm-roster-research/1.0"}
            )
            with urllib.request.urlopen(request, timeout=7) as response:
                return json.load(response)

    return parse_roster(fetch(url))


def current_rosters(teams, now=None, cache=CACHE, fetch=None):
    """Get current team rosters. Raise on incomplete coverage (fail closed)."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("Current time must be timezone aware")
    teams = sorted({canonical(t) for t in teams})
    if not teams:
        return {}
    cache = Path(cache)
    try:
        saved = json.loads(cache.read_text())
        fetched_at = datetime.fromisoformat(saved["fetched_utc"])
        if (
            fetched_at.tzinfo is not None
            and timedelta(0) <= now - fetched_at <= timedelta(minutes=CACHE_MINUTES)
            and all(t in saved["teams"] for t in teams)
        ):
            return {t: saved["teams"][t] for t in teams}
    except (OSError, ValueError, KeyError, TypeError):
        pass

    found = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        tasks = {executor.submit(_one, team, fetch): team for team in teams}
        for future in as_completed(tasks):
            team = tasks[future]
            try:
                found[team] = future.result()
            except (OSError, ValueError, TypeError, KeyError) as error:
                raise ValueError(
                    f"ESPN roster unavailable for {team}: {type(error).__name__}"
                ) from error

    cache.parent.mkdir(parents=True, exist_ok=True)
    # Atomically replace. Never silently use a stale roster following API errors.
    payload = {"fetched_utc": now.isoformat(), "teams": found}
    temp = cache.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, sort_keys=True) + "\n")
    temp.replace(cache)
    return found


def event_teams(event_ticker, game_date, games):
    """Identify both teams from the exact Kalshi game ticker and nflverse schedule."""
    try:
        suffix = str(event_ticker).split("-", 1)[1]
        match = re.fullmatch(r"\d{2}[A-Z]{3}\d{1,2}([A-Z]+)", suffix)
        if not match:
            return None
        pair = match.group(1)
    except (IndexError, AttributeError):
        return None
    needed = {"gameday", "away_team", "home_team", "season", "week"}
    if not needed.issubset(games.columns):
        return None
    day_games = games[games.gameday.astype(str).eq(str(game_date))]
    possibilities = []
    for game in day_games.itertuples():
        away, home = canonical(game.away_team), canonical(game.home_team)
        a = {
            away,
            "LAR" if away == "LA" else away,
            "WSH" if away == "WAS" else away,
            "JAC" if away == "JAX" else away,
        }
        h = {
            home,
            "LAR" if home == "LA" else home,
            "WSH" if home == "WAS" else home,
            "JAC" if home == "JAX" else home,
        }
        if any(pair == x + y for x in a for y in h):
            possibilities.append((away, home, int(game.season), int(game.week)))
    return possibilities[0] if len(possibilities) == 1 else None


def verified_kickoff(game, game_date, games):
    """Exact NFL fixture kickoff in UTC; never use Kalshi market occurrence time.

    The exchange occurrence timestamp can reflect market expiration/settlement
    rather than actual kickoff. Return None on missing/ambiguous schedule data
    so a trader cannot enter late or leave a new order past the game start.
    """
    needed = {"gameday", "gametime", "away_team", "home_team", "season", "week"}
    if game is None or not needed.issubset(games.columns):
        return None
    away, home, season, week = game
    fixtures = games.loc[
        games.gameday.astype(str).eq(str(game_date))
        & games.away_team.map(canonical).eq(away)
        & games.home_team.map(canonical).eq(home)
        & games.season.eq(season)
        & games.week.eq(week)
    ]
    if len(fixtures) != 1:
        return None
    clock = fixtures.iloc[0].gametime
    if not isinstance(clock, str) or not re.fullmatch(r"\d{1,2}:\d{2}", clock):
        return None
    import pandas as pd

    local = pd.to_datetime(
        f"{game_date} {clock}", format="%Y-%m-%d %H:%M", errors="coerce"
    )
    if pd.isna(local):
        return None
    try:
        utc = local.tz_localize(
            "America/New_York", ambiguous="NaT", nonexistent="NaT"
        ).tz_convert("UTC")
    except (TypeError, ValueError):
        return None
    return None if pd.isna(utc) else utc


def availability(player, game, rosters, injuries):
    """Return (team, reason): reason '' only for unambiguous, eligible player."""
    away, home, season, week = game
    key = normalize_name(player)
    matches = [(t, rosters[t][key]) for t in (away, home) if key in rosters.get(t, {})]
    if len(matches) != 1:
        return None, "unverified-roster-or-ambiguous-team"
    team, active = matches[0]
    if not active:
        return team, "ESPN-inactive-or-questionable"
    report = injuries[
        (injuries.season == season)
        & (injuries.week == week)
        & injuries.team.map(canonical).eq(team)
        & injuries.full_name.map(normalize_name).eq(key)
    ]
    if any(
        str(s).strip().lower() in ("out", "doubtful", "questionable", "inactive")
        for s in report.report_status.dropna()
    ):
        return team, "injury-report-out-or-questionable"
    return team, ""
