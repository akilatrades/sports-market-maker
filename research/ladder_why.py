"""Why NBA ladders kink: EXPLORATORY cuts of Study B (RESEARCH_LOG.md,
2026-11-26, "Ladders, deeper", part A). In-sample 2025-26, SIMULATED. No
bar; nothing here changes the frozen paper rule.

    python -m research.ladder_why

Writes outputs/ladder_why/summary.json (aggregates only).
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.stats import clustered_mean_t
from research import ladder as L

OUT = Path("outputs/ladder_why")


def with_tip(r):
    tip = pd.to_datetime(r.game.map(L.game_key).map(L.tips()), utc=True)
    r = r.copy()
    r["hours_to_tip"] = (
        tip - pd.to_datetime(r.end_ts, unit="s", utc=True)
    ).dt.total_seconds() / 3600
    r["strike_plus"] = (r.floor_strike + 0.5).round(1)
    r["round5"] = r.strike_plus % 5 == 0
    r["round10"] = r.strike_plus % 10 == 0
    r["spread_c"] = (100 * (r.yes_ask - r.yes_bid)).round()
    fit = r.mid - r.resid
    r["bid_above_curve"] = r.yes_bid > fit
    return r


def m(f):
    if len(f) < 3:
        return {"fills": int(len(f))}
    mean, t = clustered_mean_t(f.pnl.to_numpy(), f.game.to_numpy())
    return {"fills": int(len(f)), "games": int(f.game.nunique()), "cents": round(100 * float(mean), 2),
            "t": round(float(t), 2) if math.isfinite(t) else None}  # fmt: skip


def run(r, t):
    r = with_tip(r)
    out_orders = L.orders(r, L.THRESHOLD, 1.0)
    ctrl_orders = L.orders(r, -0.01, 0.01)
    for o in (out_orders, ctrl_orders):
        o["traded"] = o.ticker.map(L.traded_through(o, t)).fillna(0)
    out = out_orders[out_orders.traded >= L.QUEUE]
    ctrl = ctrl_orders[ctrl_orders.traded >= L.QUEUE]
    base = r.sort_values("end_ts").drop_duplicates("ticker")
    res = {"note": "EXPLORATORY, in-sample NBA 2025-26, SIMULATED. Outlier = 3+ cents above the "
           "ladder's curve; control = within 1 cent; resting NO, 5+ contracts traded through.",
           "overall": {"outlier": m(out), "control": m(ctrl)}}  # fmt: skip
    res["E1_round_strikes"] = {
        "share_round5_all_strikes": round(float(base.round5.mean()), 3),
        "share_round5_outlier_orders": round(float(out_orders.round5.mean()), 3),
        "share_round10_all_strikes": round(float(base.round10.mean()), 3),
        "share_round10_outlier_orders": round(float(out_orders.round10.mean()), 3),
        "outlier_round5": m(out[out.round5]),
        "outlier_not_round5": m(out[~out.round5]),
    }
    bins = [(0, 3), (3, 6), (6, 99)]
    res["E2_hours_before_tip"] = {
        f"{a}-{b}h": {"outlier": m(out[out.hours_to_tip.between(a, b, inclusive="left")]),
                      "control": m(ctrl[ctrl.hours_to_tip.between(a, b, inclusive="left")])}
        for a, b in bins}  # fmt: skip
    nxt = r.set_index(["ticker", "end_ts"])
    persist = {}
    for k in (1, 2, 3):
        keys = list(zip(out_orders.ticker, out_orders.end_ts + 3600 * k))
        later = nxt.reindex(keys)
        ok = later.resid.notna().to_numpy()
        if ok.sum():
            persist[f"+{k}h"] = {
                "still_fitted": int(ok.sum()),
                "median_resid_then_cents": round(100 * float(np.median(later.resid.to_numpy()[ok])), 2),
                "median_resid_at_order_cents": round(100 * float(np.median(out_orders.resid.to_numpy()[ok])), 2),
                "median_bid_change_cents": round(100 * float(np.median(later.yes_bid.to_numpy()[ok] - out_orders.yes_bid.to_numpy()[ok])), 2),
                "median_ask_change_cents": round(100 * float(np.median(later.yes_ask.to_numpy()[ok] - out_orders.yes_ask.to_numpy()[ok])), 2),
            }  # fmt: skip
    res["E3_persistence"] = persist
    res["E4_side"] = {"share_with_bid_above_curve": round(float(out_orders.bid_above_curve.mean()), 3),
                      "bid_above_curve": m(out[out.bid_above_curve]),
                      "only_ask_above_curve": m(out[~out.bid_above_curve])}  # fmt: skip
    res["E5_spread"] = {
        name: {"outlier": m(out[out.spread_c.between(a, b)]), "control": m(ctrl[ctrl.spread_c.between(a, b)])}
        for name, (a, b) in {"1-2c": (1, 2), "3-5c": (3, 5), "6c+": (6, 99)}.items()}  # fmt: skip
    res["variants"] = 14
    return res


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
