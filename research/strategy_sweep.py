"""Nine resting-order strategy families across all scanned Kalshi markets,
with profit factor (exploratory).

Plan: RESEARCH_LOG.md, "2026-10-22: Strategy sweep across all scanned
markets, with profit factor (exploratory plan)". Simulated from the scan's
hourly resting-order rows: one contract per order, first in line, held to
settlement. Profit factor = winning dollars / losing dollars.

    python -m research.strategy_sweep   # writes outputs/research/strategy_sweep.{json,md}
"""

import json
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

from research.explore_strategies import category
from research.fill_sizing_replay import clustered_mean_t

SCAN = Path("outputs/scan")
OUT = Path("outputs/research")
COLUMNS = [
    "ticker",
    "end_ts",
    "yes_bid",
    "yes_ask",
    "price",
    "volume",
    "side",
    "traded",
    "won",
    "result",
    "event_ticker",
    "date",
    "series",
]
# Series with a maker multiplier on Kalshi's fee schedule (checked 2026-10-22).
MAKER_FEE_SERIES = {
    "KXINXY", "KXNASDAQ100Y", "KXCPI", "KXCPIYOY", "KXFED", "KXFEDDECISION", "KXGDP",
    "KXPAYROLLS", "KXU3", "KXRATECUTCOUNT", "KXIPO", "KXLLM1", "KXBTCMAX150", "KXAAAGASM",
    "KXEGGS", "KXATPMATCH", "KXWTAMATCH", "KXBALLONDOR", "KXLALIGA", "KXHEISMAN",
    "KXMARMAD", "KXMENWORLDCUP", "KXWCGAME", "KXSB", "KXSUPERBOWLHEADLINE", "KXUCL",
    "KXUCLGAME", "KXNBA", "KXNBAEAST", "KXNBAWEST", "KXNBAMVP", "KXNBAROY", "KXWNBA",
    "KXWNBAGAME", "KXMLB", "KXMLBAL", "KXMLBNL", "KXMLBASGAME", "KXMLBGAME", "KXNHL",
    "KXNHLEAST", "KXNHLWEST", "KXNCAAF", "KXNCAAFACC", "KXNCAAFB10", "KXNCAAFB12",
    "KXNCAAFSEC", "KXNCAAFGAME", "KXNCAAFPLAYOFF", "KXNFLGAME", "KXNFLMVP", "KXPGATOUR",
}  # fmt: skip
MIN_FILLS = 300
TOP = 10


def load(folder=SCAN):
    frames = []
    for path in sorted(Path(folder).glob("orders_*.csv.gz")):
        try:
            rows = pd.read_csv(path, usecols=COLUMNS, low_memory=False)
        except (OSError, EOFError, ValueError, zlib.error):
            continue
        frames.append(rows[rows.result.isin(["yes", "no"])])
    r = pd.concat(frames, ignore_index=True)
    r = r[(r.yes_bid > 0) & (r.yes_ask < 1) & (r.yes_ask > r.yes_bid)].copy()
    r["fill"] = (
        np.floor(pd.to_numeric(r.traded, errors="coerce").fillna(0)) >= 1
    ).astype(float)
    fee = np.where(
        r.series.isin(MAKER_FEE_SERIES), 0.0175 * r.price * (1 - r.price), 0.0
    )
    r["pnl"] = r.won.astype(float) - r.price - fee
    r["day"] = pd.to_datetime(r.date, errors="coerce")
    r = r[r.day.notna()]
    r["half"] = np.where(r.day < r.day.median(), "earlier", "later")
    r["category"] = r.series.map(category)
    r["spread"] = (r.yes_ask - r.yes_bid).round(2)
    r["mid"] = (r.yes_ask + r.yes_bid) / 2
    # Trading in the previous hour of the same market (hourly candle volume).
    r = r.sort_values(["ticker", "side", "end_ts"])
    r["prev_volume"] = r.groupby(["ticker", "side"]).volume.shift(1)
    return r.reset_index(drop=True)


def two_sided(r, wide_only=False):
    """Both sides posted in the same hour: one row per (market, hour)."""
    y = r[r.side.eq("yes")].set_index(["ticker", "end_ts"])
    n = r[r.side.eq("no")].set_index(["ticker", "end_ts"])
    j = y.join(n[["fill", "pnl"]], rsuffix="_no", how="inner")
    if wide_only:
        j = j[j.spread >= 0.05 - 1e-9]
    for col in ("fill", "pnl", "fill_no", "pnl_no", "spread"):
        j[col] = pd.to_numeric(j[col], errors="coerce").astype(float)
    j["contracts"] = j.fill + j.fill_no
    j["pnl_row"] = j.fill * j.pnl + j.fill_no * j.pnl_no
    return j.reset_index()


FAMILIES = {
    "1 NO on every market": lambda r: r[r.side.eq("no")],
    "2 YES on every market": lambda r: r[r.side.eq("yes")],
    "3 both sides (market making)": None,
    "4 favourite side (80c+)": lambda r: r[r.price >= 0.80 - 1e-9],
    "5 long-shot side (20c or less)": lambda r: r[r.price <= 0.20 + 1e-9],
    "6 NO where YES is 35-50c": lambda r: r[
        r.side.eq("no") & r.mid.between(0.35, 0.50)
    ],
    "7 both sides, spread 5c+": None,
    "8 NO after an hour with no trading": lambda r: r[
        r.side.eq("no") & r.prev_volume.eq(0)
    ],
    "9 NO after an hour with trading": lambda r: r[
        r.side.eq("no") & (r.prev_volume > 0)
    ],
}


