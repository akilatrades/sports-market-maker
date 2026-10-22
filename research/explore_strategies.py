"""A different strategy across all scanned Kalshi markets (exploratory).

Plan: RESEARCH_LOG.md, "2026-10-22: A different strategy across all scanned
Kalshi markets (exploratory plan)". Taker strategies on the cross-market
scan's hourly quotes (7 to 4 hours before expected expiration), no model:

- S1 favourite-longshot: at the first quote, buy the side whose ask is at
  least X (80, 90, 95¢);
- S2 momentum / reversal: where the mid moved 5¢ or more between the first
  and last quote, buy the side it moved toward (or away from) at the last
  quote's ask;
- calibration: realised YES rate minus the mid, by price band and category.

Simulated from public quotes and results; one contract at the quoted ask.

    python -m research.explore_strategies   # writes outputs/research/explore_strategies.{json,md}
"""

import json
import re
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.stats import clustered_mean_t

SCAN = Path("outputs/scan")
OUT = Path("outputs/research")
FAVOURITE = (0.80, 0.90, 0.95)
MOVE = 0.05
MIN_TRADES = 1000
TIGHT = 0.03  # extra variants (added after the first run): spread at most 3¢
FAV_MID = (0.80, 0.90)
COLUMNS = [
    "ticker",
    "end_ts",
    "yes_bid",
    "yes_ask",
    "side",
    "result",
    "event_ticker",
    "date",
    "series",
]
CATEGORIES = [
    ("mentions", r"MENTION|SAY|ANNOUNCER"),
    (
        "weather",
        r"TEMP|RAIN|SNOW|HIGH[A-Z]{2,4}$|LOW[A-Z]{2,4}$|HURRICANE|TORNADO|WEATHER",
    ),
    ("crypto", r"BTC|ETH|SOL|XRP|DOGE|CRYPTO|COIN"),
    (
        "sports",
        r"NBA|NFL|NHL|MLB|NCAA|WNBA|MLS|EPL|UCL|UEL|LALIGA|SERIEA|BUNDES|LIGUE|ATP|WTA|ITF|"
        r"UFC|PGA|LPGA|NASCAR|F1|SOCCER|FIFA|CLUBF|TENNIS|GOLF|BOXING|CRICKET|IPL|KBO|NPB|"
        r"AHL|KHL|VTB|ABA|ACB|BBL|NBL|EUROLEAGUE|CHAMP|CUP|LEAGUE|GAME$|SPREAD$|TOTAL$|BTTS$",
    ),
    (
        "economics",
        r"CPI|FED|RATE|GDP|JOBLESS|PAYROLL|UNEMP|AAAGAS|NATGAS|OIL|WTI|DIESEL|GOLD|SILVER|COPPER|"
        r"NATGAS|PLATINUM|PALLADIUM|INX|NASDAQ|SPX|TREAS|MORTGAGE|PCE|PPI|HOUSING|TEU|EMP$",
    ),
    (
        "politics",
        r"TRUMP|ELECT|VOTE|SENATE|HOUSE|GOV|PRES|CONGRESS|BILL|APPROVE|MIDTERM|STATELEG|"
        r"SCOTUS|CABINET|PARLIAMENT|MAYOR|POLL",
    ),
    (
        "entertainment",
        r"^KXRT$|YTVIEWS|BOXOFFICE|SPOTIFY|BILLBOARD|GRAMMY|OSCAR|EMMY|NETFLIX|SONG|ALBUM|"
        r"TOPMODEL|LLM|APPRANK|HEADLINE|FEATURE|BWAY",
    ),
]


def category(series):
    """Coarse category from the series name (sports is checked before
    economics, so that e.g. LALIGASPREAD is not read as a fuel market)."""
    s = str(series).upper()
    for name, pattern in CATEGORIES:
        if re.search(pattern, s):
            return name
    return "other"


def taker_fee(price, rounded=False):
    """Kalshi's taker fee per contract; rounded = one-contract order, up to the cent."""
    fee = 0.07 * np.asarray(price, float) * (1 - np.asarray(price, float))
    return np.ceil(np.round(fee * 100, 6)) / 100 if rounded else fee


