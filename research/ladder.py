"""Study B: the strike ladder as an option chain (RESEARCH_LOG.md, 2026-11-26,
plan written before any result). NBA points, rebounds, assists and threes,
2025-26, pre-game hourly candles. SIMULATED.

B1 counts ladder-hours where a higher strike's YES bid exceeds a lower
strike's YES ask by more than two taker fees (riskless on paper). B2 fits
logit(mid) = a - b x strike per ladder-hour and rests NO one cent inside on
strikes priced above the curve, with the scan's fill rule.

    python -m research.ladder

Writes outputs/ladder/summary.json and grid.csv (aggregates only).
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.maker import maker_fee
from kalshi.stats import clustered_mean_t

HIST = Path("data/kalshi_history")
OUT = Path("outputs/ladder")
SERIES = ("KXNBAPTS", "KXNBAREB", "KXNBAAST", "KXNBA3PT")
TICK = 0.01
BOX = Path("data/player_games.parquet")
KALSHI_TO_ESPN = {
    "GSW": "GS",
    "NYK": "NY",
    "SAS": "SA",
    "NOP": "NO",
    "UTA": "UTAH",
    "WAS": "WSH",
}

# --- the plan, fixed before results ---------------------------------------------
PREGAME_HOURS = 3  # fallback: tip-off = occurrence time - 3 hours
MIN_STRIKES = 4
THRESHOLD, QUEUE = 0.03, 5
THRESHOLDS, QUEUES = (0.02, 0.03, 0.05), (1, 5)
HAIRCUT = 0.02
BAR = {"t": 2.5, "fills": 500, "games": 100, "months_positive": 5, "over_middle": 0.01}


def taker_fee(p):
    return np.ceil(np.round(0.07 * p * (1 - p) * 100, 6)) / 100


def load(hist=HIST, series=SERIES):
    candles, trades = [], []
    for s in series:
        m = pd.read_parquet(hist / f"markets_{s}.parquet")
        m = m[m.result.isin(["yes", "no"])][
            ["ticker", "floor_strike", "occurrence_datetime", "result"]
        ]
        c = pd.read_parquet(hist / f"candles_{s}.parquet").merge(m, on="ticker")
        done = set((hist / f"trades_done_{s}.txt").read_text().split())
        c["has_trades"] = c.ticker.isin(done)
        c["series"] = s
        candles.append(c)
        t = pd.read_parquet(hist / f"trades_{s}.parquet")
        trades.append(
            t[["ticker", "created_time", "yes_price", "count", "taker_outcome_side"]]
        )
    return prepare(pd.concat(candles, ignore_index=True)), pd.concat(
        trades, ignore_index=True
    )


def tips(box=BOX):
    """Kalshi game code ("25DEC01PHXLAL": date, away, home) -> tip-off, from
    the box scores (the occurrence time is missing before April 2026)."""
    b = pd.read_parquet(box)
    b = b[b.home.astype(bool)][["game_date", "team", "tip_utc"]].drop_duplicates()
    b["key"] = (
        pd.to_datetime(b.game_date).dt.strftime("%y%b%d").str.upper() + "|" + b.team
    )
    return b.drop_duplicates("key").set_index("key").tip_utc


def game_key(code):
    home = code[-3:]
    return code[:7] + "|" + KALSHI_TO_ESPN.get(home, home)


def prepare(c, tip_by_key=None):
    c = c.copy()
    c["game"] = c.ticker.str.split("-").str[1]
    tip_by_key = tips() if tip_by_key is None else tip_by_key
    tip = pd.to_datetime(c.game.map(game_key).map(tip_by_key), utc=True)
    occ = pd.to_datetime(
        c.occurrence_datetime, utc=True, format="ISO8601", errors="coerce"
    )
    tip = tip.fillna(occ - pd.Timedelta(hours=PREGAME_HOURS))
    end = pd.to_datetime(c.end_ts, unit="s", utc=True)
    c = c[end <= tip]
    c = c[(c.yes_bid > 0) & (c.yes_ask < 1) & (c.yes_ask > c.yes_bid)].copy()
    c["ladder"] = c.ticker.str.rsplit("-", n=1).str[0]
    c["month"] = pd.to_datetime(c.end_ts, unit="s").dt.to_period("M")
    c["mid"] = (c.yes_bid + c.yes_ask) / 2
    return c.reset_index(drop=True)


def arbitrage(c):
    """Ladder-hours where buying the lower YES and the higher NO pays at
    least $1 in every outcome for less than $1 after taker fees."""
    rows, crossings = [], 0
    for (ladder, ts), g in c.groupby(["ladder", "end_ts"]):
        if len(g) < 2:
            continue
        g = g.sort_values("floor_strike")
        ask, bid = g.yes_ask.to_numpy(), g.yes_bid.to_numpy()
        vol = g.volume.to_numpy()
        best, crossed = -1.0, False
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                crossed |= bool(bid[j] > ask[i] + 1e-9)
                profit = bid[j] - ask[i] - taker_fee(ask[i]) - taker_fee(1 - bid[j])
                if profit > best:
                    best, v = profit, min(vol[i], vol[j])
        crossings += crossed
        if best > 0:
            rows.append({"ladder": ladder, "end_ts": ts, "profit": best, "volume": v,
                         "month": g.month.iloc[0]})  # fmt: skip
    a = pd.DataFrame(rows, columns=["ladder", "end_ts", "profit", "volume", "month"])
    hours = c.groupby(["ladder", "end_ts"]).ngroups
    return {
        "ladder_hours": int(hours),
        "crossed_before_fees": int(crossings),
        "with_arbitrage": int(len(a)),
        "share": round(len(a) / hours, 5) if hours else None,
        "median_profit_cents": round(100 * float(a.profit.median()), 2)
        if len(a)
        else None,
        "max_profit_cents": round(100 * float(a.profit.max()), 2) if len(a) else None,
        "ladders": int(a.ladder.nunique()),
        "with_volume_in_both": int((a.volume > 0).sum()),
        "by_month": a.groupby(a.month.astype(str)).size().to_dict(),
    }


def residuals(c):
    """Residual of each strike's mid from a logistic curve fitted to its
    ladder-hour (4+ two-sided strikes)."""
    c = c.copy()
    c["resid"] = np.nan
    for _, idx in c.groupby(["ladder", "end_ts"]).groups.items():
        if len(idx) < MIN_STRIKES:
            continue
        g = c.loc[idx]
        x = g.floor_strike.to_numpy(float)
        y = np.clip(g.mid.to_numpy(float), 0.01, 0.99)
        if np.ptp(x) == 0:
            continue
        slope, intercept = np.polyfit(x, np.log(y / (1 - y)), 1)
        fit = 1 / (1 + np.exp(-(intercept + slope * x)))
        c.loc[idx, "resid"] = y - fit
    return c.dropna(subset=["resid"])


def orders(r, low, high):
    """First qualifying hour per market with residual in [low, high]:
    a NO bid one cent inside (the scan's rule)."""
    q = r[(r.resid >= low) & (r.resid <= high) & r.has_trades].sort_values("end_ts")
    q = q.drop_duplicates("ticker").copy()
    spread = (q.yes_ask - q.yes_bid).round(4)
    q["improved"] = spread >= 2 * TICK - 1e-9
    q["price"] = np.round(np.where(q.improved, 1 - q.yes_ask + TICK, 1 - q.yes_ask), 4)
    q["yes_level"] = np.round(1 - q.price, 4)
    q = q[(q.price > 0) & (q.price < 1)]
    q["pnl"] = (q.result == "no").astype(float) - q.price - maker_fee(q.price)
    return q


def traded_through(o, t):
    """Contracts YES buyers traded through each NO bid in the next hour."""
    if o.empty:
        return pd.Series(dtype=float)
    t = t[t.ticker.isin(set(o.ticker)) & (t.taker_outcome_side == "yes")].copy()
    stamp = pd.to_datetime(t.created_time, utc=True, format="ISO8601")
    t["ts"] = (stamp - pd.Timestamp(0, tz="UTC")).dt.total_seconds()
    m = t.merge(o[["ticker", "end_ts", "yes_level", "improved"]], on="ticker")
    m = m[(m.ts > m.end_ts) & (m.ts <= m.end_ts + 3600)]
    same = (m.yes_price - m.yes_level).abs() < 1e-6
    hit = (m.yes_price > m.yes_level + 1e-6) | (same & m.improved)
    return m[hit].groupby("ticker")["count"].sum()


def measure(f, haircut=0.0):
    if len(f) < 2:
        return {"fills": int(len(f))}
    mean, t = clustered_mean_t(f.pnl.to_numpy() - haircut, f.game.to_numpy())
    by_month = f.groupby("month").pnl.mean()
    return {"fills": int(len(f)), "games": int(f.game.nunique()),
            "cents": round(100 * float(mean), 2),
            "t": round(float(t), 2) if math.isfinite(t) else None,
            "months_positive": int((by_month > 0).sum()), "months": int(len(by_month)),
            "avg_no_price": round(float(f.price.mean()), 3)}  # fmt: skip


def group(r, t, low, high, queue):
    o = orders(r, low, high)
    o["traded"] = o.ticker.map(traded_through(o, t)).fillna(0)
    return o[o.traded >= queue]


def run(c, t):
    r = residuals(c)
    grid = []
    for th in THRESHOLDS:
        for q in QUEUES:
            f = group(r, t, th, 1.0, q)
            grid.append(
                {"group": f"resid >= +{round(100 * th)}c", "queue": q, **measure(f)}
            )
    for name, (lo, hi) in {
        "resid <= -3c": (-1.0, -0.03),
        "resid -1c..+1c": (-0.01, 0.01),
    }.items():
        for q in QUEUES:
            grid.append({"group": name, "queue": q, **measure(group(r, t, lo, hi, q))})
    over = group(r, t, THRESHOLD, 1.0, QUEUE)
    middle = group(r, t, -0.01, 0.01, QUEUE)
    before, after, mid = measure(over), measure(over, HAIRCUT), measure(middle)
    gap = (
        None
        if "cents" not in before or "cents" not in mid
        else round(before["cents"] - mid["cents"], 2)
    )
    passed = bool(
        (after.get("cents") or -1) > 0 and (after.get("t") or 0) >= BAR["t"]
        and after.get("fills", 0) >= BAR["fills"] and after.get("games", 0) >= BAR["games"]
        and before.get("months_positive", 0) >= BAR["months_positive"]
        and gap is not None and gap >= 100 * BAR["over_middle"]
    )  # fmt: skip
    return pd.DataFrame(grid), {
        "note": "SIMULATED, NBA props 2025-26, pre-game hourly candles; resting NO one cent "
        "inside, filled when `queue` contracts trade through in the next hour. Cents per "
        "contract after the maker fee. Not a forecast.",
        "ladder_hours_fitted": int(r.groupby(["ladder", "end_ts"]).ngroups),
        "residual_spread_cents": {
            k: round(100 * float(v), 2)
            for k, v in r.resid.quantile([0.05, 0.25, 0.5, 0.75, 0.95]).items()
        },  # fmt: skip
        "B1_arbitrage": arbitrage(c),
        "B2_primary": {
            "before_haircut": before,
            "after_2c_haircut": after,
            "middle_group": mid,
            "over_minus_middle_cents": gap,
        },  # fmt: skip
        "variants": 6,
        "bar": BAR,
        "pass": passed,
    }


def main(argv=None):
    c, t = load()
    grid, summary = run(c, t)
    OUT.mkdir(parents=True, exist_ok=True)
    grid.to_csv(OUT / "grid.csv", index=False)
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=1, default=str) + "\n", "utf-8"
    )
    print(grid.to_string(index=False))
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
