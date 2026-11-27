"""Ladder checks C2 (sportsbooks) and C3 (capacity) (RESEARCH_LOG.md,
2026-11-27, plans written before any result). In-sample NBA 2025-26,
SIMULATED; Study B's outlier (+3c) and control (-1c..+1c) resting NO orders.

    python -m research.ladder_checks

Writes outputs/ladder_checks/summary.json (aggregates only).
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.stats import clustered_mean_t
from research import ladder as L

OUT = Path("outputs/ladder_checks")
BOOK = Path("outputs/bookline/fills_with_book.csv.gz")
AHEAD = 4  # contracts resting ahead of us (the 5-contract queue)
SIZES = (1, 3, 5, 10, 25)
HAIRCUTS = (0.02, 0.005)


def cmean(values, clusters):
    if len(values) < 3:
        return {"n": int(len(values))}
    mean, t = clustered_mean_t(np.asarray(values, float), np.asarray(clusters))
    return {"n": int(len(values)), "games": int(pd.Series(clusters).nunique()),
            "cents": round(100 * float(mean), 2),
            "t": round(float(t), 2) if math.isfinite(t) else None}  # fmt: skip


def book_check(groups, book_path=BOOK):
    """Kalshi mid, fitted curve and the books' fair YES chance, per group."""
    b = pd.read_csv(book_path, usecols=["ticker", "p_book", "book_n"])
    b = b[b.p_book.notna()].drop_duplicates("ticker")
    out = {}
    for name, o in groups.items():
        j = o.merge(b, on="ticker")
        fit = j.mid - j.resid
        out[name] = {
            "orders_with_book": int(len(j)),
            "mid_minus_book": cmean(j.mid - j.p_book, j.game),
            "curve_minus_book": cmean(fit - j.p_book, j.game),
            "residual": cmean(j.resid, j.game),
        }
    return out


def capacity(filled_orders):
    """Dollars per month by order size, with AHEAD contracts in front."""
    f = filled_orders.copy()
    months = max(1, f.month.nunique())
    out = {}
    for size in SIZES:
        got = np.clip(f.traded - AHEAD, 0, size)
        row = {"contracts_filled": int(got.sum()),
               "contracts_per_month": round(float(got.sum()) / months, 1)}  # fmt: skip
        for h in HAIRCUTS:
            dollars = float((got * (f.pnl - h)).sum())
            row[f"dollars_per_month_after_{round(100 * h, 1)}c"] = round(
                dollars / months, 2
            )
        out[str(size)] = row
    return out


def run(r, t):
    groups = {}
    for name, (lo, hi) in {
        "outlier": (L.THRESHOLD, 1.0),
        "control": (-0.01, 0.01),
    }.items():
        o = L.orders(r, lo, hi)
        o["traded"] = o.ticker.map(L.traded_through(o, t)).fillna(0)
        groups[name] = o
    filled = groups["outlier"][groups["outlier"].traded >= L.QUEUE]
    return {
        "note": "In-sample NBA 2025-26, SIMULATED. C2: de-vigged sportsbook YES chance at the "
        "books' earliest posting for the game, exact line only. C3: 4 contracts ahead of us.",
        "C2_sportsbooks": book_check(groups),
        "C3_capacity": {
            "months": int(filled.month.nunique()),
            "fills_at_size_1": int(len(filled)),
            "by_size": capacity(filled),
        },  # fmt: skip
    }


def main(argv=None, r=None, t=None):
    if r is None:
        c, t = L.load()
        r = L.residuals(c)
    summary = run(r, t)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=1, default=str) + "\n", "utf-8"
    )
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
