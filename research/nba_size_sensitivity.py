"""Reproducible NBA two-book historical sizing diagnostics (research only).

Never calls Kalshi authenticated endpoints and cannot place trades.
Requires the saved Oct 18 historical hypothetical-fill input.
"""
import json
from pathlib import Path

import pandas as pd

DATA = Path("outputs/bookline/fills_with_book.csv.gz")


def main():
    d = pd.read_csv(DATA, low_memory=False)
    required = ["price", "book_edge", "book_n", "game_id", "pnl_no_fee", "pnl_if_filled"]
    absent = sorted(set(required) - set(d.columns))
    if absent:
        raise ValueError(f"Historical input missing required columns: {absent}")
    subset = d[
        d.price.between(0.1, 0.9)
        & d.book_edge.between(0, 0.15)
        & (d.book_n >= 2)
    ].copy()
    print("HISTORICAL TWO-BOOK REPLAY INPUTS")
    print(json.dumps({
        "source_rows": len(d),
        "filtered_possible_fills": len(subset),
        "independent_games": int(subset.game_id.nunique()),
        "columns": list(d.columns),
        "known_ticker_unique": int(subset["ticker"].nunique())
        if "ticker" in subset else None,
        "sample_redacted_dtypes": {
            name: str(subset[name].dtype)
            for name in ("tip_utc", "day", "date", "month", "filled_contracts", "pnl_no_fee", "price")
            if name in subset.columns
        },
        "pnl_fee_average": round(float(subset.pnl_if_filled.mean()), 6),
        "pnl_no_fee_average": round(float(subset.pnl_no_fee.mean()), 6),
        "counted_stat": subset.groupby("stat").size().to_dict()
        if "stat" in subset else {},
    }, indent=2))


if __name__ == "__main__":
    main()
