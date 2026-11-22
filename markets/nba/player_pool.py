"""High-level NBA player pool models for analytics and projections.

Phases:
1. Data foundation via nba_api
2. Hierarchical player ratings (shrinkage toward position/role)
3. Projection layer (minutes + context)
4. Value layer (simple availability-adjusted impact)

Intended for research and portfolio use. Requires: pip install nba_api
"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np
import pandas as pd

try:
    from nba_api.stats.endpoints import leaguedashplayerstats, playergamelog
    from nba_api.stats.static import players
except ImportError:
    leaguedashplayerstats = playergamelog = players = None


# --- Phase 1: Data foundation ----------------------------------------------

def fetch_current_season_stats(season: str = "2025-26", per_mode: str = "PerGame") -> pd.DataFrame:
    """Pull current-season player stats from NBA Stats API."""
    if leaguedashplayerstats is None:
        raise ImportError("nba_api is required: pip install nba_api")
    time.sleep(0.6)  # polite rate limit
    data = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season,
        per_mode_detailed=per_mode,
        season_type_all_star="Regular Season",
    )
    df = data.get_data_frames()[0]
    df["season"] = season
    return df


def fetch_player_game_log(player_id: int, season: str = "2025-26") -> pd.DataFrame:
    """Game log for one player (useful for EW rates)."""
    if playergamelog is None:
        raise ImportError("nba_api is required")
    time.sleep(0.6)
    log = playergamelog.PlayerGameLog(player_id=player_id, season=season)
    return log.get_data_frames()[0]


# --- Phase 2: Hierarchical ratings ------------------------------------------

POSITION_GROUPS = {
    "PG": "G",
    "SG": "G",
    "SF": "F",
    "PF": "F",
    "C": "C",
}


def _position_group(pos: str) -> str:
    return POSITION_GROUPS.get(str(pos).split("-")[0], "F")


def hierarchical_rate(
    df: pd.DataFrame,
    stat: str,
    minutes_col: str = "MIN",
    *,
    prior_strength: float = 30.0,
    min_minutes: float = 100.0,
) -> pd.Series:
    """Shrink player per-minute rates toward position-group mean.

    Returns a Series of shrunk rates indexed like df.
    """
    if stat not in df.columns or minutes_col not in df.columns:
        return pd.Series(np.nan, index=df.index)

    rate = df[stat] / df[minutes_col].replace(0, np.nan)
    group = df.get("POSITION", pd.Series("F", index=df.index)).map(_position_group)
    group_mean = rate.groupby(group).transform("mean")

    n = df[minutes_col].fillna(0)
    weight = n / (n + prior_strength)
    shrunk = weight * rate + (1 - weight) * group_mean
    shrunk = shrunk.where(n >= min_minutes, group_mean)
    return shrunk


def add_hierarchical_ratings(df: pd.DataFrame) -> pd.DataFrame:
    """Add shrunk per-minute rates for core counting stats."""
    out = df.copy()
    for stat in ("PTS", "REB", "AST", "FG3M"):
        if stat in out.columns:
            out[f"rate_{stat.lower()}_shrunk"] = hierarchical_rate(out, stat)
    return out


# --- Phase 3: Projection layer ----------------------------------------------

def project_per_game(
    df: pd.DataFrame,
    *,
    minutes_col: str = "MIN",
    injury_mult: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """Simple per-game projection from shrunk rates × expected minutes."""
    out = df.copy()
    minutes = out[minutes_col].fillna(0)
    if injury_mult is not None:
        minutes = minutes * injury_mult.reindex(out.index).fillna(1.0)

    for stat, rate_col in (
        ("pts", "rate_pts_shrunk"),
        ("reb", "rate_reb_shrunk"),
        ("ast", "rate_ast_shrunk"),
        ("fg3m", "rate_fg3m_shrunk"),
    ):
        if rate_col in out.columns:
            out[f"proj_{stat}"] = out[rate_col] * minutes
    out["proj_minutes"] = minutes
    return out


# --- Phase 4: Value layer ---------------------------------------------------

def simple_value(
    df: pd.DataFrame,
    *,
    replacement_pts: float = 0.35,  # rough per-minute replacement
    replacement_reb: float = 0.12,
    replacement_ast: float = 0.08,
) -> pd.DataFrame:
    """Very simple availability-adjusted value over replacement (per game).

    Not a full WAR model — a transparent starting point.
    """
    out = df.copy()
    minutes = out.get("proj_minutes", out.get("MIN", 0))
    pts = out.get("proj_pts", 0)
    reb = out.get("proj_reb", 0)
    ast = out.get("proj_ast", 0)

    repl_pts = replacement_pts * minutes
    repl_reb = replacement_reb * minutes
    repl_ast = replacement_ast * minutes

    # Rough weights; tune later
    out["value_over_repl"] = (
        1.0 * (pts - repl_pts) + 0.7 * (reb - repl_reb) + 0.9 * (ast - repl_ast)
    )
    return out


def build_player_pool(season: str = "2025-26") -> pd.DataFrame:
    """End-to-end: fetch → hierarchical rates → projections → value."""
    raw = fetch_current_season_stats(season)
    # Basic cleanup
    raw = raw[raw["MIN"] > 0].copy()
    if "PLAYER_POSITION" in raw.columns:
        raw["POSITION"] = raw["PLAYER_POSITION"]
    elif "POSITION" not in raw.columns:
        raw["POSITION"] = "F"

    rated = add_hierarchical_ratings(raw)
    projected = project_per_game(rated)
    valued = simple_value(projected)

    cols = [
        "PLAYER_NAME",
        "TEAM_ABBREVIATION",
        "POSITION",
        "GP",
        "MIN",
        "PTS",
        "REB",
        "AST",
        "FG3M",
        "rate_pts_shrunk",
        "rate_reb_shrunk",
        "rate_ast_shrunk",
        "rate_fg3m_shrunk",
        "proj_minutes",
        "proj_pts",
        "proj_reb",
        "proj_ast",
        "proj_fg3m",
        "value_over_repl",
    ]
    available = [c for c in cols if c in valued.columns]
    return valued[available].sort_values("value_over_repl", ascending=False)


if __name__ == "__main__":
    pool = build_player_pool()
    print(pool.head(20).to_string(index=False))
