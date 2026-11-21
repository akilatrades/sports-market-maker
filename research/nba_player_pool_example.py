"""Example runner for the NBA player pool models.

Usage (from repo root, after pip install nba_api):
    python research/nba_player_pool_example.py
"""

from markets.nba.player_pool import build_player_pool


def main():
    print("Building NBA player pool (this may take a few seconds)...")
    pool = build_player_pool(season="2025-26")
    print("\nTop 15 by simple value over replacement:\n")
    print(pool.head(15).to_string(index=False))
    pool.to_csv("outputs/nba_player_pool.csv", index=False)
    print("\nSaved to outputs/nba_player_pool.csv")


if __name__ == "__main__":
    main()
