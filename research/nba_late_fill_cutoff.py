"""NBA: do resting NO orders that fill in the last hour before tip lose money?

RESEARCH_LOG.md, 2026-10-30, "Stop resting NBA orders in the last hour before
tip-off (pre-registered)". SIMULATED: the 2025-26 replay (in-sample for the
pricing rules; the cutoff itself was never tuned on it). One 1-contract NO
order per market, placed about five hours before tip, filled by the first
public trade print that would have reached it (``research.fill_sizing_replay``
rules). No maker fee, as in that replay.

    python -m research.nba_late_fill_cutoff   # outputs/research/nba_late_fill_cutoff.json
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.maker import maker_fee
from kalshi.stats import clustered_mean_t
from research.fill_sizing_replay import ORDERS, TRADES

OUT = Path("outputs/research/nba_late_fill_cutoff.json")
BOOKS = Path("outputs/bookline/book_lines.csv.gz")
CUTOFFS = (30, 60, 90, 120)  # minutes before tip; 60 is the pre-registered one
PRIMARY = 60
DRAWS = 20
FEE_SHARE = 0.25  # as research.bookline_backtest and the live v7 book edge


def load_orders(path=ORDERS):
    o = pd.read_csv(path, low_memory=False).drop_duplicates("ticker").copy()
    for col in ("over", "p_model", "price", "tip_ts", "end_ts", "yes_level"):
        o[col] = o[col].astype(float)
    o["improved"] = o.improved.astype(str).str.lower().eq("true")
    o["pnl"] = (1 - o.over) - o.price
    return o[o.price.between(0.10, 0.90)].reset_index(drop=True)


def hits(orders, trades):
    """Every trade print that would reach each order before tip, oldest first."""
    t = trades.copy()
    created = pd.to_datetime(t.created_time, utc=True, format="ISO8601")
    t["ts"] = created.dt.tz_convert(None).to_numpy().astype("datetime64[s]")
    t["ts"] = t.ts.astype("int64")
    t["yes_price"] = t.yes_price.astype(float)
    t["count"] = t["count"].astype(float)
    cols = ["ticker", "end_ts", "tip_ts", "yes_level", "improved"]
    tt = t.merge(orders[cols], on="ticker")
    tt = tt[(tt.ts > tt.end_ts) & (tt.ts <= tt.tip_ts)]
    same = (tt.yes_price - tt.yes_level).abs() < 1e-6
    better = tt.yes_price > tt.yes_level + 1e-6
    hit = tt.taker_outcome_side.eq("yes") & (better | (same & tt.improved))
    return tt.loc[hit, ["ticker", "ts", "count"]].sort_values(["ticker", "ts"])


def first_fill(orders, hit, share=1.0, seed=0):
    """Seconds before tip of each order's first fill (NaN: never filled)."""
    h = hit
    if share < 1:
        rng = np.random.default_rng(seed)
        reached = rng.binomial(h["count"].round().astype(int).clip(lower=1), share)
        h = h[reached > 0]
    first = h.groupby("ticker").ts.min()
    return orders.tip_ts - orders.ticker.map(first)


def v7_like(orders, books_path=BOOKS):
    """Orders with an exact book line, book edge 0-8c and model edge >= 0."""
    b = pd.read_csv(books_path)
    b["line"] = b.line.round(1)
    b = b.drop_duplicates(["game_id", "player_key", "stat", "line"], keep="last")
    o = orders.copy()
    o["line"] = o.line.astype(float).round(1)
    o["game_id"] = pd.to_numeric(o.game_id, errors="coerce")
    o = o.merge(
        b[["game_id", "player_key", "stat", "line", "p_book"]],
        on=["game_id", "player_key", "stat", "line"],
        how="inner",
    )
    fee = maker_fee(o.price, FEE_SHARE)
    book_edge = (1 - o.p_book) - o.price - fee
    model_edge = (1 - o.p_model) - o.price - fee
    return o[book_edge.between(0, 0.08) & (model_edge >= 0)].reset_index(drop=True)


def cents(frame):
    if len(frame) < 10:
        return {"fills": len(frame), "cents": None, "t": None}
    m, t = clustered_mean_t(frame.pnl, frame.game_id)
    return {
        "fills": len(frame),
        "games": int(frame.game_id.nunique()),
        "cents": round(100 * float(m), 2),
        "t": round(float(t), 2),
    }


def clustered_diff(a, b):
    """Mean of a minus mean of b, game-clustered."""
    if len(a) < 10 or len(b) < 10:
        return {"cents": None, "t": None}
    xa, xb = a.pnl.astype(float), b.pnl.astype(float)
    est = float(xa.mean() - xb.mean())
    infl = pd.concat(
        [(xa - xa.mean()) / len(xa), -(xb - xb.mean()) / len(xb)], ignore_index=True
    )
    groups = pd.concat([a.game_id, b.game_id], ignore_index=True).astype(str)
    se = float(np.sqrt((infl.groupby(groups.to_numpy()).sum() ** 2).sum()))
    return {"cents": round(100 * est, 2), "t": round(est / se, 2) if se else None}


def table(orders, before):
    """Removed (late) vs kept (early) fills for each cutoff."""
    filled = orders.assign(before=before)[before.notna()]
    out = {"all_fills": cents(filled)}
    for c in CUTOFFS:
        late = filled[filled.before <= c * 60]
        early = filled[filled.before > c * 60]
        out[f"{c}m"] = {
            "removed_late": cents(late),
            "kept_early": cents(early),
            "late_minus_early": clustered_diff(late, early),
            "dollars_removed": round(float(late.pnl.sum()), 2),
        }
    return out


def by_stat(orders, before, cutoff=PRIMARY):
    filled = orders.assign(before=before)[before.notna()]
    late = filled[filled.before <= cutoff * 60]
    return {s: cents(g) for s, g in late.groupby("stat")}


def main():
    orders = load_orders()
    trades = pd.concat([pd.read_parquet(p) for p in TRADES], ignore_index=True)
    res = {
        "note": "SIMULATED 2025-26 replay, in-sample season; RESEARCH_LOG.md 2026-10-30",
        "variants": len(CUTOFFS) * 2 * 2,
    }
    for name, pop in (("P1_all_10_90c", orders), ("P2_v7_like", v7_like(orders))):
        h = hits(pop, trades)
        block = {"orders": len(pop)}
        block["first_in_line"] = table(pop, first_fill(pop, h))
        draws = []
        for seed in range(DRAWS):
            t = table(pop, first_fill(pop, h, 0.25, seed))[f"{PRIMARY}m"]
            draws.append(t["removed_late"])
        ranked = sorted(
            (d for d in draws if d["cents"] is not None), key=lambda d: d["cents"]
        )
        block["flow_0.25_primary_median_draw"] = (
            ranked[len(ranked) // 2] if ranked else None
        )
        block["late_by_stat_first_in_line"] = by_stat(pop, first_fill(pop, h))
        res[name] = block
    p1 = res["P1_all_10_90c"]
    primary = p1["first_in_line"][f"{PRIMARY}m"]["removed_late"]
    flow = p1["flow_0.25_primary_median_draw"] or {}
    p2 = res["P2_v7_like"]["first_in_line"][f"{PRIMARY}m"]["removed_late"]
    res["pass"] = bool(
        primary["cents"] is not None
        and primary["fills"] >= 300
        and primary["cents"] <= -2
        and primary["t"] <= -2.0
        and (flow.get("cents") or 0) < 0
        and (p2.get("cents") or 0) < 0
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    main()
