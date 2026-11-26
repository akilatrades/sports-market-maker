"""Track 1: ladder outliers on every other Kalshi ladder (RESEARCH_LOG.md,
2026-11-26, "Four more tracks", plan written before any result). SIMULATED,
cross-market scan 2025-26; the NBA series the rule was chosen on are left
out.

    python -m research.ladder_all

Writes outputs/ladder_all/summary.json (aggregates only).
"""

import glob
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.stats import clustered_mean_t
from research.queue_stress import family

SCAN = "outputs/scan/orders_*.csv.gz"
OUT = Path("outputs/ladder_all")
COLUMNS = ["ticker", "end_ts", "yes_bid", "yes_ask", "side", "traded", "result",
           "event_ticker", "date", "pnl", "series", "price"]  # fmt: skip
EXCLUDED = {"KXNBAPTS", "KXNBAREB", "KXNBAAST", "KXNBA3PT"}
NUMBER = re.compile(r"^\d+(\.\d+)?$")
# --- the plan, fixed before results ---------------------------------------------
SHAPE_SHARE, SHAPE_HOURS, TOLERANCE = 0.90, 20, 0.01
MIN_STRIKES = 4
OUTLIER, CONTROL = 0.03, 0.01
THRESHOLDS = (0.02, 0.03, 0.05)
QUEUE, HAIRCUT = 5, 0.02
BAR = {"t": 2.5, "fills": 500, "events": 100, "over_control": 0.01, "months_share": 0.6}


def load(pattern=SCAN):
    frames = []
    for path in sorted(glob.glob(pattern)):
        try:
            f = pd.read_csv(path, usecols=lambda c: c in COLUMNS)
        except (ValueError, OSError, EOFError):
            continue
        if f.empty or f.series.iloc[0] in EXCLUDED:
            continue
        frames.append(f[f.side == "no"])
    return prepare(pd.concat(frames, ignore_index=True))


def prepare(d):
    d = d.copy()
    last = d.ticker.str.rsplit("-", n=1).str[-1]
    d = d[last.str.match(NUMBER)].copy()
    d["strike"] = d.ticker.str.rsplit("-", n=1).str[-1].astype(float)
    d["ladder"] = d.ticker.str.rsplit("-", n=1).str[0]
    for c in ("yes_bid", "yes_ask", "traded", "pnl", "price", "end_ts"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d[(d.yes_bid > 0) & (d.yes_ask < 1) & (d.yes_ask > d.yes_bid)]
    d = d.drop_duplicates(["ticker", "end_ts"])
    d["mid"] = (d.yes_bid + d.yes_ask) / 2
    d["month"] = pd.to_datetime(d.date, errors="coerce").dt.to_period("M")
    return d.reset_index(drop=True)


def shaped_series(d):
    """Series whose ladders fall with the strike in 90%+ of hours (prices only)."""
    rows = []
    for (series, _, _), g in d.groupby(["series", "ladder", "end_ts"]):
        if len(g) < 3:
            continue
        mids = g.sort_values("strike").mid.to_numpy()
        rows.append((series, bool((np.diff(mids) <= TOLERANCE + 1e-9).all())))
    s = (
        pd.DataFrame(rows, columns=["series", "falls"])
        .groupby("series")
        .falls.agg(["mean", "size"])
    )
    keep = s[(s["mean"] >= SHAPE_SHARE) & (s["size"] >= SHAPE_HOURS)]
    return set(keep.index), s


def residuals(d):
    d = d.copy()
    d["resid"] = np.nan
    for _, idx in d.groupby(["ladder", "end_ts"]).groups.items():
        if len(idx) < MIN_STRIKES:
            continue
        x = d.loc[idx, "strike"].to_numpy(float)
        y = np.clip(d.loc[idx, "mid"].to_numpy(float), 0.01, 0.99)
        if np.ptp(x) == 0:
            continue
        slope, intercept = np.polyfit(x, np.log(y / (1 - y)), 1)
        d.loc[idx, "resid"] = y - 1 / (1 + np.exp(-(intercept + slope * x)))
    return d.dropna(subset=["resid"])


def group(r, low, high, queue=QUEUE):
    q = (
        r[(r.resid >= low) & (r.resid <= high)]
        .sort_values("end_ts")
        .drop_duplicates("ticker")
    )
    return q[(q.traded >= queue) & q.pnl.notna() & q.result.isin(["yes", "no"])]


def measure(f, haircut=0.0):
    if len(f) < 2:
        return {"fills": int(len(f))}
    mean, t = clustered_mean_t(f.pnl.to_numpy() - haircut, f.event_ticker.to_numpy())
    by_month = f.groupby("month").pnl.mean()
    return {"fills": int(len(f)), "events": int(f.event_ticker.nunique()),
            "series": int(f.series.nunique()), "cents": round(100 * float(mean), 2),
            "t": round(float(t), 2) if math.isfinite(t) else None,
            "months_positive": int((by_month > 0).sum()), "months": int(len(by_month)),
            "avg_no_price": round(float(f.price.mean()), 3)}  # fmt: skip


def run(d):
    keep, shape = shaped_series(d)
    r = residuals(d[d.series.isin(keep)])
    out_group = group(r, OUTLIER, 1.0)
    control = group(r, -CONTROL, CONTROL)
    before, after, ctrl = (
        measure(out_group),
        measure(out_group, HAIRCUT),
        measure(control),
    )
    gap = (
        None
        if "cents" not in before or "cents" not in ctrl
        else round(before["cents"] - ctrl["cents"], 2)
    )
    months_ok = (
        before.get("months")
        and before["months_positive"] / before["months"] >= BAR["months_share"]
    )
    passed = bool(
        (after.get("cents") or -1) > 0 and (after.get("t") or 0) >= BAR["t"]
        and after.get("fills", 0) >= BAR["fills"] and after.get("events", 0) >= BAR["events"]
        and gap is not None and gap >= 100 * BAR["over_control"] and months_ok
    )  # fmt: skip
    fam = out_group.assign(fam=out_group.series.map(family))
    return {
        "note": "SIMULATED (cross-market scan 2025-26, 7-4 hours before expiration), NBA "
        "points/rebounds/assists/threes excluded. Resting NO one cent inside on strikes "
        "above the ladder's fitted curve; 5+ contracts traded through. Not a forecast.",
        "series_with_numbered_ladders": int(shape.shape[0]),
        "series_passing_shape_check": len(keep),
        "ladder_hours_fitted": int(r.groupby(["ladder", "end_ts"]).ngroups),
        "primary": {"before_haircut": before, "after_2c_haircut": after, "control": ctrl,
                    "over_control_cents": gap},  # fmt: skip
        "thresholds": {f"+{round(100 * th)}c": measure(group(r, th, 1.0)) for th in THRESHOLDS},
        "by_family_before_haircut": {k: measure(g) for k, g in fam.groupby("fam") if len(g) >= 30},
        "top_series": out_group.groupby("series").pnl.agg(["size", "mean"])
        .sort_values("size", ascending=False).head(12)
        .assign(mean=lambda x: (100 * x["mean"]).round(2)).to_dict("index"),
        "variants": 3,
        "bar": BAR,
        "pass": passed,
    }  # fmt: skip


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
