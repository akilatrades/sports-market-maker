"""Spread maker: more pregame fills from start times per series and earlier
quoting (pre-registered; RESEARCH_LOG.md, 2026-10-23, "Spread maker, more
pregame fills").

Reads the 24-to-4-hour scan (``outputs/scan_24h``: order rows plus each
event's ticker start and Kalshi milestones), builds three start-time sources,
replays 9 rules x 2 flow shares and checks the plan's pass bar. SIMULATED and
in-sample: one contract, both sides one cent inside spreads of 8c or more,
first in line (flow share 1) or each traded contract reaching us with
probability 0.25 (median of 20 draws), held to settlement.

    python -m research.spread_start_window   # outputs/research/spread_start_window.{json,md}
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.stats import clustered_mean_t
from live.prod_spread_auto import ticker_start
from research.strategy_sweep import MAKER_FEE_SERIES

SCAN = Path("outputs/scan_24h")
OUT = Path("outputs/research")
MIN_SPREAD = 0.08
MIN_LEAD_MINUTES = 85  # live v2: a new quote needs the start this far away
MILESTONE_WINDOW_HOURS = 12  # live v2: a milestone counts within 12 h of expiry
AGREE = (-15 * 60, 2 * 60)  # milestone minus ticker start, seconds
TYPE_MIN_EVENTS, TYPE_MIN_SHARE = 20, 0.95
OFFSET_MAX_IQR = 30 * 60  # seconds
OFFSET_MARGIN = 30 * 60  # S3 start = expiry - median offset - this
OFFSET_MIN_EVENTS = 10  # implementation detail: an IQR needs some events
WINDOWS = (7, 12, 24)  # hours before expiry; all down to the scan's 4 hours
SOURCES = {"S1": ("S1",), "S1+S2": ("S1", "S2"), "S1+S2+S3": ("S1", "S2", "S3")}
DRAWS = 20


def _ts(value):
    t = pd.to_datetime(value, utc=True, errors="coerce")
    return np.nan if pd.isna(t) else t.timestamp()


def load_rows(folder=SCAN):
    """Order rows as the pilot's replay builds them, plus hours before expiry."""
    frames = []
    for path in sorted(Path(folder).glob("orders_*.csv.gz")):
        rows = pd.read_csv(path, low_memory=False)
        frames.append(rows[rows.result.isin(["yes", "no"])])
    if not frames:
        return pd.DataFrame()
    r = pd.concat(frames, ignore_index=True)
    r = r[(r.yes_bid > 0) & (r.yes_ask < 1) & (r.yes_ask > r.yes_bid)].copy()
    r["traded"] = np.floor(pd.to_numeric(r.traded, errors="coerce").fillna(0))
    fee = np.where(
        r.series.isin(MAKER_FEE_SERIES), 0.0175 * r.price * (1 - r.price), 0.0
    )
    r["pnl"] = r.won.astype(float) - r.price - fee
    r["day"] = pd.to_datetime(r.date, errors="coerce")
    r = r[r.day.notna()]
    r["half"] = np.where(r.day < r.day.median(), "earlier", "later")
    r["spread"] = (r.yes_ask - r.yes_bid).round(2)
    return r[r.spread >= MIN_SPREAD - 1e-9].reset_index(drop=True)


def load_events(folder=SCAN):
    frames = [pd.read_csv(p) for p in sorted(Path(folder).glob("events_*.csv.gz"))]
    if not frames:
        return pd.DataFrame(columns=["event_ticker", "expiry", "s1", "milestones"])
    e = pd.concat(frames, ignore_index=True).drop_duplicates("event_ticker")
    e["expiry"] = e.expiry.map(_ts)
    e["s1"] = e.event_ticker.map(
        lambda x: (lambda s: s.timestamp() if s else np.nan)(ticker_start(x))
    )
    e["milestones"] = e.milestones.map(
        lambda x: json.loads(x) if isinstance(x, str) and x else []
    )
    e["series"] = e.event_ticker.str.split("-").str[0]
    return e.reset_index(drop=True)


def milestone_by_type(e):
    """{event: {type: earliest start within the window before expiry}}."""
    out = {}
    for row in e.itertuples():
        found = {}
        for m in row.milestones:
            start = _ts(m.get("start"))
            if np.isnan(start) or np.isnan(row.expiry):
                continue
            if not row.expiry - MILESTONE_WINDOW_HOURS * 3600 <= start <= row.expiry:
                continue
            kind = str(m.get("type") or "")
            found[kind] = min(found.get(kind, start), start)
        out[row.event_ticker] = found
    return out


