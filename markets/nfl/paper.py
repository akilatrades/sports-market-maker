"""Model probabilities for open Kalshi NFL prop markets (RESEARCH_LOG.md, 2026-10-16).

Maps each open market to the model's over-probability from the latest
ladder made before ``now``, by game day, player name, stat and line. Used by
the "no" seller paper test with the NFL model as veto.
"""

import os
from pathlib import Path

import pandas as pd

from markets.nfl.kalshi import normalize_name, parse
from markets.nfl.market import kickoffs

LADDERS = Path(os.environ.get("SMM_NFL_LADDERS_DIR", "outputs/nfl/projections/ladders"))
MODEL_SERIES = {"KXNFLANYTD", "KXNFLRECYDS"}
MAX_MODEL_AGE_HOURS = 36


def latest_ladder(now, folder=LADDERS, max_age_hours=None):
    """Latest eligible rows, reducing each chunk before reading more history."""
    files = sorted(folder.glob("*.csv.gz"))
    ladder = pd.DataFrame(
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
    keys = ["game_id", "player_id", "stat", "line"]
    for f in files:
        made = pd.to_datetime(
            f.stem.split("_")[-1].replace(".csv", ""), format="%Y-%m-%dT%H%MZ", utc=True
        )
        if made > pd.Timestamp(now):
            continue
        # Never concatenate the entire archive before applying freshness. Row
        # timestamps still govern eligibility, even if a filename is misleading.
        with pd.read_csv(f, chunksize=10_000) as reader:
            for chunk in reader:
                chunk["made_utc"] = pd.to_datetime(chunk.made_utc, utc=True)
                age = (pd.Timestamp(now) - chunk.made_utc).dt.total_seconds() / 3600
                eligible = age.ge(0)
                if max_age_hours is not None:
                    eligible &= age.le(max_age_hours)
                chunk = chunk.loc[eligible]
                if chunk.empty:
                    continue
                ladder = (
                    pd.concat([ladder, chunk], ignore_index=True)
                    if not ladder.empty
                    else chunk
                )
                latest_made = ladder.groupby(
                    keys, sort=False, dropna=False
                ).made_utc.transform("max")
                ladder = ladder.loc[ladder.made_utc.eq(latest_made)].drop_duplicates(
                    keys + ["p_over"], keep="last"
                )
    # Conflicting probabilities with the same latest timestamp have no valid
    # tie-breaker. Do not choose by sort order or fall back to an older estimate.
    ambiguous = ladder.duplicated(keys, keep=False)
    if ambiguous.any():
        count = len(ladder.loc[ambiguous, keys].drop_duplicates())
        print(f"NFL MODEL: blocked {count} conflicting projection keys", flush=True)
    return ladder.loc[~ambiguous].sort_values("made_utc").reset_index(drop=True)


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
