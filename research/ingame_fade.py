"""Track 2: in-game overreaction on NBA props (RESEARCH_LOG.md, 2026-11-26,
"Four more tracks", plan written before any result). SIMULATED, 2025-26
hourly candles and public trades.

An in-game candle whose mid rose 15+ cents since the previous candle gets a
resting NO one cent inside for the next hour (fade the jump); the mirror
fades 15+ cent falls with a resting YES; quiet candles (under 5 cents) get
a resting NO as the control. Fills need 5+ contracts traded through.

    python -m research.ingame_fade

Writes outputs/ingame_fade/summary.json (aggregates only).
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.maker import fills, maker_fee
from kalshi.stats import clustered_mean_t
from research import ladder as L

OUT = Path("outputs/ingame_fade")
# --- the plan, fixed before results ---------------------------------------------
GAME_HOURS = 3
JUMP, QUIET = 0.15, 0.05
MAX_GAP_SECONDS = 2 * 3600
QUEUE, HAIRCUT = 5, 0.02
TICK = 0.01
BAR = {"t": 2.5, "fills": 300, "games": 100, "over_control": 0.01}


def load(hist=L.HIST, series=L.SERIES):
    candles, trades = [], []
    for s in series:
        m = pd.read_parquet(hist / f"markets_{s}.parquet")
        m = m[m.result.isin(["yes", "no"])][["ticker", "result"]]
        c = pd.read_parquet(hist / f"candles_{s}.parquet").merge(m, on="ticker")
        done = set((hist / f"trades_done_{s}.txt").read_text().split())
        candles.append(c[c.ticker.isin(done)])
        t = pd.read_parquet(hist / f"trades_{s}.parquet")
        trades.append(
            t[["ticker", "created_time", "yes_price", "count", "taker_outcome_side"]]
        )
    return prepare(pd.concat(candles, ignore_index=True)), pd.concat(
        trades, ignore_index=True
    )


def prepare(c, tip_by_key=None):
    c = c.copy()
    c["game"] = c.ticker.str.split("-").str[1]
    tip_by_key = L.tips() if tip_by_key is None else tip_by_key
    tip = pd.to_datetime(c.game.map(L.game_key).map(tip_by_key), utc=True)
    c["tip_ts"] = (tip - pd.Timestamp(0, tz="UTC")).dt.total_seconds()
    c = c[c.tip_ts.notna()]
    c = c[(c.yes_bid > 0) & (c.yes_ask < 1) & (c.yes_ask > c.yes_bid)].copy()
    c["mid"] = (c.yes_bid + c.yes_ask) / 2
    c = c.sort_values(["ticker", "end_ts"])
    c["prev_mid"] = c.groupby("ticker").mid.shift()
    c["prev_ts"] = c.groupby("ticker").end_ts.shift()
    c["move"] = c.mid - c.prev_mid
    ingame = (c.end_ts > c.tip_ts) & (c.end_ts <= c.tip_ts + GAME_HOURS * 3600)
    recent = (c.end_ts - c.prev_ts) <= MAX_GAP_SECONDS
    c = c[ingame & recent & c.move.notna()].copy()
    c["month"] = pd.to_datetime(c.end_ts, unit="s").dt.to_period("M")
    return c.reset_index(drop=True)


def orders(c, side, picked):
    q = c[picked].sort_values("end_ts").drop_duplicates("ticker").copy()
    spread = (q.yes_ask - q.yes_bid).round(4)
    q["improved"] = spread >= 2 * TICK - 1e-9
    if side == "no":
        q["price"] = np.round(
            np.where(q.improved, 1 - q.yes_ask + TICK, 1 - q.yes_ask), 4
        )
        q["yes_level"] = np.round(1 - q.price, 4)
    else:
        q["price"] = np.round(np.where(q.improved, q.yes_bid + TICK, q.yes_bid), 4)
        q["yes_level"] = q.price
    q["side"] = side
    q = q[(q.price > 0) & (q.price < 1)]
    won = (q.result == side).astype(float)
    q["pnl"] = won - q.price - maker_fee(q.price)
    return q


def fill(q, t):
    if q.empty:
        return q.assign(traded=0.0)
    tt = t[t.ticker.isin(set(q.ticker))].copy()
    stamp = pd.to_datetime(tt.created_time, utc=True, format="ISO8601")
    tt["ts"] = (stamp - pd.Timestamp(0, tz="UTC")).dt.total_seconds()
    placed = q[["ticker", "end_ts", "side", "yes_level", "improved"]].copy()
    placed["tip_ts"] = placed.end_ts + 3600
    got = fills(placed, tt)
    return q.assign(traded=q.ticker.map(got).fillna(0.0))


def measure(f, haircut=0.0):
    if len(f) < 2:
        return {"fills": int(len(f))}
    mean, tstat = clustered_mean_t(f.pnl.to_numpy() - haircut, f.game.to_numpy())
    by_month = f.groupby("month").pnl.mean()
    return {"fills": int(len(f)), "games": int(f.game.nunique()),
            "cents": round(100 * float(mean), 2),
            "t": round(float(tstat), 2) if math.isfinite(tstat) else None,
            "months_positive": int((by_month > 0).sum()), "months": int(len(by_month)),
            "avg_price": round(float(f.price.mean()), 3)}  # fmt: skip


def run(c, t):
    groups = {
        "fade_up_no": ("no", c.move >= JUMP),
        "fade_down_yes": ("yes", c.move <= -JUMP),
        "control_quiet_no": ("no", c.move.abs() < QUIET),
    }
    out, filled = {}, {}
    for name, (side, picked) in groups.items():
        q = fill(orders(c, side, picked), t)
        f = q[q.traded >= QUEUE]
        filled[name] = f
        out[name] = {"orders": int(len(q)), "before_haircut": measure(f),
                     "after_2c_haircut": measure(f, HAIRCUT),
                     "first_in_line": measure(q[q.traded >= 1])}  # fmt: skip
    up, ctrl = out["fade_up_no"], out["control_quiet_no"]
    gap = None
    if "cents" in up["before_haircut"] and "cents" in ctrl["before_haircut"]:
        gap = round(up["before_haircut"]["cents"] - ctrl["before_haircut"]["cents"], 2)
    a = up["after_2c_haircut"]
    passed = bool(
        (a.get("cents") or -1) > 0 and (a.get("t") or 0) >= BAR["t"]
        and a.get("fills", 0) >= BAR["fills"] and a.get("games", 0) >= BAR["games"]
        and gap is not None and gap >= 100 * BAR["over_control"]
    )  # fmt: skip
    return {
        "note": "SIMULATED, NBA props 2025-26, in-game hourly candles (tip-off to +3h). "
        "Resting one cent inside for an hour; 5+ contracts traded through. Not a forecast.",
        "ingame_candles": int(len(c)),
        "jumps_up": int((c.move >= JUMP).sum()),
        "falls": int((c.move <= -JUMP).sum()),
        **out,
        "fade_up_over_control_cents": gap,
        "variants": 3,
        "bar": BAR,
        "pass": passed,
    }


def main(argv=None):
    c, t = load()
    summary = run(c, t)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=1, default=str) + "\n", "utf-8"
    )
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
