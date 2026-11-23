"""Which other sports have pick'em lines to compare? A one-off, cheap look.

RESEARCH_LOG.md, 2026-11-23, "Pick'em lines in other sports: a probe". For
each sport it takes the next one or two games and asks the odds feed for the
main player-prop markets from the US sportsbooks and the pick'em apps
together. It keeps counts only: how many sportsbooks quote each market, how
many lines PrizePicks and Underdog post, and how many of those sit on a line
a sportsbook also quotes. No odds and no lines are stored, nothing is
priced, and no results are read.

Cost: one credit per market returned per group (sportsbooks, apps) per
game; a market nobody quotes is free. At most MAX_CREDITS in all, and
nothing is spent when fewer than MIN_CREDITS_LEFT remain.

    python -m research.pickem_probe     # needs ODDS_API_KEY
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

OUT = Path("outputs/pickem/probe.json")
REGIONS = "us,us_dfs"
APPS = {"prizepicks": "PrizePicks", "underdog": "Underdog"}
GAMES_PER_SPORT = 2
HOURS_AHEAD = 72
MIN_CREDITS_LEFT = 15_000  # the bot's odds come first
# The feed's sport key -> the main markets to ask about. Tennis is not here:
# the feed lists no tennis player props at all.
SPORTS = {
    "basketball_nba": [  # the combined stats the page does not read yet
        "player_points_rebounds_assists",
        "player_points_rebounds",
        "player_points_assists",
        "player_rebounds_assists",
    ],
    "basketball_ncaab": [
        "player_points",
        "player_rebounds",
        "player_assists",
        "player_threes",
        "player_points_rebounds_assists",
    ],
    "americanfootball_ncaaf": [
        "player_pass_yds",
        "player_rush_yds",
        "player_reception_yds",
        "player_receptions",
        "player_pass_tds",
    ],
    "icehockey_nhl": [
        "player_points",
        "player_assists",
        "player_goals",
        "player_shots_on_goal",
        "player_total_saves",
        "player_blocked_shots",
    ],
    "soccer_epl": ["player_shots", "player_shots_on_target", "player_assists"],
    "soccer_spain_la_liga": [
        "player_shots",
        "player_shots_on_target",
        "player_assists",
    ],
    "soccer_usa_mls": ["player_shots", "player_shots_on_target", "player_assists"],
    "soccer_uefa_champs_league": [
        "player_shots",
        "player_shots_on_target",
        "player_assists",
    ],
}
MAX_CREDITS = 2 * GAMES_PER_SPORT * sum(len(m) for m in SPORTS.values())


def count_event(odds):
    """Counts for one event-odds reply: market -> books, app lines, matches."""
    lines = {}  # market -> group -> set of (player, line)
    books = {}  # market -> set of sportsbook keys
    for book in odds.get("bookmakers", []) or []:
        key = book.get("key")
        for market in book.get("markets", []) or []:
            name = market.get("key")
            quoted = {
                (str(o.get("description")).strip().lower(), float(o["point"]))
                for o in market.get("outcomes", []) or []
                if o.get("description") and o.get("point") is not None
            }
            if not quoted:
                continue
            group = APPS.get(key, "sportsbooks")
            lines.setdefault(name, {}).setdefault(group, set()).update(quoted)
            if key not in APPS:
                books.setdefault(name, set()).add(key)
    out = {}
    for name, groups in sorted(lines.items()):
        priced = groups.get("sportsbooks", set())
        row = {"sportsbooks": len(books.get(name, ())), "sportsbook_lines": len(priced)}
        for app in APPS.values():
            posted = groups.get(app, set())
            row[f"{app}_lines"] = len(posted)
            row[f"{app}_lines_a_sportsbook_also_quotes"] = len(posted & priced)
        out[name] = row
    return out


def add(total, counts):
    """Sum one game's counts into the sport's."""
    for market, row in counts.items():
        into = total.setdefault(market, dict.fromkeys(row, 0))
        for key, value in row.items():
            # Sportsbook counts are per game; keep the most seen in any game.
            into[key] = (
                max(into[key], value) if key == "sportsbooks" else into[key] + value
            )
    return total


def left(usage):
    try:
        return int(float(usage.get("remaining")))
    except (AttributeError, TypeError, ValueError):
        return None


def probe(now, key, events, event_odds):
    """The whole look: one entry per sport. ``events`` and ``event_odds`` are
    the feed's two calls (kalshi.books), passed in so tests can stand in."""
    from kalshi.books import BooksError

    report = {"sports": {}, "credits_before": None, "credits_after": None}
    for sport, markets in SPORTS.items():
        entry = {"asked": markets, "games_listed": 0, "games_asked": 0, "markets": {}}
        report["sports"][sport] = entry
        try:
            listed, usage = events(key, sport=sport)  # free
        except BooksError as error:
            entry["note"] = f"not listed by the feed: {str(error)[:80]}"
            continue
        remaining = left(usage)
        if report["credits_before"] is None:
            report["credits_before"] = remaining
        if remaining is not None and remaining < MIN_CREDITS_LEFT:
            report["note"] = f"stopped: fewer than {MIN_CREDITS_LEFT} credits left"
            break
        entry["games_listed"] = len(listed)
        soon = sorted(
            (e for e in listed if now < _time(e) <= now + timedelta(hours=HOURS_AHEAD)),
            key=_time,
        )
        # The games nearest tip-off are the likeliest to have props posted.
        for event in soon[:GAMES_PER_SPORT]:
            try:
                odds, usage = event_odds(
                    key, event["id"], sport=sport, markets=markets, regions=REGIONS
                )
            except BooksError as error:
                entry["note"] = f"a game could not be read: {str(error)[:80]}"
                continue
            entry["games_asked"] += 1
            add(entry["markets"], count_event(odds))
            report["credits_after"] = left(usage)
        if not soon:
            entry["note"] = f"no game in the next {HOURS_AHEAD} hours"
    before, after = report["credits_before"], report["credits_after"]
    if before is not None and after is not None:
        report["credits_spent"] = before - after
    return report


def _time(event):
    return datetime.fromisoformat(str(event["commence_time"]).replace("Z", "+00:00"))


def main():
    from kalshi.books import BooksError, api_key, event_odds, events

    now = datetime.now(UTC)
    try:
        report = probe(now, api_key(), events, event_odds)
    except BooksError as error:
        print(f"::error::pick'em probe: {error}")
        return 1
    report = {"probed_utc": now.isoformat(timespec="minutes"), **report}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1) + "\n", "utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
