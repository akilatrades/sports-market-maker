"""Continuous minutes adjustment from the official injury report.

Out / Doubtful -> strong down-weight or skip.
Questionable -> reduce expected minutes and increase residual uncertainty.
Probable / Available -> little or no change.

Intended for paper evaluation. Does not alter live hard-skip behavior.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STATUS_MINUTES_MULT = {
    "Out": 0.0,
    "Doubtful": 0.15,
    "Questionable": 0.55,
    "Probable": 0.92,
    "Available": 1.0,
}

STATUS_SCALE_MULT = {
    "Out": 1.0,
    "Doubtful": 1.4,
    "Questionable": 1.25,
    "Probable": 1.05,
    "Available": 1.0,
}


def apply_injury_minutes(
    rows: pd.DataFrame,
    *,
    status_col: str = "injury_status",
    minutes_col: str = "ew_minutes",
) -> pd.DataFrame:
    """Return a copy with adjusted expected minutes and a residual scale multiplier.

    Adds columns ``minutes_mult`` and ``injury_scale_mult``.
    """
    out = rows.copy()
    status = out.get(status_col, pd.Series("", index=out.index)).fillna("")
    mult = status.map(STATUS_MINUTES_MULT).fillna(1.0)
    scale_mult = status.map(STATUS_SCALE_MULT).fillna(1.0)
    out["minutes_mult"] = mult
    out["injury_scale_mult"] = scale_mult
    if minutes_col in out:
        out[minutes_col] = out[minutes_col] * mult
    return out
