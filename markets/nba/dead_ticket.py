"""Late-game "dead tickets": props whose line is out of reach, or already won.

Pure rules and parsers for the read-only watcher
(`research/dead_ticket_watch.py`; RESEARCH_LOG.md, 2026-11-16, "Dead-ticket
watch"). Nothing here trades or reads an account.

Out of reach: the player still needs more than a generous ceiling on what
can be produced in the game time left: a rate per minute plus a fixed
allowance (`CEILING`). The strict rule adds five minutes for an overtime
that may still come; the loose rule counts regulation only.
"""

import math
import re

STATS = {
    "KXNBAPTS": "points",
    "KXNBAREB": "rebounds",
    "KXNBAAST": "assists",
    "KXNBA3PT": "threes",
}
# (per minute of game time left, fixed allowance). Fixed before the
# exploratory replay; do not tune on watcher data.
CEILING = {
    "points": (1.5, 3.0),
    "rebounds": (0.5, 2.0),
    "assists": (0.5, 2.0),
    "threes": (1.0 / 3.0, 2.0),
}
OVERTIME_MINUTES = 5.0
MAX_MINUTES_LEFT = 24.0  # second half only
# ESPN abbreviation -> Kalshi's three letters, where they differ.
ESPN_TO_KALSHI = {
    "GS": "GSW",
    "NY": "NYK",
    "SA": "SAS",
    "NO": "NOP",
    "UTAH": "UTA",
    "WSH": "WAS",
}
SUFFIX = re.compile(r"\b(Jr\.?|Sr\.?|II|III|IV|V)\b")
TICKER = re.compile(
    r"^(KXNBA(?:PTS|REB|AST|3PT))-(\d{2}[A-Z]{3}\d{2})([A-Z]{3})([A-Z]{3})"
    r"-([A-Z]{3})([A-Z]+?)(\d*)-(\d+)$"
)


def kalshi_team(abbreviation):
    text = str(abbreviation or "").upper()
    return ESPN_TO_KALSHI.get(text, text)


def player_key(name):
    """'Shai Gilgeous-Alexander' -> 'SGILGEOUSALEXANDER' (first initial plus
    the rest of the name, letters only), as Kalshi writes it in tickers."""
    parts = SUFFIX.sub("", str(name or "")).split()
    if len(parts) < 2:
        return None
    rest = re.sub("[^A-Za-z]", "", "".join(parts[1:]))
    return (parts[0][0] + rest).upper() if rest else None


def parse_ticker(ticker):
    """KXNBAPTS-26NOV14BKNMEM-BKNDWOLF2-20 -> stat, game, team, player key
    and the whole number the player must reach. None when it does not fit."""
    match = TICKER.match(str(ticker or ""))
    if not match:
        return None
    series, day, away, home, team, key, _jersey, line = match.groups()
    if team not in (away, home):
        return None
    return {
        "stat": STATS[series],
        "series": series,
        "game": day + away + home,
        "team": team,
        "key": key,
        "line": int(line),
    }


def minutes_left(period, clock_seconds):
    """Game minutes left in regulation, or in the current overtime."""
    period, clock = int(period), max(float(clock_seconds), 0.0)
    if period < 1:
        raise ValueError("period must be at least 1")
    if period <= 4:
        return (4 - period) * 12.0 + min(clock, 720.0) / 60.0
    return min(clock, 300.0) / 60.0


def ceiling(stat, minutes, overtime=True):
    rate, allowance = CEILING[stat]
    return rate * (minutes + (OVERTIME_MINUTES if overtime else 0.0)) + allowance


def out_of_reach(stat, need, minutes, overtime=True):
    """True when ``need`` more of ``stat`` is beyond the ceiling for the game
    time left. Only in the second half, and never for a line already met."""
    if not math.isfinite(need) or not math.isfinite(minutes):
        return False
    if need < 1 or minutes < 0 or minutes > MAX_MINUTES_LEFT:
        return False
    return need > ceiling(stat, minutes, overtime)


def _made(value):
    """ESPN writes shooting as 'made-attempted'; plain numbers pass through."""
    text = str(value).strip()
    number = text.split("-")[0] if "-" in text[1:] else text
    return float(number)


def clock_seconds(status):
    """Seconds left in the period from ESPN's status: the numeric clock, or
    the displayed one ('5:32', '32.1')."""
    try:
        return float(status["clock"])
    except (KeyError, TypeError, ValueError):
        text = str(status["displayClock"]).strip()
        minutes, _, seconds = text.rpartition(":")
        return (float(minutes) if minutes else 0.0) * 60 + float(seconds)


def parse_summary(payload, board_status=None):
    """ESPN game summary -> the state the rules need, or None when the game
    is not in progress or the payload is not as expected.

    The summary's own status may carry only the game's state; the period and
    clock then come from ``board_status``, the same game's status on the
    scoreboard.

    {"game": "26NOV14BKNMEM", "period", "clock_seconds", "minutes_left",
     "margin" (absolute score gap), "players": {(team, key): {stat: n}}}
    Two players of one team with the same key are dropped (ambiguous).
    """
    try:
        competition = payload["header"]["competitions"][0]
        status = competition.get("status") or {}
        board = board_status or {}
        state = (status.get("type") or board.get("type") or {}).get("state")
        if state != "in":
            return None
        timing = status if "period" in status else board
        period = int(timing["period"])
        clock = clock_seconds(timing)
        sides = {c["homeAway"]: c for c in competition["competitors"]}
        home = kalshi_team(sides["home"]["team"]["abbreviation"])
        away = kalshi_team(sides["away"]["team"]["abbreviation"])
        margin = abs(float(sides["home"]["score"]) - float(sides["away"]["score"]))
        blocks = payload["boxscore"]["players"]
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    players, seen = {}, set()
    for block in blocks:
        try:
            team = kalshi_team(block["team"]["abbreviation"])
            table = block["statistics"][0]
            labels = [str(x).upper() for x in table.get("labels") or table["names"]]
            index = {name: labels.index(name) for name in ("PTS", "REB", "AST", "3PT")}
            athletes = table["athletes"]
        except (KeyError, IndexError, TypeError, ValueError):
            return None
        for athlete in athletes:
            key = player_key((athlete.get("athlete") or {}).get("displayName"))
            stats = athlete.get("stats") or []
            if key is None:
                continue
            if (team, key) in seen:
                players.pop((team, key), None)
                continue
            seen.add((team, key))
            if not stats:  # did not play (yet): nothing so far
                row = dict.fromkeys(CEILING, 0.0)
            else:
                try:
                    row = {
                        "points": _made(stats[index["PTS"]]),
                        "rebounds": _made(stats[index["REB"]]),
                        "assists": _made(stats[index["AST"]]),
                        "threes": _made(stats[index["3PT"]]),
                    }
                except (IndexError, ValueError):
                    continue
            players[(team, key)] = row
    return {
        "home": home,
        "away": away,
        "period": period,
        "clock_seconds": clock,
        "minutes_left": minutes_left(period, clock),
        "margin": margin,
        "players": players,
    }


def taker_fee_cents(price, contracts=10):
    """Kalshi's taker fee per contract in cents, rounded up to the cent on
    an order of ``contracts`` (0.07 x contracts x P x (1 - P))."""
    total = math.ceil(0.07 * contracts * price * (1 - price) * 100 - 1e-9)
    return total / contracts