def load_markets(folder=SCAN):
    """One row per market: quotes at its first and last hourly look, and the result."""
    frames = []
    for path in sorted(Path(folder).glob("orders_*.csv.gz")):
        try:
            rows = pd.read_csv(path, usecols=COLUMNS, low_memory=False)
        except (OSError, EOFError, ValueError, zlib.error):
            continue
        rows = rows[rows.side.eq("no") & rows.result.isin(["yes", "no"])]
        frames.append(rows.drop(columns="side"))
    q = pd.concat(frames, ignore_index=True)
    q = q[(q.yes_bid > 0) & (q.yes_ask < 1) & (q.yes_ask > q.yes_bid)]
    q = q.sort_values(["ticker", "end_ts"])
    first = q.groupby("ticker").head(1).set_index("ticker")
    last = q.groupby("ticker").tail(1).set_index("ticker")
    m = first[["series", "event_ticker", "date", "result", "yes_bid", "yes_ask"]].join(
        last[["yes_bid", "yes_ask", "end_ts"]], rsuffix="_last"
    )
    m["yes"] = m.result.eq("yes").astype(float)
    m["mid"] = (m.yes_bid + m.yes_ask) / 2
    m["mid_last"] = (m.yes_bid_last + m.yes_ask_last) / 2
    m["day"] = pd.to_datetime(m.date, errors="coerce")
    m["category"] = m.series.map(category)
    m = m[m.day.notna()].reset_index()
    split = m.day.median()
    m["half"] = np.where(m.day < split, "earlier", "later")
    return m, split


def trades_s1(m, x):
    """Buy the favourite at the first quote's ask when that ask is at least x."""
    yes_ask, no_ask = m.yes_ask, 1 - m.yes_bid
    buy_yes = yes_ask >= x - 1e-9
    buy_no = (no_ask >= x - 1e-9) & ~buy_yes
    t = m[buy_yes | buy_no].copy()
    yes_side = buy_yes[buy_yes | buy_no].to_numpy()
    t["price"] = np.where(yes_side, t.yes_ask, 1 - t.yes_bid)
    t["won"] = np.where(yes_side, t.yes, 1 - t.yes)
    return t


def trades_s2(m, momentum):
    """Momentum or reversal on a 5¢+ move between the first and last quote."""
    move = m.mid_last - m.mid
    t = m[move.abs() >= MOVE - 1e-9].copy()
    up = (t.mid_last - t.mid) > 0
    buy_yes = up if momentum else ~up
    t["price"] = np.where(buy_yes, t.yes_ask_last, 1 - t.yes_bid_last)
    t["won"] = np.where(buy_yes, t.yes, 1 - t.yes)
    return t


def trades_s1_mid(m, x):
    """Extra variant: favourite by the mid (at least x), spread at most 3¢, buy at the ask."""
    tight = (m.yes_ask - m.yes_bid) <= TIGHT + 1e-9
    buy_yes = tight & (m.mid >= x - 1e-9)
    buy_no = tight & (m.mid <= 1 - x + 1e-9)
    t = m[buy_yes | buy_no].copy()
    yes_side = buy_yes[buy_yes | buy_no].to_numpy()
    t["price"] = np.where(yes_side, t.yes_ask, 1 - t.yes_bid)
    t["won"] = np.where(yes_side, t.yes, 1 - t.yes)
    return t


def trades_s2_tight(m, momentum):
    """Extra variant: S2 where the last quote's spread is at most 3¢."""
    tight = (m.yes_ask_last - m.yes_bid_last) <= TIGHT + 1e-9
    return trades_s2(m[tight], momentum)


def load_resting(folder=SCAN, split=None):
    """The scan's own resting orders (one per hourly look, 1¢ inside when the
    spread allows), on the favourite side only: YES when its price is 80¢+,
    NO when the NO price is 80¢+. One filled contract per market (first fill)."""
    cols = [
        "ticker",
        "end_ts",
        "side",
        "price",
        "traded",
        "won",
        "pnl",
        "event_ticker",
        "date",
        "series",
        "result",
    ]
    frames = []
    for path in sorted(Path(folder).glob("orders_*.csv.gz")):
        try:
            rows = pd.read_csv(path, usecols=cols, low_memory=False)
        except (OSError, EOFError, ValueError, zlib.error):
            continue
        rows = rows[
            rows.result.isin(["yes", "no"])
            & (rows.price >= 0.80)
            & (rows.price <= 0.98)
        ]
        frames.append(rows)
    r = pd.concat(frames, ignore_index=True)
    r = r[np.floor(r.traded) >= 1].sort_values(["ticker", "end_ts"])
    r = r.drop_duplicates("ticker", keep="first")
    r["day"] = pd.to_datetime(r.date, errors="coerce")
    r = r[r.day.notna()]
    r["half"] = np.where(r.day < split, "earlier", "later")
    r["category"] = r.series.map(category)
    return r


def score(t, fee_rounded=False):
    if len(t) < 2:
        return {"trades": len(t)}
    pnl = t.won - t.price - taker_fee(t.price, fee_rounded)
    mean, tt = clustered_mean_t(pnl, t.event_ticker)
    profit = pnl.groupby(t.series.to_numpy()).sum()
    top_share = (
        float(profit.max() / profit[profit > 0].sum()) if (profit > 0).any() else np.nan
    )
    return {
        "trades": len(t),
        "events": int(t.event_ticker.nunique()),
        "series": int(t.series.nunique()),
        "cents": 100 * float(mean),
        "t": float(tt),
        "win_rate": float(t.won.mean()),
        "avg_price": float(t.price.mean()),
        "top_series_share_of_profit": top_share,
        "top_series": str(profit.idxmax()) if len(profit) else None,
    }


