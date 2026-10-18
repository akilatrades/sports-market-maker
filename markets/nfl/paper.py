"""Model probabilities for open Kalshi NFL prop markets (RESEARCH_LOG.md, 2026-10-16).

Maps each open market to the model's over-probability from the latest
ladder made before ``now``, by game day, player name, stat and line. Used by
the "no" seller paper test with the NFL model as veto.
"""

from pathlib import Path

import pandas as pd

from markets.nfl.kalshi import normalize_name, parse
from markets.nfl.market import kickoffs

LADDERS = Path("outputs/nfl/projections/ladders")
MODEL_SERIES = {"KXNFLANYTD", "KXNFLRECYDS"}
MAX_MODEL_AGE_HOURS = 36


def latest_ladder(now, folder=LADDERS, max_age_hours=None):
    """Rows of the most recent ladder made before ``now``, with kickoff times."""
    files = sorted(folder.glob("*.csv.gz"))
    frames = []
    for f in files:
        made = pd.to_datetime(
            f.stem.split("_")[-1].replace(".csv", ""), format="%Y-%m-%dT%H%MZ", utc=True
        )
        if made <= pd.Timestamp(now):
            frames.append(pd.read_csv(f))
    if not frames:
        return pd.DataFrame(
            columns=[
                "game_id",
                "player",
                "player_id",
                "stat",
                "line",
                "p_over",
                "made_utc",
            ]
        )
    ladder = pd.concat(frames, ignore_index=True)
    ladder["made_utc"] = pd.to_datetime(ladder.made_utc, utc=True)
    age = (pd.Timestamp(now) - ladder.made_utc).dt.total_seconds() / 3600
    ladder = ladder[age.ge(0)]
    if max_age_hours is not None:
        ladder = ladder[age.loc[ladder.index].le(max_age_hours)]
    return ladder.sort_values("made_utc").drop_duplicates(
        ["game_id", "player_id", "stat", "line"], keep="last"
    )


def model_estimates(markets, games, now, folder=LADDERS, max_age_hours=None):
    """Return probability and its original projection timestamp per ticker."""
    m = pd.DataFrame(markets)
    if m.empty:
        return {}
    m["series"] = m.ticker.str.split("-").str[0]
    m = parse(m)
    m["gameday"] = m.game_date.astype(str)
    ladder = latest_ladder(now, folder, max_age_hours=max_age_hours)
    if ladder.empty:
        return {}
    ladder = ladder.merge(kickoffs(games)[["game_id", "gameday"]], on="game_id")
    ladder["player_key"] = ladder.player.map(normalize_name)
    joined = m.merge(
        ladder[["gameday", "player_key", "stat", "line", "p_over", "made_utc"]],
        on=["gameday", "player_key", "stat", "line"],
    )
    return {
        r.ticker: {"probability": r.p_over, "made_utc": r.made_utc.isoformat()}
        for r in joined.itertuples()
    }


def model_probabilities(markets, games, now, folder=LADDERS):
    """Historical research API; live trading applies an explicit age limit."""
    estimates = model_estimates(markets, games, now, folder)
    return {ticker: estimate["probability"] for ticker, estimate in estimates.items()}
