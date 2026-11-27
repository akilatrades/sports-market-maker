"""The frozen Study B ladder rule on fresh data (RESEARCH_LOG.md: 2026-11-26
"Ladders, deeper" part B, other sports; 2026-11-27 C1, this season's NBA).
SIMULATED from public candles and trades in data/kalshi_history_ladders/.

    python -m research.ladder_fresh nba      # C1: KXNBAPTS/REB/AST/3PT since 2026-10-20
    python -m research.ladder_fresh other    # part B: every other downloaded series

Writes outputs/ladder_fresh/<which>.json (aggregates only).
"""

import glob
import json
import sys
from pathlib import Path

import pandas as pd

from research import ladder as L
from research import ladder_all as A

DATA = Path("data/kalshi_history_ladders")
OUT = Path("outputs/ladder_fresh")
NBA = ("KXNBAPTS", "KXNBAREB", "KXNBAAST", "KXNBA3PT")
NBA_START = pd.Timestamp("2026-10-20", tz="UTC")
# --- the plans, fixed before results --------------------------------------------
TIP_HOURS = {"nba": 3, "other": 4}  # occurrence time minus this = before the game
BARS = {
    "nba": {"t": 2.0, "fills": 100, "games": 40, "over_control": 0.01},
    "other": {"t": 2.5, "fills": 500, "games": 100, "over_control": 0.01},
}
HAIRCUT, THIN_HAIRCUT = 0.02, 0.005


def load(which, data=DATA):
    names = [
        Path(p).stem.removeprefix("markets_")
        for p in sorted(glob.glob(f"{data}/markets_*.parquet"))
    ]
    names = [n for n in names if (n in NBA) == (which == "nba")]
    candles, trades = [], []
    for s in names:
        cpath, tpath = data / f"candles_{s}.parquet", data / f"trades_{s}.parquet"
        if not cpath.exists():
            continue
        m = pd.read_parquet(data / f"markets_{s}.parquet")
        c = pd.read_parquet(cpath).merge(
            m[["ticker", "floor_strike", "occurrence_datetime", "close_time",
               "expected_expiration_time", "result"]], on="ticker")  # fmt: skip
        c["series"] = s
        candles.append(c)
        if tpath.exists():
            trades.append(pd.read_parquet(tpath))
    if not candles:
        return pd.DataFrame(), pd.DataFrame()
    t = pd.concat(trades, ignore_index=True) if trades else pd.DataFrame(
        columns=["ticker", "created_time", "yes_price", "count", "taker_outcome_side"])  # fmt: skip
    return prepare(pd.concat(candles, ignore_index=True), which), t


def prepare(c, which):
    c = c.copy()

    def utc(col):
        return pd.to_datetime(c[col], utc=True, format="ISO8601", errors="coerce")

    anchor = (
        utc("occurrence_datetime")
        .fillna(utc("expected_expiration_time"))
        .fillna(utc("close_time"))
    )
    tip = anchor - pd.Timedelta(hours=TIP_HOURS[which])
    end = pd.to_datetime(c.end_ts, unit="s", utc=True)
    keep = (end <= tip) & c.result.isin(["yes", "no"])
    if which == "nba":
        keep &= anchor >= NBA_START
    c = c[keep & (c.yes_bid > 0) & (c.yes_ask < 1) & (c.yes_ask > c.yes_bid)].copy()
    suffix = pd.to_numeric(c.ticker.str.rsplit("-", n=1).str[-1], errors="coerce")
    c["floor_strike"] = pd.to_numeric(c.floor_strike, errors="coerce").fillna(
        suffix - 0.5
    )
    c["strike"] = c.floor_strike
    c["ladder"] = c.ticker.str.rsplit("-", n=1).str[0]
    c["game"] = c.ticker.str.split("-").str[1]
    c["event_ticker"] = c.game
    c["month"] = end.loc[c.index].dt.tz_localize(None).dt.to_period("M")
    c["mid"] = (c.yes_bid + c.yes_ask) / 2
    c["has_trades"] = True
    return c.dropna(subset=["floor_strike"]).reset_index(drop=True)


def group(r, t, low, high):
    o = L.orders(r, low, high)
    o["traded"] = o.ticker.map(L.traded_through(o, t)).fillna(0)
    return o[o.traded >= L.QUEUE]


def run(c, t, which):
    bar = BARS[which]
    if c.empty:
        return {"which": which, "status": "no data yet"}
    kept = set(c.series.unique())
    if which == "other":
        kept, _ = A.shaped_series(c)
        c = c[c.series.isin(kept)]
    r = L.residuals(c)
    out_f, ctrl = group(r, t, L.THRESHOLD, 1.0), group(r, t, -0.01, 0.01)
    before, after, thin, control = (L.measure(out_f), L.measure(out_f, HAIRCUT),
                                    L.measure(out_f, THIN_HAIRCUT), L.measure(ctrl))  # fmt: skip
    gap = (
        None
        if "cents" not in before or "cents" not in control
        else round(before["cents"] - control["cents"], 2)
    )
    passed = bool(
        (after.get("cents") or -1) > 0 and (after.get("t") or 0) >= bar["t"]
        and after.get("fills", 0) >= bar["fills"] and after.get("games", 0) >= bar["games"]
        and gap is not None and gap >= 100 * bar["over_control"]
    )  # fmt: skip
    spread = (out_f.yes_ask - out_f.yes_bid).round(4)
    return {
        "which": which,
        "note": "SIMULATED from public candles and trades; resting NO one cent inside on "
        "strikes 3+ cents above the ladder's logit curve; 5+ contracts traded through.",
        "series_used": sorted(kept),
        "ladder_hours_fitted": int(r.groupby(["ladder", "end_ts"]).ngroups),
        "outlier_before_haircut": before,
        "outlier_after_2c_haircut": after,
        "outlier_after_0_5c_haircut": thin,
        "control": control,
        "over_control_cents": gap,
        "refinement_spread_3c_plus": L.measure(out_f[spread >= 0.03 - 1e-9]),
        "yes_happened_vs_mid_all_outlier_orders": {
            "yes": round(
                float((L.orders(r, L.THRESHOLD, 1.0).result == "yes").mean()), 4
            ),
            "mid": round(float(L.orders(r, L.THRESHOLD, 1.0).mid.mean()), 4),
        }
        if len(r)
        else None,
        "bar": bar,
        "pass": passed,
    }


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    which = argv[0] if argv else "nba"
    c, t = load(which)
    summary = run(c, t, which)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{which}.json").write_text(
        json.dumps(summary, indent=1, default=str) + "\n", "utf-8"
    )
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