def evaluate(t):
    out = {}
    for fee_rounded in (False, True):
        key = "fee_one_contract" if fee_rounded else "fee_large_order"
        out[key] = {
            "all": score(t, fee_rounded),
            "earlier": score(t[t.half.eq("earlier")], fee_rounded),
            "later": score(t[t.half.eq("later")], fee_rounded),
        }
    pnl = t.won - t.price
    mean, tt = clustered_mean_t(pnl, t.event_ticker) if len(t) > 1 else (np.nan, np.nan)
    out["no_fee"] = {"cents": 100 * float(mean), "t": float(tt)}
    late = out["fee_large_order"]["later"]
    early = out["fee_large_order"]["earlier"]
    out["promising"] = bool(
        late.get("trades", 0) + early.get("trades", 0) >= MIN_TRADES
        and early.get("cents", -1) > 0
        and late.get("cents", -1) > 0
        and late.get("t", 0) >= 2
        and out["fee_large_order"]["all"].get("top_series_share_of_profit", 1) <= 0.25
    )
    # Categories: ranked on the earlier half, best reported on the later half.
    cats = {}
    for c, g in t.groupby("category"):
        cats[c] = {
            "earlier": score(g[g.half.eq("earlier")]),
            "later": score(g[g.half.eq("later")]),
        }
    ranked = sorted(
        (c for c in cats if cats[c]["earlier"].get("trades", 0) >= 100),
        key=lambda c: -cats[c]["earlier"].get("cents", -1e9),
    )
    out["categories"] = cats
    out["best_category_on_earlier_half"] = ranked[0] if ranked else None
    return out


def calibration(m):
    bands = [0, 0.05, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 0.95, 1.0]
    m = m.assign(band=pd.cut(m.mid, bands, include_lowest=True))
    rows = []
    for band, g in m.groupby("band", observed=True):
        gap, t = clustered_mean_t(g.yes - g.mid, g.event_ticker)
        rows.append(
            {
                "band": str(band),
                "markets": len(g),
                "mid": float(g.mid.mean()),
                "yes_rate": float(g.yes.mean()),
                "gap_cents": 100 * float(gap),
                "t": float(t),
            }
        )
    by_cat = {}
    for c, g in m.groupby("category"):
        fav = g[(g.mid >= 0.8) | (g.mid <= 0.2)]
        # Gap on the favourite side: realised minus price for the side above 80¢.
        side = np.where(
            fav.mid >= 0.8, fav.yes - fav.mid, (1 - fav.yes) - (1 - fav.mid)
        )
        gap, t = (
            clustered_mean_t(side, fav.event_ticker)
            if len(fav) > 1
            else (np.nan, np.nan)
        )
        by_cat[c] = {
            "markets": len(g),
            "favourite_markets": len(fav),
            "favourite_gap_cents": 100 * float(gap),
            "t": float(t),
        }
    return {"by_price": rows, "favourite_side_by_category": by_cat}


def run():
    m, split = load_markets()
    results = {
        "markets": len(m),
        "series": int(m.series.nunique()),
        "events": int(m.event_ticker.nunique()),
        "split_date": str(split.date()),
        "categories": m.category.value_counts().to_dict(),
        "calibration": calibration(m),
        "rules": {},
    }
    for x in FAVOURITE:
        results["rules"][f"S1 favourite at {100 * x:.0f}c+"] = evaluate(trades_s1(m, x))
    results["rules"]["S2 momentum"] = evaluate(trades_s2(m, True))
    results["rules"]["S2 reversal"] = evaluate(trades_s2(m, False))
    # Extra variants, added after the first run showed S1 and S2 buying wide spreads.
    for x in FAV_MID:
        results["rules"][f"S1b favourite mid {100 * x:.0f}c+, spread <= 3c"] = evaluate(
            trades_s1_mid(m, x)
        )
    results["rules"]["S2b momentum, spread <= 3c"] = evaluate(trades_s2_tight(m, True))
    results["rules"]["S2b reversal, spread <= 3c"] = evaluate(trades_s2_tight(m, False))
    results["resting_favourite"] = resting_summary(load_resting(split=split))
    return results


