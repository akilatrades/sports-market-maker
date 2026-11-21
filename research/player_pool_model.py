"""The stat model's price for every open Kalshi NBA prop, for the player-pool page.

The projections job prices the props a few times a day, hours apart. The
page wants the same numbers more often, so the player-pool workflow runs
this every quarter of an hour while its price watcher is up.

It calls the projections job's own pricing function
(live.nba_projections.price_markets) on the same public inputs: box scores,
Kalshi's open markets, and ESPN's schedule, betting lines and injury report.
It writes one file, outputs/player_pool/model.json, and nothing the
projections job writes: no projections file, no paper ledger, no bet card.
No keys, no account, no orders.

One input differs from the projections job (RESEARCH_LOG.md, 2026-11-21,
"a returning regular and his stand-ins"): who is out. The injury feed can
keep an old "Out" on a player who has since been upgraded, so for the games
being priced a player on the league's official injury report takes that
report's status (``reconcile``). If the official report cannot be read, the
feed is used alone and the file says so. This is for the page only; the
projections job and the bots' inputs are unchanged.

    python -m live.fetch_nba_data
    python -m research.player_pool_model
"""

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from kalshi.api import snapshot
from live.nba_projections import player_ids, price_markets
from markets.nba import official_injuries
from markets.nba.kalshi import SERIES, normalize_name, parse
from markets.nba.live import injuries, scoreboard
from research.nba_player_pool_dashboard import SLATE_COLUMNS, slate_file

OUT = Path("outputs/player_pool/model.json")
DAYS_AHEAD = 3  # today and the next two days, as the projections job reads
OFFICIAL_SECONDS = 25  # at most this long is spent fetching the league's report
OFFICIAL_OUT = {"Out", "Doubtful"}
OFFICIAL_PLAYING = {"Questionable", "Probable", "Available"}


def official_report(now):
    """The league's newest injury report as a table, or None if it cannot be read."""
    try:
        _, table = official_injuries.report_at(
            now, deadline=time.monotonic() + OFFICIAL_SECONDS
        )
    except (ValueError, OSError) as error:  # ReportError is a ValueError
        print(f"::warning::official injury report not read: {type(error).__name__}")
        return None
    return table


def reconcile(report, official, schedule, players):
    """The injury feed's report with the league's official report laid over it.

    For the games in ``schedule`` only, and only for players the official
    report lists by name: Out or Doubtful means not playing, anything else
    means expected to play, whatever the feed says. Everyone else keeps the
    feed's status. A name that does not identify exactly one player on that
    team is left alone. Returns (report, changes); each change records what
    the feed said and what the official report says.
    """
    if official is None or official.empty or schedule.empty:
        return report, []
    eastern = schedule.tip_utc.dt.tz_convert("America/New_York").dt.strftime("%m/%d/%Y")
    games = set(zip(schedule.home, eastern)) | set(zip(schedule.away, eastern))
    listed = official_injuries.for_games(official, games)
    listed = listed[listed.status.isin(OFFICIAL_OUT | OFFICIAL_PLAYING)]
    listed = listed[listed.player_key.astype(bool)].drop_duplicates(
        ["team_espn", "player_key"], keep="last"
    )
    known = player_ids(players)
    report = report.copy()
    feed = report.dropna(subset=["player_id"]).drop_duplicates("player_id")
    feed = feed.set_index(feed.player_id.astype("int64"))
    changes, added = [], []
    for row in listed.itertuples():
        if row.player_key not in known.index:
            continue
        match = known.loc[row.player_key]
        if match.team != row.team_espn:
            continue
        player_id, out = int(match.player_id), row.status in OFFICIAL_OUT
        was = feed.loc[player_id] if player_id in feed.index else None
        if (bool(was.out) if was is not None else False) == out:
            continue
        changes.append(
            {
                "player": match.player,
                "team": row.team_espn,
                "feed": was.status if was is not None else None,
                "official": row.status,
            }
        )
        if was is None:
            added.append(
                {
                    "team": row.team_espn,
                    "player_id": player_id,
                    "player": match.player,
                    "status": row.status,
                    "comment": "official injury report",
                    "updated": None,
                    "out": out,
                }
            )
        else:
            mine = report.player_id == player_id
            report.loc[mine, "out"] = out
            report.loc[mine, "status"] = row.status
    if added:
        report = pd.concat([report, pd.DataFrame(added)], ignore_index=True)
    return report, changes


def price_now(now, players, games):
    """Every open prop on a game still ahead, priced by the stat model.

    Returns (priced rows, availability): the second says whether the
    official injury report was read and where it overrode the injury feed.
    """
    players = players[players.tip_utc < now].copy()
    season = now.year + 1 if now.month >= 8 else now.year
    eastern = pd.Timestamp(now).tz_convert("America/New_York")
    days = [(eastern + timedelta(days=i)).date() for i in range(DAYS_AHEAD)]
    schedule = pd.concat(
        [scoreboard(f"{day:%Y%m%d}", season) for day in days], ignore_index=True
    )
    schedule["tip_utc"] = pd.to_datetime(schedule.tip_utc, utc=True)
    schedule = schedule[~schedule.completed & (schedule.tip_utc > now)]
    markets = parse(snapshot(SERIES, now=now))
    if schedule.empty or markets.empty:
        return pd.DataFrame(), None
    official = official_report(now)
    report, changes = reconcile(injuries(), official, schedule, players)
    priced, _ = price_markets(players, games, schedule, markets, report, now=now)
    return priced, {"official_report": official is not None, "changes": changes}


def model_file(priced, now, availability=None):
    """The priced props in the shape the page reads its price file in."""
    stamp = pd.Timestamp(now).isoformat(timespec="seconds")
    extra = {} if availability is None else {"availability": availability}
    if priced.empty:
        return {"snapshot_utc": stamp, "columns": SLATE_COLUMNS, "rows": [], **extra}
    frame = priced.copy()
    frame["player_key"] = frame.player.map(normalize_name)
    frame["tip_utc"] = pd.to_datetime(frame.tip_utc, utc=True).map(str)
    frame["snapshot_utc"] = stamp
    blank = frame.injury_status.isna() | frame.injury_status.astype(str).eq("")
    frame["injury_status"] = frame.injury_status.where(~blank, None)
    return {**slate_file(frame), **extra}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--players", default="data/player_games.parquet")
    parser.add_argument("--games", default="data/games.parquet")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    now = datetime.now(UTC)
    players = pd.read_parquet(args.players)
    games = pd.read_parquet(args.games)
    priced, availability = price_now(now, players, games)
    payload = model_file(priced, now, availability)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
    path.write_text(text + "\n", "utf-8")
    print(f"{len(payload['rows'])} props priced at {payload['snapshot_utc']}")
    if availability is not None:
        read = "read" if availability["official_report"] else "not read"
        print(f"official injury report {read}; {len(availability['changes'])} changes")


if __name__ == "__main__":
    main()