def stats(rows, pnl="pnl", weight="fill"):
    w = rows[weight].to_numpy(float)
    p = rows[pnl].to_numpy(float)
    filled = w > 0
    if filled.sum() < 2:
        return {"fills": float(w.sum())}
    # Per-contract result, weighted by contracts filled (two-sided rows hold 0-2).
    dollars = p[filled] if weight == "contracts" else p[filled] * w[filled]
    per = dollars / w[filled]
    mean, t = clustered_mean_t(per, w[filled], rows.event_ticker.to_numpy()[filled])
    wins, losses = dollars[dollars > 0].sum(), -dollars[dollars < 0].sum()
    return {
        "fills": float(w.sum()),
        "events": int(pd.unique(rows.event_ticker.to_numpy()[filled]).size),
        "cents": 100 * float(mean),
        "t": float(t),
        "profit_factor": float(wins / losses) if losses > 0 else np.nan,
        "total_usd": float(dollars.sum()),
    }


def family_rows(r, name):
    if name.startswith("3 "):
        j = two_sided(r)
    elif name.startswith("7 "):
        j = two_sided(r, wide_only=True)
    else:
        return FAMILIES[name](r), "pnl", "fill"
    return j, "pnl_row", "contracts"


def holdout(rows, pnl, weight):
    """Series ranked on the earlier half; the top 10 pooled on the later half."""
    early = rows[rows.half.eq("earlier")]
    ranked = []
    for s, g in early.groupby("series"):
        st = stats(g, pnl, weight)
        if st.get("fills", 0) >= 30 and st.get("events", 0) >= 10:
            ranked.append((st["cents"], s))
    top = [s for _, s in sorted(ranked, reverse=True)[:TOP]]
    late = rows[rows.half.eq("later") & rows.series.isin(top)]
    return {"top_series": top, "later_pooled": stats(late, pnl, weight)}


def sweep(r):
    out = {}
    for name in FAMILIES:
        rows, pnl, weight = family_rows(r, name)
        fam = {
            "all": stats(rows, pnl, weight),
            "earlier": stats(rows[rows.half.eq("earlier")], pnl, weight),
            "later": stats(rows[rows.half.eq("later")], pnl, weight),
            "categories": {},
            "holdout": holdout(rows, pnl, weight),
        }
        for c, g in rows.groupby("category"):
            fam["categories"][c] = {
                "all": stats(g, pnl, weight),
                "earlier": stats(g[g.half.eq("earlier")], pnl, weight),
                "later": stats(g[g.half.eq("later")], pnl, weight),
            }
        late, early = fam["later"], fam["earlier"]
        fam["promising"] = bool(
            late.get("fills", 0) >= MIN_FILLS
            and late.get("t", 0) >= 2
            and late.get("cents", -1) > 0
            and early.get("cents", -1) > 0
        )
        hl = fam["holdout"]["later_pooled"]
        fam["holdout_promising"] = bool(
            hl.get("fills", 0) >= MIN_FILLS
            and hl.get("t", 0) >= 2
            and hl.get("cents", -1) > 0
        )
        out[name] = fam
    return out


def _c(s, key="cents", t="t"):
    if key not in s:
        return "n/a"
    return f"{s[key]:+.2f} ({s[t]:.2f})"


def report(res, markets):
    lines = [
        "# Strategy sweep across all scanned markets (exploratory, simulated)",
        "",
        f"{markets:,} markets. Resting orders one cent inside the spread, one contract each,",
        "filled as if first in line, held to settlement; Kalshi's maker fee only on the",
        "series that pay one. Profit factor = winning dollars / losing dollars.",
        "",
        "| Family | Fills | ¢/contract (t) | Profit factor | Total $ | Earlier ¢ (t) | Later ¢ (t) | Top-10 on later half ¢ (t), fills | Promising |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name, f in res.items():
        a, h = f["all"], f["holdout"]["later_pooled"]
        lines.append(
            f"| {name} | {a['fills']:,.0f} | {_c(a)} | {a['profit_factor']:.3f} | "
            f"{a['total_usd']:+,.0f} | {_c(f['earlier'])} | {_c(f['later'])} | "
            f"{_c(h)}, {h.get('fills', 0):,.0f} | "
            f"{'yes' if f['promising'] or f['holdout_promising'] else 'no'} |"
        )
    lines += ["", "## By category (later half shows whether it held)", ""]
    for name, f in res.items():
        lines += [
            f"**{name}**",
            "",
            "| Category | Fills | ¢/contract (t) | Profit factor | Total $ | Earlier ¢ (t) | Later ¢ (t) |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for c, s in sorted(f["categories"].items()):
            a = s["all"]
            if "cents" not in a:
                continue
            lines.append(
                f"| {c} | {a['fills']:,.0f} | {_c(a)} | {a['profit_factor']:.3f} | "
                f"{a['total_usd']:+,.0f} | {_c(s['earlier'])} | {_c(s['later'])} |"
            )
        lines += [
            "",
            f"Top 10 series on the earlier half: {', '.join(f['holdout']['top_series'])}",
            "",
        ]
    return "\n".join(lines)


def main():
    r = load()
    res = sweep(r)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "strategy_sweep.json").write_text(
        json.dumps(res, indent=1, default=float) + "\n"
    )
    text = report(res, r.ticker.nunique())
    (OUT / "strategy_sweep.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