def resting_summary(r):
    """Maker on the favourite side, scan's maker fee (a quarter of the taker fee)."""
    out = {}
    for name, g in [("all", r)] + list(r.groupby("category")):
        row = {}
        for half in ("earlier", "later"):
            h = g[g.half.eq(half)]
            if len(h) > 1:
                mean, t = clustered_mean_t(h.pnl, h.event_ticker)
                row[half] = {"fills": len(h), "cents": 100 * float(mean), "t": float(t)}
        if len(g) > 1:
            mean, t = clustered_mean_t(g.pnl, g.event_ticker)
            row["all"] = {
                "fills": len(g),
                "cents": 100 * float(mean),
                "t": float(t),
                "avg_price": float(g.price.mean()),
            }
        out[name] = row
    return out


def report(r):
    lines = [
        "# A different strategy across all scanned Kalshi markets (exploratory, simulated)",
        "",
        f"{r['markets']:,} markets, {r['series']:,} series, {r['events']:,} events; halves split "
        f"at {r['split_date']}. Taker at the quoted ask, one contract, held to settlement.",
        "",
        "## Calibration: realised YES rate minus the mid at the first quote",
        "",
        "| Mid band | Markets | Mid | YES rate | Gap (¢) | t |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in r["calibration"]["by_price"]:
        lines.append(
            f"| {row['band']} | {row['markets']:,} | {row['mid']:.3f} | {row['yes_rate']:.3f} | "
            f"{row['gap_cents']:+.2f} | {row['t']:.2f} |"
        )
    lines += [
        "",
        "Favourite side (mid ≥ 80¢ or ≤ 20¢), realised minus price, by category:",
        "",
        "| Category | Markets | Favourite markets | Gap (¢) | t |",
        "|---|---:|---:|---:|---:|",
    ]
    for c, v in sorted(r["calibration"]["favourite_side_by_category"].items()):
        lines.append(
            f"| {c} | {v['markets']:,} | {v['favourite_markets']:,} | {v['favourite_gap_cents']:+.2f} | {v['t']:.2f} |"
        )
    lines += [
        "",
        "## Rules (taker fee unrounded = a large order; one-contract fee in brackets)",
        "",
        "| Rule | Trades | Win rate | Avg price | ¢/contract (t) | 1-contract fee ¢ | No fee ¢ | Earlier ¢ (t) | Later ¢ (t) | Top series share | Promising |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name, v in r["rules"].items():
        a, e, l1 = (
            v["fee_large_order"]["all"],
            v["fee_large_order"]["earlier"],
            v["fee_large_order"]["later"],
        )
        one = v["fee_one_contract"]["all"]
        lines.append(
            f"| {name} | {a['trades']:,} | {a['win_rate']:.3f} | {a['avg_price']:.3f} | "
            f"{a['cents']:+.2f} ({a['t']:.2f}) | {one['cents']:+.2f} | {v['no_fee']['cents']:+.2f} | "
            f"{e['cents']:+.2f} ({e['t']:.2f}) | {l1['cents']:+.2f} ({l1['t']:.2f}) | "
            f"{a['top_series_share_of_profit']:.0%} ({a['top_series']}) | {'yes' if v['promising'] else 'no'} |"
        )
    rest = r.get("resting_favourite", {})
    if rest:
        lines += [
            "",
            "## Extra: resting orders on the favourite side (maker, 80-98¢, scan's maker fee)",
            "",
            "| Category | Fills | Avg price | ¢/contract (t) | Earlier ¢ (t) | Later ¢ (t) |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for c, v in rest.items():
            a, e, l1 = v.get("all", {}), v.get("earlier", {}), v.get("later", {})
            if not a:
                continue
            lines.append(
                f"| {c} | {a['fills']:,} | {a['avg_price']:.3f} | {a['cents']:+.2f} ({a['t']:.2f}) | "
                f"{e.get('cents', float('nan')):+.2f} ({e.get('t', float('nan')):.2f}) | "
                f"{l1.get('cents', float('nan')):+.2f} ({l1.get('t', float('nan')):.2f}) |"
            )
    lines += ["", "## By category (large-order fee; earlier half → later half)", ""]
    for name, v in r["rules"].items():
        lines += [
            f"**{name}** (best on the earlier half: {v['best_category_on_earlier_half']})",
            "",
            "| Category | Earlier trades | Earlier ¢ (t) | Later trades | Later ¢ (t) |",
            "|---|---:|---:|---:|---:|",
        ]
        for c, s in sorted(v["categories"].items()):
            e, l1 = s["earlier"], s["later"]
            lines.append(
                f"| {c} | {e.get('trades', 0):,} | {e.get('cents', float('nan')):+.2f} ({e.get('t', float('nan')):.2f}) | "
                f"{l1.get('trades', 0):,} | {l1.get('cents', float('nan')):+.2f} ({l1.get('t', float('nan')):.2f}) |"
            )
        lines.append("")
    return "\n".join(lines)


def main():
    r = run()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "explore_strategies.json").write_text(
        json.dumps(r, indent=1, default=float) + "\n"
    )
    text = report(r)
    (OUT / "explore_strategies.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