def trusted_types(e, by_type):
    """Milestone types that match ticker starts closely enough (S2's check)."""
    stats = {}
    for row in e[e.s1.notna()].itertuples():
        for kind, start in by_type.get(row.event_ticker, {}).items():
            ok = AGREE[0] <= start - row.s1 <= AGREE[1]
            n, good = stats.get(kind, (0, 0))
            stats[kind] = (n + 1, good + int(ok))
    table = {
        k: {"events": n, "share_agreeing": round(g / n, 3)}
        for k, (n, g) in stats.items()
    }
    for v in table.values():
        v["trusted"] = (
            v["events"] >= TYPE_MIN_EVENTS and v["share_agreeing"] >= TYPE_MIN_SHARE
        )
    return table


def starts(e, sources, by_type, types):
    """{event: start seconds} from the chosen sources, in order S1, S2, S3."""
    s1 = dict(zip(e.event_ticker, e.s1))
    s2 = {}
    for event, found in by_type.items():
        ok = [t for k, t in found.items() if types.get(k, {}).get("trusted")]
        if ok:
            s2[event] = min(ok)
    known = {}
    if "S1" in sources:
        known.update({k: v for k, v in s1.items() if not np.isnan(v)})
    if "S2" in sources:
        for k, v in s2.items():
            known.setdefault(k, v)
    offsets = {}
    if "S3" in sources:
        offsets = series_offsets(
            e, {**{k: v for k, v in s1.items() if not np.isnan(v)}, **s2}
        )
        for row in e.itertuples():
            o = offsets.get(row.series)
            if row.event_ticker not in known and o and o["usable"]:
                known[row.event_ticker] = row.expiry - o["median_s"] - OFFSET_MARGIN
    return known, offsets


def series_offsets(e, known):
    """Per series: median and middle-half spread of (expiry - start)."""
    gaps = {}
    for row in e.itertuples():
        if row.event_ticker in known and not np.isnan(row.expiry):
            gaps.setdefault(row.series, []).append(row.expiry - known[row.event_ticker])
    out = {}
    for series, g in gaps.items():
        g = np.asarray(g, dtype=float)
        q1, med, q3 = np.percentile(g, [25, 50, 75])
        out[series] = {
            "events": len(g),
            "median_s": float(med),
            "iqr_s": float(q3 - q1),
            "usable": len(g) >= OFFSET_MIN_EVENTS and q3 - q1 <= OFFSET_MAX_IQR,
        }
    return out


def select(r, known, hi):
    """Pregame quotes under a rule: inside the window, start known, 85+ min ahead."""
    start = r.event_ticker.map(known)
    keep = (
        (r.hours_before_expiry <= hi + 1e-9)
        & start.notna()
        & (start - r.end_ts >= MIN_LEAD_MINUTES * 60)
    )
    return r[keep]


def fills(q, share=1.0, seed=0):
    if share >= 1:
        return q[q.traded >= 1]
    got = np.random.default_rng(seed).binomial(q.traded.astype(np.int64), share)
    return q[got >= 1]


def stats(f):
    out = {"fills": int(len(f)), "dollars": round(float(f.pnl.sum()), 2)}
    if len(f) >= 30:
        mean, t = clustered_mean_t(f.pnl, f.event_ticker)
        out.update(
            events=int(f.event_ticker.nunique()),
            cents_per_contract=round(100 * float(mean), 2),
            t_event_clustered=round(float(t), 2),
            earlier_half_cents=round(100 * float(f[f.half == "earlier"].pnl.mean()), 2),
            later_half_cents=round(100 * float(f[f.half == "later"].pnl.mean()), 2),
        )
    return out


def added(f, base):
    key = ["ticker", "end_ts", "side"]
    m = f.merge(base[key].assign(_b=1), on=key, how="left")
    return m[m._b.isna()].drop(columns="_b")


