"""Optional player-specific residual variance for the NBA StatModel.

The current outcome distribution uses minutes-tier + expected-value bands.
This module adds a lightweight hierarchical shrinkage of residual variance
toward the tier mean. It can be mixed into StatModel.prob_over without
changing the default (band-only) behavior.

Intended for paper evaluation first.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def fit_player_residual_scale(
    rows: pd.DataFrame,
    stat: str,
    mean: np.ndarray,
    *,
    prior_strength: float = 20.0,
    min_games: int = 8,
) -> pd.Series:
    """Return a Series (index = player_id) of multiplicative residual scales.

    scale > 1 means the player is more volatile than the tier average.
    """
    if "player_id" not in rows.columns:
        return pd.Series(dtype=float)

    residual = rows[stat].to_numpy(float) - mean
    # Rough per-player variance relative to global
    global_var = np.nanvar(residual)
    if global_var <= 0:
        return pd.Series(dtype=float)

    df = pd.DataFrame({"player_id": rows.player_id, "resid2": residual**2})
    counts = df.groupby("player_id").size()
    means = df.groupby("player_id")["resid2"].mean()

    # Shrink toward global variance
    n = counts.clip(lower=1)
    shrunk = (n * means + prior_strength * global_var) / (n + prior_strength)
    scale = np.sqrt(shrunk / global_var)
    scale = scale.where(counts >= min_games, 1.0)
    return scale


def adjust_threshold_for_scale(threshold: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """Widen or tighten the ratio threshold according to player scale.

    Higher scale -> more mass in the tails -> lower P(over) for a given line
    above the mean (conservative for NO quoting).
    """
    # Simple linear adjustment on the log-ratio scale; clip for stability.
    return threshold ** (1.0 / np.clip(scale, 0.6, 1.8))
