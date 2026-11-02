"""More fills for the spread maker and NBA: looser settings, fills vs edge.

RESEARCH_LOG.md, 2026-11-02, "More fills for the spread maker and NBA". The
variants and the choosing rule were written down before this ran. SIMULATED
and in-sample; first in line and ``flow_share`` 0.25 (median of 20 draws).

    python -m research.fills_first_sweep spread   # outputs/research/fills_first_spread.json
    python -m research.fills_first_sweep nba      # outputs/research/fills_first_nba.json
"""

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.stats import clustered_mean_t

OUT = Path("outputs/research")
DRAWS = 20


def summary(f, cluster):
    out = {"fills": int(len(f))}
    if len(f) >= 30:
        m, t = clustered_mean_t(f.pnl, f[cluster])
        out.update(
            cents=round(100 * float(m), 2),
            t=round(float(t), 2),
            dollars=round(float(f.pnl.sum()), 2),
        )
        if "half" in f:
            for h in ("earlier", "later"):
                g = f[f.half == h]
                out[f"{h}_cents"] = (
                    round(100 * float(g.pnl.mean()), 2) if len(g) else None
                )
    return out


def median_draw(draws):
    ok = [d for d in draws if d.get("cents") is not None]
    if not ok:
        return draws[0]
    return sorted(ok, key=lambda d: d["cents"])[len(ok) // 2]


# --- spread maker -------------------------------------------------------------


def spread_quotes():
    import research.spread_start_window as ssw

    ssw.MIN_SPREAD = 0.04  # load every width the sweep may use
    r, e = ssw.load_rows(), ssw.load_events()
    by_type = ssw.milestone_by_type(e)
    types = ssw.trusted_types(e, by_type)
    known, _ = ssw.starts(e, ssw.SOURCES["S1+S2+S3"], by_type, types)
    q = ssw.select(r, known, 24).copy()  # start known, 85+ minutes ahead
    q["h_start"] = (q.event_ticker.map(known) - q.end_ts) / 3600
    return q


def spread_variant(q, lead, per_event, min_spread, esports):
    from live.spread_policy import ESPORTS_SERIES

    v = q[(q.h_start <= lead + 1e-9) & (q.spread >= min_spread - 1e-9)]
    if not esports:
        v = v[~v.series.isin(ESPORTS_SERIES)]
    if per_event is not None:
        # Widest markets first within each event and snapshot (v5's tiebreak).
        m = v.drop_duplicates(["event_ticker", "end_ts", "ticker"])[
            ["event_ticker", "end_ts", "ticker", "spread"]
        ]
        m = m.sort_values(["event_ticker", "end_ts", "spread", "ticker"])
        m["rank"] = (
            m.iloc[::-1].groupby(["event_ticker", "end_ts"]).cumcount().iloc[::-1]
        )
        keep = m[m["rank"] < per_event][["ticker", "end_ts"]]
        v = v.merge(keep, on=["ticker", "end_ts"])
    return v


def spread_fills(v, share, seed=0):
    if share >= 1:
        return v[v.traded >= 1]
    got = np.random.default_rng(seed).binomial(v.traded.astype(np.int64), share)
    return v[got >= 1]


def spread_sweep():
    q = spread_quotes()
    days = q.day.nunique()
    rows = []
    for lead, per_event, ms, esports in itertools.product(
        (12, 24), (1, 2, None), (0.08, 0.06, 0.05, 0.04), (False, True)
    ):
        v = spread_variant(q, lead, per_event, ms, esports)
        first = summary(spread_fills(v, 1.0), "event_ticker")
        flow = median_draw(
            [summary(spread_fills(v, 0.25, s), "event_ticker") for s in range(DRAWS)]
        )
        rows.append(
            {
                "lead_hours": lead,
                "markets_per_event": per_event or "all",
                "min_spread_cents": round(100 * ms),
                "esports": esports,
                "quotes": len(v),
                "first_in_line": first,
                "flow_0.25": flow,
                "flow_fills_per_day": round(flow["fills"] / days, 1),
            }
        )
    return {"days": int(days), "variants": rows}


def spread_pick(res):
    ok = [
        r
        for r in res["variants"]
        if (r["flow_0.25"].get("cents") or -1) >= 2
        and (r["flow_0.25"].get("t") or 0) >= 2
        and (r["flow_0.25"].get("earlier_cents") or -1) > 0
        and (r["flow_0.25"].get("later_cents") or -1) > 0
    ]

    def changes(r):
        return sum(
            (
                r["lead_hours"] != 12,
                r["markets_per_event"] != 1,
                r["min_spread_cents"] != 8,
                r["esports"] is not False,
            )
        )

    return max(ok, key=lambda r: (r["flow_0.25"]["fills"], -changes(r)), default=None)


# --- NBA ----------------------------------------------------------------------


GAPS = {
    "v7": {"points": 3.0, "rebounds": 2.0, "assists": 2.0, "threes": 1.0},
    "1.5x": {"points": 4.5, "rebounds": 3.0, "assists": 3.0, "threes": 1.5},
    "2x": {"points": 6.0, "rebounds": 4.0, "assists": 4.0, "threes": 2.0},
}
EDGE_FLOORS = (0.0, -0.01, -0.02, -0.03)
EDGE_CAP = 0.08


def nba_orders():
    """Replay orders in games with logged book lines, priced v7's way:
    the exact line when a book quotes it, else nearby lines (per gap set)."""
    import kalshi.line_translation as lt
    from kalshi.maker import maker_fee
    from research.nba_late_fill_cutoff import (
        BOOKS,
        FEE_SHARE,
        first_fill,
        hits,
        load_orders,
    )
    from research.fill_sizing_replay import TRADES

    o = load_orders()
    b = pd.read_csv(BOOKS)
    b["line"] = b.line.round(1)
    b = b.drop_duplicates(["game_id", "player_key", "stat", "line"], keep="last")
    o["line"] = o.line.astype(float).round(1)
    o["game_id"] = pd.to_numeric(o.game_id, errors="coerce")
    o = o[o.game_id.isin(b.game_id.unique()) & o.stat.isin(lt.DISPERSION)].copy()
    exact = b.set_index(["game_id", "player_key", "stat", "line"]).p_book
    o["p_exact"] = [
        exact.get((g, p, s, x))
        for g, p, s, x in zip(o.game_id, o.player_key, o.stat, o.line)
    ]
    groups = {k: g for k, g in b.groupby(["game_id", "player_key", "stat"])}
    original = dict(lt.MAX_GAP)
    try:
        for name, gap in GAPS.items():
            lt.MAX_GAP.update(gap)
            col = []
            for r in o.itertuples():
                if pd.notna(r.p_exact):
                    col.append(r.p_exact)
                    continue
                q = groups.get((r.game_id, r.player_key, r.stat))
                p = (
                    lt.translate(q, r.line, r.stat, exclude_exact=False)[0]
                    if q is not None
                    else None
                )
                col.append(np.nan if p is None else p)
            o[f"p_{name}"] = col
    finally:
        lt.MAX_GAP.update(original)
    o["fee"] = maker_fee(o.price, FEE_SHARE)
    trades = pd.concat([pd.read_parquet(p) for p in TRADES], ignore_index=True)
    h = hits(o, trades)
    o["fill_first"] = first_fill(o, h).notna()
    flows = np.column_stack(
        [first_fill(o, h, 0.25, s).notna().to_numpy() for s in range(DRAWS)]
    )
    return o, flows


def nba_sweep():
    o, flows = nba_orders()
    rows = []
    for (gname, _), floor in itertools.product(GAPS.items(), EDGE_FLOORS):
        p = o[f"p_{gname}"]
        edge = (1 - p) - o.price - o.fee
        sel = p.notna() & edge.between(floor - 1e-9, EDGE_CAP)
        first = summary(o[sel & o.fill_first], "game_id")
        flow = median_draw(
            [summary(o[sel & flows[:, s]], "game_id") for s in range(DRAWS)]
        )
        rows.append(
            {
                "gap": gname,
                "edge_floor_cents": round(100 * floor),
                "orders": int(sel.sum()),
                "translated_orders": int((sel & o.p_exact.isna()).sum()),
                "first_in_line": first,
                "flow_0.25": flow,
            }
        )
    return {"games": int(o.game_id.nunique()), "variants": rows}


def nba_pick(res):
    ok = [
        r
        for r in res["variants"]
        if (r["flow_0.25"].get("cents") or -1) >= 1
        and (r["flow_0.25"].get("t") or 0) >= 1
        and (r["first_in_line"].get("cents") or -1) > 0
    ]
    return max(ok, key=lambda r: r["flow_0.25"]["fills"], default=None)


def main(argv):
    which = argv[0] if argv else "spread"
    if which == "spread":
        res = spread_sweep()
        res["pick"] = spread_pick(res)
    else:
        res = nba_sweep()
        res["pick"] = nba_pick(res)
    res["note"] = "SIMULATED, in-sample; RESEARCH_LOG.md 2026-11-02"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"fills_first_{which}.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


if __name__ == "__main__":
    out = main(sys.argv[1:])
    print(json.dumps(out["pick"], indent=1))
