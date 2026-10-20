"""Prior-only NBA playing-time backtest, with fixed untuned coefficients.

Compares a 0.8 EW / 0.2 last-minute prior-only forecast with EW and last
minutes on 2025-26 played games; all predictions are created via shift(1).
This does not validate the licensed pregame vendor or game-day lineup data.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

INPUT = Path("data/player_games.parquet")
OUTPUT = Path("outputs/research/nba_minutes_asof_2025_26.json")


def evaluate(data):
    p = data.copy()
    p["tip_utc"] = pd.to_datetime(p.tip_utc, utc=True)
    p["minutes"] = pd.to_numeric(p.minutes, errors="coerce")
    p = p.sort_values(["player_id", "tip_utc", "game_id"]).copy()
    # A scheduled DNP still changes availability, but does not supply a
    # realized playing-minutes target for this conditional-on-playing model.
    p = p[(~p.did_not_play) & p.minutes.between(1, 48)].copy()
    by = p.groupby("player_id", sort=False)["minutes"]
    p["prior_games"] = by.cumcount()
    p["last_minutes_before_tip"] = by.shift(1)
    p["ew_minutes_before_tip"] = (
        by.transform(lambda series: series.ewm(alpha=0.32, adjust=False).mean())
        .groupby(p.player_id)
        .shift(1)
    )
    p = p[(p.prior_games >= 5) & p.ew_minutes_before_tip.notna()].copy()
    p["frozen_80_20"] = (
        0.8 * p.ew_minutes_before_tip + 0.2 * p.last_minutes_before_tip
    ).clip(0, 44)
    cohorts = {}
    for name, q in {
        "holdout_2025_26": p[(p.season == 2026)],
        "older_2023_24": p[(p.season == 2024)],
        "older_2024_25": p[(p.season == 2025)],
    }.items():
        candidates = {
            "last": "last_minutes_before_tip",
            "ew": "ew_minutes_before_tip",
            "frozen_80_20": "frozen_80_20",
        }
        scores = {}
        for label, col in candidates.items():
            if q.empty:
                scores[label] = None
                continue
            delta = q[col] - q.minutes
            scores[label] = {
                "mae_minutes": round(float(delta.abs().mean()), 3),
                "rmse_minutes": round(float(np.sqrt((delta**2).mean())), 3),
                "within_5_minutes": round(float(delta.abs().le(5).mean()), 4),
            }
        cohorts[name] = {
            "conditional_on_playing_rows": len(q),
            "games": int(q.game_id.nunique()),
            "metrics": scores,
        }
    return {
        "method": "as-of, shifted player-minute history; coefficients fixed before report",
        "scope": "conditional on appearing, not injury availability or lineup confirmation",
        "note": "Do not claim improved model accuracy unless holdout beats EW and last; no Kalshi P&L tested.",
        "cohorts": cohorts,
    }


def main():
    data = pd.read_parquet(INPUT)
    report = evaluate(data)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
