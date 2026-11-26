"""Test 1: the favorite-longshot bias across Kalshi (RESEARCH_LOG.md,
2026-11-26, plan written before any result). SIMULATED, cross-market scan,
in-sample 2025-26; quotes from 7 to 4 hours before expected expiration.

    python -m research.longshot

Writes outputs/longshot/summary.json (aggregates only).
"""

import glob
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.stats import clustered_mean_t
from research.queue_stress import family

SCAN = "outputs/scan/orders_*.csv.gz"
OUT = Path("outputs/longshot")
COLUMNS = ["ticker", "end_ts", "yes_bid", "yes_ask", "price", "side", "traded", "result",
           "pnl", "event_ticker", "date", "series"]  # fmt: skip
BUCKETS = [
    0.01,
    0.02,
    0.05,
    0.10,
    0.20,
    0.30,
    0.40,
    0.50,
    0.60,
    0.70,
    0.80,
    0.90,
    0.95,
    0.98,
    0.99,
]
# --- the plan, fixed before results ---------------------------------------------
LONGSHOT_BID = 0.10
BAND = (0.90, 0.98)
QUEUE, HAIRCUT = 5, 0.02
SPLIT = pd.Timestamp("2026-03-01")
TREASURY = 0.04
BAR = {"t": 2.5, "markets": 1000, "events": 300}


def load(pattern=SCAN):
    frames = []
    for path in sorted(glob.glob(pattern)):
        try:
            frames.append(pd.read_csv(path, usecols=lambda c: c in COLUMNS))
        except (ValueError, OSError, EOFError):
            continue
    d = pd.concat(frames, ignore_index=True)
    for c in ("yes_bid", "yes_ask", "price", "traded", "pnl", "end_ts"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d[d.result.isin(["yes", "no"])].copy()
    d["day"] = pd.to_datetime(d.date, errors="coerce")
    d["family"] = d.series.map(family)
    return d


def taker_fee(p, rounded=False):
    fee = 0.07 * p * (1 - p)
    return np.ceil(np.round(fee * 100, 6)) / 100 if rounded else fee


def first_quotes(d):
    """One quote per market: its first hour in the window, two-sided."""
    q = d.sort_values("end_ts").drop_duplicates("ticker")
    q = q[(q.yes_bid >= 0) & (q.yes_ask <= 1) & (q.yes_ask > q.yes_bid)].copy()
    q["mid"] = (q.yes_bid + q.yes_ask) / 2
    q["yes_won"] = (q.result == "yes").astype(float)
    return q


def calibration(q):
    q = q.copy()
    q["bucket"] = pd.cut(q.mid, BUCKETS)
    g = q.groupby("bucket", observed=True).agg(
        markets=("mid", "size"), priced=("mid", "mean"), happened=("yes_won", "mean")
    )
    g["gap_points"] = 100 * (g.happened - g.priced)
    return {str(k): {"markets": int(r.markets), "priced": round(float(r.priced), 4),
                     "happened": round(float(r.happened), 4),
                     "gap_points": round(float(r.gap_points), 2)}
            for k, r in g.iterrows()}  # fmt: skip


def measure(f, value, cash=None):
    if len(f) < 2:
        return {"markets": int(len(f))}
    mean, t = clustered_mean_t(value.to_numpy(), f.event_ticker.to_numpy())
    halves = [value[f.day < SPLIT].mean(), value[f.day >= SPLIT].mean()]
    out = {"markets": int(len(f)), "events": int(f.event_ticker.nunique()),
           "cents": round(100 * float(mean), 3),
           "t": round(float(t), 2) if math.isfinite(t) else None,
           "first_half_cents": round(100 * float(halves[0]), 3) if np.isfinite(halves[0]) else None,
           "second_half_cents": round(100 * float(halves[1]), 3) if np.isfinite(halves[1]) else None,
           "avg_price": round(float(f.price_paid.mean()), 4)}  # fmt: skip
    if cash is not None:
        out["profit_per_dollar"] = round(float(value.sum() / cash.sum()), 5)
    return out


def passes(m):
    return bool(
        (m.get("cents") or -1) > 0 and (m.get("t") or 0) >= BAR["t"]
        and m.get("markets", 0) >= BAR["markets"] and m.get("events", 0) >= BAR["events"]
        and (m.get("first_half_cents") or -1) > 0 and (m.get("second_half_cents") or -1) > 0
    )  # fmt: skip


def taker(q, side):
    """Take one contract at the ask on the cheap NO (YES longshot) or the
    expensive YES (favourite)."""
    if side == "no":
        f = q[q.yes_bid <= LONGSHOT_BID + 1e-9].copy()
        f["price_paid"] = 1 - f.yes_bid
        won = (f.result == "no").astype(float)
    else:
        f = q[q.yes_ask.between(*BAND)].copy()
        f["price_paid"] = f.yes_ask
        won = (f.result == "yes").astype(float)
    f = f[(f.price_paid > 0) & (f.price_paid < 1)]
    won = won.loc[f.index]
    exact = won - f.price_paid - taker_fee(f.price_paid)
    rounded = won - f.price_paid - taker_fee(f.price_paid, rounded=True)
    return f, exact, rounded


def maker(d, side):
    f = d[
        (d.side == side) & d.price.between(*BAND) & (d.traded >= QUEUE) & d.pnl.notna()
    ].copy()
    f["price_paid"] = f.price
    return f


def by_family(f, value):
    return {k: measure(f.loc[g.index], value.loc[g.index]) for k, g in f.groupby("family")
            if len(g) >= 200}  # fmt: skip


def run(d):
    q = first_quotes(d)
    out = {
        "note": "SIMULATED (cross-market scan 2025-26, quotes 7-4 hours before expected "
        "expiration). Cents per contract. Not a forecast.",
        "markets_quoted": int(len(q)),
        "calibration_yes": calibration(q),
    }
    f, exact, rounded = taker(q, "no")
    out["T_NO_take_no_when_yes_bid_le_10c"] = {
        "after_fee": measure(f, exact, f.price_paid),
        "after_fee_rounded_1_contract": measure(f, rounded),
        "by_family": by_family(f, exact),
    }
    f, exact, _ = taker(q, "yes")
    out["T_YES_take_yes_at_90_98c"] = measure(f, exact, f.price_paid)
    m = maker(d, "no")
    out["M_NO_rest_no_at_90_98c"] = {
        "before_haircut": measure(m, m.pnl, m.price_paid),
        "after_2c_haircut": measure(m, m.pnl - HAIRCUT),
        "by_family_before_haircut": by_family(m, m.pnl),
    }
    m = maker(d, "yes")
    out["M_YES_rest_yes_at_90_98c"] = {"before_haircut": measure(m, m.pnl),
                                       "after_2c_haircut": measure(m, m.pnl - HAIRCUT)}  # fmt: skip
    # Cash: about 5.5 hours locked; a 4% Treasury earns 4% x 5.5 / 8760 per dollar.
    out["treasury_per_dollar_over_5_5_hours"] = round(TREASURY * 5.5 / 8760, 7)
    out["pass_T_NO"] = passes(out["T_NO_take_no_when_yes_bid_le_10c"]["after_fee"])
    out["pass_M_NO"] = passes(out["M_NO_rest_no_at_90_98c"]["after_2c_haircut"])
    out["variants"] = 4
    out["bar"] = BAR
    return out


def main(argv=None, d=None):
    summary = run(load() if d is None else d)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=1, default=str) + "\n", "utf-8"
    )
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