def judge(variant, base_fills, added_1, added_cautious):
    """The plan's bar, item by item."""
    a = stats(added_1)
    by_series = added_1.groupby("series").pnl.sum()
    top = (
        float(by_series.max() / by_series[by_series > 0].sum())
        if (by_series > 0).any()
        else None
    )
    checks = {
        "1 at least 2x the baseline's fills": variant["fills"] >= 2 * base_fills,
        "2a added fills positive with t >= 2 (flow 1)": (
            a.get("cents_per_contract") or 0
        )
        > 0
        and (a.get("t_event_clustered") or 0) >= 2,
        "2b added fills positive at flow 0.25": float(np.median(added_cautious)) > 0,
        "3 added fills positive in both halves": (a.get("earlier_half_cents") or 0) > 0
        and (a.get("later_half_cents") or 0) > 0,
        "4 no series over a quarter of added profit": top is not None and top <= 0.25,
    }
    return checks, a, top


def main():
    r, e = load_rows(), load_events()
    if r.empty or e.empty:
        raise SystemExit(
            f"No scan data in {SCAN}; run the market scan with window 24,4"
        )
    by_type = milestone_by_type(e)
    types = trusted_types(e, by_type)
    result = {
        "note": "SIMULATED, in-sample, pre-registered (RESEARCH_LOG.md, 2026-10-23); 1 contract, 8c+ spreads",
        "scan": {
            "order_rows": int(len(r)),
            "events": int(len(e)),
            "events_with_ticker_start": int(e.s1.notna().sum()),
            "events_with_milestones": int(sum(bool(v) for v in by_type.values())),
            "series": int(r.series.nunique()),
        },
        "milestone_types": types,
        "variants": {},
    }
    base_q = select(r, starts(e, SOURCES["S1"], by_type, types)[0], 7)
    base = fills(base_q)
    offsets_seen = {}
    for name, sources in SOURCES.items():
        known, offsets = starts(e, sources, by_type, types)
        offsets_seen.update(offsets)
        for hi in WINDOWS:
            q = select(r, known, hi)
            f1 = fills(q)
            v = stats(f1)
            cautious = [fills(q, 0.25, s) for s in range(DRAWS)]
            v["flow_0.25_median"] = {
                "fills": int(np.median([len(c) for c in cautious])),
                "cents_per_contract": round(
                    100 * float(np.median([c.pnl.mean() for c in cautious if len(c)])),
                    2,
                ),
            }
            label = f"{hi}->4 h, {name}"
            if (hi, name) != (7, "S1"):
                a1 = added(f1, base)
                add_c = [added(c, base).pnl.mean() for c in cautious]
                add_c = [x for x in add_c if not np.isnan(x)] or [0.0]
                checks, a, top = judge(v, len(base), a1, add_c)
                v["added_over_baseline"] = {
                    **a,
                    "top_series_share_of_added_profit": top,
                }
                v["checks"] = checks
                v["passes"] = all(checks.values())
            result["variants"][label] = v
    result["series_offsets_hours"] = {
        s: {
            "events": o["events"],
            "median": round(o["median_s"] / 3600, 2),
            "iqr": round(o["iqr_s"] / 3600, 2),
            "usable": o["usable"],
        }
        for s, o in sorted(offsets_seen.items())
    }
    passing = [(k, v) for k, v in result["variants"].items() if v.get("passes")]
    result["proposed_v3"] = (
        max(passing, key=lambda kv: kv[1]["added_over_baseline"]["fills"])[0]
        if passing
        else None
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "spread_start_window.json").write_text(
        json.dumps(result, indent=1, default=lambda o: o.item()) + "\n"
    )
    lines = [
        "# Spread maker: start times and earlier quoting (SIMULATED, in-sample, pre-registered)",
        "",
        "| Rule | Fills | ¢/contract (t) | Halves ¢ | Flow 0.25 fills | Added fills | Added ¢ (t) | Passes |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for k, v in result["variants"].items():
        a = v.get("added_over_baseline") or {}
        lines.append(
            f"| {k} | {v['fills']:,} | {v.get('cents_per_contract', '—')} ({v.get('t_event_clustered', '—')}) | "
            f"{v.get('earlier_half_cents', '—')} / {v.get('later_half_cents', '—')} | "
            f"{v['flow_0.25_median']['fills']:,} | {a.get('fills', '—')} | "
            f"{a.get('cents_per_contract', '—')} ({a.get('t_event_clustered', '—')}) | "
            f"{'baseline (v2)' if 'passes' not in v else ('yes' if v['passes'] else 'no')} |"
        )
    lines += ["", f"Proposed v3: {result['proposed_v3'] or 'none; v2 stays'}"]
    (OUT / "spread_start_window.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
