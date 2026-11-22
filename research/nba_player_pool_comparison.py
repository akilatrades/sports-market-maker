"""Clean comparison report for the NBA player pool models.

Shows raw season averages vs. hierarchical projections vs. value.
Usage:
    python research/nba_player_pool_comparison.py
"""

from pathlib import Path

import pandas as pd

from markets.nba.player_pool import build_player_pool


def main():
    print("Building enhanced player pool (recent minutes limited to first 50 for speed)...")
    pool = build_player_pool(season="2025-26", use_recent_minutes=True)

    # Comparison view
    compare_cols = [
        "PLAYER_NAME",
        "TEAM_ABBREVIATION",
        "MIN",
        "PTS",
        "proj_minutes",
        "proj_pts",
        "residual_scale",
        "value_over_repl",
    ]
    available = [c for c in compare_cols if c in pool.columns]
    report = pool[available].head(25).copy()
    report["pts_diff"] = report.get("proj_pts", 0) - report.get("PTS", 0)

    print("\n=== Top 25: Raw vs Projected ===\n")
    print(report.to_string(index=False))

    out = Path("outputs/nba_player_pool_comparison.csv")
    out.parent.mkdir(exist_ok=True)
    report.to_csv(out, index=False)
    print(f"\nSaved comparison to {out}")


if __name__ == "__main__":
    main()
