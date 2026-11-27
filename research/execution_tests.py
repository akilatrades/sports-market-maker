"""W3 execution tests on last season's NBA prop trades (RESEARCH_LOG.md,
2026-11-27, "Week 1", plan written before any result). SIMULATED,
in-sample 2025-26, first in line; public prints exist only for the 6 hours
before tip-off.

Universe: NBA points/rebounds/assists/threes markets with a pre-game candle
whose resting NO price (one cent inside) is 65-95 cents (the v9 band).
Orders rest from the candle until tip-off; held to settlement; maker fee.

    python -m research.execution_tests

Writes outputs/execution_tests/summary.json (aggregates only).
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.maker import maker_fee
from kalshi.stats import clustered_mean_t
from research import ladder as L

OUT = Path("outputs/execution_tests")
TICK = 0.01
BAND = (0.65, 0.95)
WINDOWS = {"6-4h": (4, 6), "4-2h": (2, 4), "2-1h": (1, 2)}
WIDE = 0.06
CAPS = (2, 3)
BAR = {
    "window_cents_per_fill": 1.0, "t": 2.0,
    "improve_cents_per_order": 0.3, "improve_orders": 1500,
    "inventory_sd_cut": 0.20, "inventory_mean_drop_cents": 0.2,
}  # fmt: skip


def with_tip(c):
    tip = pd.to_datetime(c.game.map(L.game_key).map(L.tips()), utc=True)
    c = c.copy()
    c["tip_ts"] = (tip - pd.Timestamp(0, tz="UTC")).dt.total_seconds()
    c["hours"] = (c.tip_ts - c.end_ts) / 3600
    c["day"] = pd.to_datetime(c.tip_ts, unit="s")
    return c.dropna(subset=["tip_ts"])


def first_in_window(c, lo, hi):
    w = c[(c.hours > lo) & (c.hours <= hi)]
    return w.sort_values("end_ts").drop_duplicates("ticker").copy()


def place(q, inside):
    q = q.copy()
    spread = (q.yes_ask - q.yes_bid).round(4)
    q["improved"] = spread >= (inside + 1) * TICK - 1e-9
    step = np.where(q.improved, inside * TICK, 0.0)
    q["price"] = np.round(1 - q.yes_ask + step, 4)
    q["yes_level"] = np.round(1 - q.price, 4)
    return q


def first_fill(q, t):
    """Contracts traded through each NO bid from the candle to tip-off, and
    the time of the first such trade."""
    tt = t[t.ticker.isin(set(q.ticker)) & (t.taker_outcome_side == "yes")].copy()
    stamp = pd.to_datetime(tt.created_time, utc=True, format="ISO8601")
    tt["ts"] = (stamp - pd.Timestamp(0, tz="UTC")).dt.total_seconds()
    m = tt.merge(
        q[["ticker", "end_ts", "tip_ts", "yes_level", "improved"]], on="ticker"
    )
    m = m[(m.ts > m.end_ts) & (m.ts <= m.tip_ts)]
    same = (m.yes_price - m.yes_level).abs() < 1e-6
    m = m[(m.yes_price > m.yes_level + 1e-6) | (same & m.improved)]
    g = m.groupby("ticker").agg(traded=("count", "sum"), fill_ts=("ts", "min"))
    q = q.join(g, on="ticker")
    q["traded"] = q.traded.fillna(0)
    q["filled"] = q.traded >= 1
    q["pnl"] = (q.result == "no").astype(float) - q.price - maker_fee(q.price)
    q["value"] = np.where(q.filled, q.pnl, 0.0)  # per order placed
    return q


def stat(values, clusters):
    if len(values) < 3:
        return {"n": int(len(values))}
    mean, t = clustered_mean_t(np.asarray(values, float), np.asarray(clusters))
    return {"n": int(len(values)), "cents": round(100 * float(mean), 3),
            "t": round(float(t), 2) if math.isfinite(t) else None}  # fmt: skip


def halves(q, col, split):
    return [stat(q.loc[q.day < split, col], q.loc[q.day < split, "game"]).get("cents"),
            stat(q.loc[q.day >= split, col], q.loc[q.day >= split, "game"]).get("cents")]  # fmt: skip


def run(c, t):
    c = with_tip(c)
    split = c.day.median()
    out = {"note": "SIMULATED, NBA props 2025-26, first in line, prints only 6h before tip-off; "
           "NO 65-95c; rest from the candle to tip-off. Cents per contract after the maker fee."}  # fmt: skip
    # E-window
    win = {}
    for name, (lo, hi) in WINDOWS.items():
        q = first_fill(place(first_in_window(c, lo, hi), 1), t)
        q = q[q.price.between(*BAND)]
        f = q[q.filled]
        win[name] = q
        out.setdefault("E_window", {})[name] = {
            "orders": int(len(q)),
            "fill_rate": round(float(q.filled.mean()), 3),
            "per_fill": stat(f.pnl, f.game),
            "per_order": stat(q.value, q.game),
            "per_fill_halves_cents": halves(f, "pnl", split),
        }
    names = list(WINDOWS)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            p = win[a][["ticker", "value", "game", "day"]].merge(
                win[b][["ticker", "value"]], on="ticker", suffixes=("_a", "_b")
            )
            p["d"] = p.value_a - p.value_b
            out["E_window"][f"{a} minus {b} per order (paired)"] = {
                **stat(p.d, p.game), "halves_cents": halves(p, "d", split)}  # fmt: skip
    # E-improve
    base = first_in_window(c, 2, 4)
    wide = base[(base.yes_ask - base.yes_bid) >= WIDE - 1e-9]
    one = first_fill(place(wide, 1), t)
    two = first_fill(place(wide, 2), t)
    keep = one.price.between(*BAND)
    p = one[keep][["ticker", "value", "game", "day", "filled"]].merge(
        two[["ticker", "value", "filled"]], on="ticker", suffixes=("_1", "_2")
    )
    p["d"] = p.value_2 - p.value_1
    imp = {**stat(p.d, p.game), "halves_cents": halves(p, "d", split),
           "fill_rate_1c": round(float(p.filled_1.mean()), 3) if len(p) else None,
           "fill_rate_2c": round(float(p.filled_2.mean()), 3) if len(p) else None,
           "per_order_1c": stat(p.value_1, p.game), "per_order_2c": stat(p.value_2, p.game)}  # fmt: skip
    imp["pass"] = bool(
        len(p) >= BAR["improve_orders"] and (imp.get("cents") or -1) >= 100 * BAR["improve_cents_per_order"]
        and (imp.get("t") or 0) >= BAR["t"] and all(h is not None and h > 0 for h in imp["halves_cents"])
    )  # fmt: skip
    out["E_improve_2c_vs_1c_spread_6c_plus"] = imp
    # E-inventory
    f = win["4-2h"][win["4-2h"].filled].sort_values("fill_ts")
    inv = {}
    for cap in (None, *CAPS):
        g = f if cap is None else f.groupby("game").head(cap)
        per_game = g.groupby("game").pnl.sum()
        inv["no cap" if cap is None else f"cap {cap}"] = {
            "fills": int(len(g)),
            "games": int(per_game.size),
            "cents_per_contract": round(100 * float(g.pnl.mean()), 3),
            "game_pnl_sd_dollars": round(float(per_game.std()), 4),
        }
    nc = inv["no cap"]
    for k in [k for k in inv if k != "no cap"]:
        v = inv[k]
        v["sd_cut"] = round(1 - v["game_pnl_sd_dollars"] / nc["game_pnl_sd_dollars"], 3)
        v["mean_drop_cents"] = round(
            nc["cents_per_contract"] - v["cents_per_contract"], 3
        )
        v["pass"] = bool(
            v["sd_cut"] >= BAR["inventory_sd_cut"]
            and v["mean_drop_cents"] <= 100 * BAR["inventory_mean_drop_cents"]
        )
    out["E_inventory_4_2h_fills"] = inv
    out["variants"] = 7
    out["bar"] = BAR
    return out


def main(argv=None):
    c, t = L.load()
    summary = run(c, t)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=1, default=str) + "\n", "utf-8"
    )
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
