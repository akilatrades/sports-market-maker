"""Where is the NO edge thicker? Part D: other markets (exploratory, simulated).

Plan: RESEARCH_LOG.md, "2026-10-22: Where is the NO edge thicker? (exploratory
plan)", part D: 12 variants (the two combo series and a top-10 holdout).
Everything here replays public trade prints already in the repository. It
reads files only; it calls no API and places no orders.

1. Scan re-score. The cross-market scan (``research/scan_markets.py``) left
   one row per hypothetical order in ``outputs/scan/orders_<series>.csv.gz``:
   a NO order one cent inside the ask (at the bid when the spread is 1¢),
   posted at each hourly candle 7 to 4 hours before the market's expected
   expiration, resting one hour, one contract, filled if at least one
   contract traded through its price (as if first in line), settled with the
   scan's maker fee (a quarter of 0.07 x P x (1 - P), not rounded). Per
   series: cents per filled contract with event-clustered t, a one-sided p
   value (t distribution, events - 1 degrees of freedom) and the
   Benjamini-Hochberg false discovery rate at 10%. Then a time holdout:
   each series' markets are split at its median expiry date, series are
   ranked on the earlier half (at least 30 fills in at least 10 events),
   and the top 10 are scored on the later half.
2. Combo markets. The same scan rows for NBA double-double (KXNBA2D) and
   triple-double (KXNBA3D), the only resting-order replay with trade-print
   fills for them (``data/kalshi_history`` has their candles but no trade
   prints). Orders, fill rate, cents per filled contract with game-clustered
   t, cents per 100 orders, halves before and from 2026-02-09, at flow share
   1.0 and 0.25 (expected fill 1 - 0.75^n for n contracts traded through),
   with three fee assumptions.

    python -m research.explore_markets   # writes outputs/research/explore_markets.{json,md}
"""

import json
import zlib
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from kalshi.stats import clustered_mean_t
from research.fill_sizing_replay import clustered_mean_t as weighted_mean_t

SCAN = Path("outputs/scan")
OUT = Path("outputs/research")
FEES_SEEN = Path("outputs/launch_audit_20261018/production_liquidity.json")
COLUMNS = [
    "series",
    "ticker",
    "event_ticker",
    "end_ts",
    "date",
    "side",
    "price",
    "traded",
    "won",
    "pnl",
]
COMBOS = ("KXNBA2D", "KXNBA3D")
SPLIT = pd.Timestamp("2026-02-09")
MIN_FILLS = 30  # filled contracts, in the sample or half being ranked or tested
MIN_EVENTS = 10  # clusters; fewer make a clustered t unreliable
TOP = 10
FDR = 0.10
FLOW = 0.25
SCAN_FEE_SHARE = 0.25
BAND = (0.05, 0.95)  # the v5 NO price band, an extra variant for the combos
# Series the earlier scan write-ups singled out (RESEARCH_LOG.md, 2026-10-16/17).
NAMED = (
    "KXCLUBFBTTS",
    "KXWNBA1HTOTAL",
    "KXNBA3D",
    "KXNCAAMB1HSPREAD",
    "KXUCLCORNERS",
    "KXUFCMOF",
    "KXNBAFTM",
    "KXNCAAMENTION",
    "KXWNBA1QSPREAD",
    "KXNASCARTOP10",
    "KXITFMATCH",
    "KXNASCARRACE",
    "KXNFLANYTD",
    "KXLIGAMXSPREAD",
    "KXLALIGASPREAD",
    "KXWCSOT",
)


# --- Loading -------------------------------------------------------------------


def prepare(o, flow=FLOW):
    """Fill flags: first in line (fill_1) and the expected fill at ``flow``."""
    o = o.copy()
    n = np.floor(pd.to_numeric(o.traded, errors="coerce").fillna(0.0).to_numpy())
    o["fill_1"] = (n >= 1).astype(float)
    o["fill_q"] = 1 - (1 - flow) ** n
    o["day"] = pd.to_datetime(o.date, errors="coerce")
    return o[o.day.notna()].reset_index(drop=True)


def load_scan(folder=SCAN):
    """NO-side order rows of every scanned series, and the files that would not read."""
    frames, unreadable = [], []
    for path in sorted(Path(folder).glob("orders_*.csv.gz")):
        try:
            rows = pd.read_csv(path, usecols=COLUMNS, low_memory=False)
        except (OSError, EOFError, ValueError, zlib.error):
            unreadable.append(path.name)
            continue
        frames.append(rows[rows.side == "no"])
    return prepare(pd.concat(frames, ignore_index=True)), unreadable


# --- Statistics ----------------------------------------------------------------


def score(rows, pnl="pnl", weight="fill_1"):
    """Cents per filled contract with event-clustered t, plus counts.

    ``weight`` is ``fill_1`` (first in line: an order fills if any contract
    traded through) or ``fill_q`` (expected fill at the flow share). With
    ``fill_1`` the t is ``kalshi.stats.clustered_mean_t`` on the filled rows.
    """
    w = rows[weight].to_numpy(float)
    filled = rows[w > 0]
    with np.errstate(divide="ignore", invalid="ignore"):  # one event: no t
        if weight == "fill_1":
            mean, t = clustered_mean_t(filled[pnl], filled.event_ticker)
        else:
            mean, t = weighted_mean_t(filled[pnl], w[w > 0], filled.event_ticker)
    per_order = float((w * rows[pnl].to_numpy(float)).mean()) if len(rows) else np.nan
    return {
        "orders": int(len(rows)),
        "fill_rate": float(w.mean()) if len(rows) else np.nan,
        "fills": float(w.sum()),
        "events": int(filled.event_ticker.nunique()),
        "cents": 100 * float(mean),
        "t": float(t),
        "cents_per_100_orders": 100 * 100 * per_order,
        "avg_no_price": float(filled.price.mean()) if len(filled) else np.nan,
        "losing_fills": int((filled.won < 0.5).sum()),
    }


def later_half(o):
    """True where a market expires on or after its series' median expiry date.

    The median is over markets (one date per market, not per hourly order),
    so markets with more orders do not move the split.
    """
    markets = o.drop_duplicates("ticker")
    days = markets.day.to_numpy().astype("datetime64[D]").astype("int64")
    median = pd.Series(days).groupby(markets.series.to_numpy()).median()
    row_days = o.day.to_numpy().astype("datetime64[D]").astype("int64")
    return row_days >= o.series.map(median).to_numpy()


def one_sided_p(t, events):
    """P(T >= t) for a t distribution with events - 1 degrees of freedom."""
    t, df = np.asarray(t, float), np.asarray(events, float) - 1
    return stats.t.sf(t, np.maximum(df, 1))


def bh_qvalues(p):
    """Benjamini-Hochberg adjusted p values; reject where q <= the FDR level."""
    p = np.asarray(p, float)
    m = len(p)
    if m == 0:
        return p
    order = np.argsort(p, kind="stable")
    ranked = p[order] * m / np.arange(1, m + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.minimum(q, 1.0)
    return out


# --- Part 1: scan re-score and time holdout -----------------------------------


def series_table(o):
    """One row per series: full sample, earlier half, later half."""
    o = o.assign(later=later_half(o))
    rows = []
    for series, g in o.groupby("series", sort=True):
        full, early = score(g), score(g[~g.later])
        late, late_q = score(g[g.later]), score(g[g.later], weight="fill_q")
        markets = g.drop_duplicates("ticker")
        rows.append(
            {
                "series": series,
                "markets": int(len(markets)),
                "first_day": str(g.day.min().date()),
                "last_day": str(g.day.max().date()),
                "split_day": str(markets.day[markets.later].min().date())
                if markets.later.any()
                else None,
                **{f"full_{k}": v for k, v in full.items()},
                **{f"early_{k}": v for k, v in early.items()},
                **{f"late_{k}": v for k, v in late.items()},
                "late_cents_flow_025": late_q["cents"],
            }
        )
    table = pd.DataFrame(rows)
    table["eligible"] = (
        (table.full_fills >= MIN_FILLS)
        & (table.full_events >= MIN_EVENTS)
        & np.isfinite(table.full_t)
    )
    table["p_one_sided"] = np.nan
    table["q_bh"] = np.nan
    e = table.eligible
    table.loc[e, "p_one_sided"] = one_sided_p(table.full_t[e], table.full_events[e])
    table.loc[e, "q_bh"] = bh_qvalues(table.p_one_sided[e].to_numpy())
    return table


def holdout_pool(table):
    """Series with enough data in the earlier half to be ranked on it."""
    pool = table[
        (table.early_fills >= MIN_FILLS)
        & (table.early_events >= MIN_EVENTS)
        & np.isfinite(table.early_cents)
        & np.isfinite(table.early_t)
    ]
    return pool.reset_index(drop=True)


def pick_top(pool, by="early_cents", top=TOP):
    """The top series on the earlier half only (ties broken by name)."""
    return pool.sort_values([by, "series"], ascending=[False, True]).head(top)


def pooled_later(o, series):
    """All later-half fills of the given series together, event-clustered.

    Different series can share a game or a day, so the t clustered by expiry
    day is also given (a cruder, more cautious grouping).
    """
    o = o[o.series.isin(list(series))]
    late = o[later_half(o)]
    out = score(late)
    filled = late[late.fill_1 > 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        out["t_by_day"] = float(clustered_mean_t(filled.pnl, filled.day)[1])
    return out


def holdout(o, table, by="early_cents"):
    pool = holdout_pool(table)
    picked = pick_top(pool, by)
    late = picked.late_cents.to_numpy(float)
    return {
        "ranked_by": by,
        "pool_series": int(len(pool)),
        "top": [_row(r) for r in picked.to_dict("records")],
        "mean_earlier_cents": float(picked.early_cents.mean()),
        "mean_later_cents": float(np.nanmean(late)),
        "later_positive": int((late > 0).sum()),
        "later_t_at_least_2": int((picked.late_t >= 2).sum()),
        "pooled_later": pooled_later(o, picked.series),
        "baseline_all_pool_mean_later_cents": float(np.nanmean(pool.late_cents)),
        "baseline_all_pool_pooled_later": pooled_later(o, pool.series),
    }


def multiple_testing(table):
    e = table[table.eligible]
    tails = stats.t.sf(2.0, np.maximum(e.full_events - 1, 1))
    survivors = e[e.q_bh <= FDR].sort_values("q_bh")
    return {
        "series_with_any_order": int(len(table)),
        "eligible_series": int(len(e)),
        "t_at_least_2": int((e.full_t >= 2).sum()),
        "t_at_most_minus_2": int((e.full_t <= -2).sum()),
        "expected_t_at_least_2_normal": float(len(e) * stats.norm.sf(2.0)),
        "expected_t_at_least_2_t_dist": float(tails.sum()),
        "bh_fdr": FDR,
        "bh_survivors": [_row(r) for r in survivors.to_dict("records")],
    }


def named(table, pool):
    ranks = {s: i + 1 for i, s in enumerate(pick_top(pool, top=len(pool)).series)}
    out = []
    for r in table[table.series.isin(NAMED)].to_dict("records"):
        r = _row(r)
        r["earlier_rank"] = ranks.get(r["series"])
        out.append(r)
    return sorted(out, key=lambda r: NAMED.index(r["series"]))


# --- Part 2: combo markets -----------------------------------------------------


def combo_rows(o):
    """KXNBA2D and KXNBA3D rows with game day and three fee versions of P&L."""
    c = o[o.series.isin(COMBOS)].copy()
    code = c.event_ticker.str.split("-").str[1].str[:7]
    c["game_day"] = pd.to_datetime(code, format="%y%b%d", errors="coerce")
    c["pnl_no_fee"] = c.won - c.price
    c["pnl_one_cent"] = c.won - c.price - 0.01
    c["scan_fee"] = SCAN_FEE_SHARE * 0.07 * c.price * (1 - c.price)
    return c


def combo_block(c, pnl="pnl"):
    """Both flow shares, whole sample and both halves."""
    halves = {
        "all": c,
        "before_2026_02_09": c[c.game_day < SPLIT],
        "from_2026_02_09": c[c.game_day >= SPLIT],
    }
    return {
        f"flow_{name}": {h: score(rows, pnl, weight) for h, rows in halves.items()}
        for name, weight in [("1.0", "fill_1"), ("0.25", "fill_q")]
    }


def _count_markets(series, folder=Path("data/kalshi_history")):
    path = folder / f"markets_{series}.parquet"
    return len(pd.read_parquet(path, columns=["ticker"])) if path.exists() else None


def combos(o):
    c = combo_rows(o)
    out = {}
    for series in COMBOS:
        s = c[c.series == series]
        band = s[s.price.between(*BAND)]
        first = s.sort_values(["end_ts", "ticker"]).drop_duplicates("ticker")
        out[series] = {
            "markets": int(s.ticker.nunique()),
            "markets_listed_in_history": _count_markets(series),
            "games": int(s.event_ticker.nunique()),
            "first_game_day": str(s.game_day.min().date()),
            "last_game_day": str(s.game_day.max().date()),
            "hourly_orders_per_market": float(len(s) / max(s.ticker.nunique(), 1)),
            "share_of_fills_at_no_96c_plus": float(
                s.fill_1[s.price > BAND[1]].sum() / max(s.fill_1.sum(), 1)
            ),
            "mean_scan_fee_cents_on_fills": 100 * float(s.scan_fee[s.fill_1 > 0].mean()),
            "scan_fee": combo_block(s),
            "fee_sensitivity_flow_1": {
                "scan_fee": score(s)["cents"],
                "no_maker_fee": score(s, "pnl_no_fee")["cents"],
                "one_cent_per_contract": score(s, "pnl_one_cent")["cents"],
            },
            "extra_no_price_5_95": combo_block(band),
            "extra_first_look_per_market": combo_block(first),
        }
    return out


# --- Report --------------------------------------------------------------------


def _row(r):
    keep = {}
    for k, v in r.items():
        if isinstance(v, (np.floating, float)):
            keep[k] = None if not np.isfinite(v) else float(v)
        elif isinstance(v, (np.integer,)):
            keep[k] = int(v)
        elif isinstance(v, (np.bool_,)):
            keep[k] = bool(v)
        else:
            keep[k] = v
    return keep


def fee_types(path=FEES_SEEN):
    """Fee types recorded for some series on 2026-10-18 (current, not historical)."""
    if not Path(path).exists():
        return {}
    seen = json.loads(Path(path).read_text())
    return {
        s["series"]: f"{s['fee_type']} x{s['fee_multiplier']}"
        for s in seen.get("series", [])
        if "fee_type" in s
    }


def _f(v, fmt):
    return "n/a" if v is None or (isinstance(v, float) and not np.isfinite(v)) else fmt % v


def report(r):
    h, fees = r["holdout"], r["fee_types_seen"]
    lines = [
        "# Where is the NO edge thicker? D. Other markets",
        "",
        "*Exploratory, simulated, in-sample.* Replays of public Kalshi trade prints",
        "from the cross-market scan (each series' sample covers part of the 400",
        "days before 2026-10-16). One contract per hourly order, filled as if first",
        "in line (flow share 1.0) unless marked 0.25. Scan maker fee (a quarter of",
        "0.07 x P x (1 - P), not rounded) unless marked. t is clustered by event",
        "(the game for sports). Nothing here is live P&L or a forecast.",
        "",
        "## 1. Time holdout: top 10 on the earlier half, scored on the later half",
        "",
        f"Each series' markets split at its median expiry date. Ranked by earlier-half "
        f"cents per filled contract among the {h['pool_series']} series with at least "
        f"{MIN_FILLS} earlier-half fills in at least {MIN_EVENTS} events.",
        "",
        "| # | Series | Earlier fills | Earlier ¢ | Earlier t | Later fills (events) "
        "| Later ¢ | Later t | Later ¢ at 0.25 | Avg NO price | Fee type seen |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for i, x in enumerate(h["top"], 1):
        thin = " †" if x["late_fills"] < MIN_FILLS else ""
        lines.append(
            f"| {i} | {x['series']} | {x['early_fills']:,.0f} | {x['early_cents']:+.1f} "
            f"| {x['early_t']:.2f} | {x['late_fills']:,.0f} ({x['late_events']}){thin} "
            f"| {_f(x['late_cents'], '%+.1f')} | {_f(x['late_t'], '%.2f')} "
            f"| {_f(x['late_cents_flow_025'], '%+.1f')} "
            f"| {_f(x['full_avg_no_price'], '%.2f')} "
            f"| {fees.get(x['series'], 'not recorded')} |"
        )
    p, b = h["pooled_later"], h["baseline_all_pool_pooled_later"]
    lines += [
        "",
        f"† fewer than {MIN_FILLS} later-half fills. Fee type: as recorded on "
        "2026-10-18 for the few series checked then.",
        "",
        f"- Mean of the 10: earlier {h['mean_earlier_cents']:+.1f}¢, later "
        f"{h['mean_later_cents']:+.1f}¢; later half positive in {h['later_positive']} "
        f"of 10, t ≥ 2 in {h['later_t_at_least_2']}.",
        f"- The 10 pooled, later half: {p['fills']:,.0f} fills, {p['cents']:+.2f}¢, "
        f"t {p['t']:.2f} (by expiry day {p['t_by_day']:.2f}).",
        f"- Baseline, all {h['pool_series']} ranked series pooled, later half: "
        f"{b['fills']:,.0f} fills, {b['cents']:+.2f}¢, t {b['t']:.2f} (mean of series "
        f"{h['baseline_all_pool_mean_later_cents']:+.2f}¢).",
    ]
    x = r["extra_holdout_ranked_by_t"]
    xp = x["pooled_later"]
    lines += [
        f"- Extra variant, ranked by earlier-half t instead: later mean "
        f"{x['mean_later_cents']:+.1f}¢, positive in {x['later_positive']} of 10, pooled "
        f"{xp['fills']:,.0f} fills {xp['cents']:+.2f}¢ t {xp['t']:.2f} (by day "
        f"{xp['t_by_day']:.2f}); series: "
        + ", ".join(
            f"{s['series']} ({_f(s['late_cents'], '%+.1f')}¢)" for s in x["top"]
        )
        + ".",
        "",
    ]
    m = r["multiple_testing"]
    lines += [
        "## 2. Multiple testing on the full samples",
        "",
        f"{m['eligible_series']} of {m['series_with_any_order']} series have at least "
        f"{MIN_FILLS} fills in {MIN_EVENTS}+ events. t ≥ 2: **{m['t_at_least_2']}** "
        f"(expected with no edge anywhere: {m['expected_t_at_least_2_normal']:.0f} "
        f"normal, {m['expected_t_at_least_2_t_dist']:.0f} with events − 1 degrees of "
        f"freedom); t ≤ −2: {m['t_at_most_minus_2']}. Benjamini-Hochberg at "
        f"{m['bh_fdr']:.0%} on one-sided p values: **{len(m['bh_survivors'])} "
        "survive**.",
        "",
    ]
    if m["bh_survivors"]:
        lines += [
            "| Series | Fills | Events | Avg NO price | Losing fills | ¢ | t | q "
            "| Earlier ¢ | Later ¢ | Sample dates |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for s in m["bh_survivors"]:
            lines.append(
                f"| {s['series']} | {s['full_fills']:,.0f} | {s['full_events']} "
                f"| {s['full_avg_no_price']:.2f} | {s['full_losing_fills']} "
                f"| {s['full_cents']:+.1f} | {s['full_t']:.2f} | {s['q_bh']:.3f} "
                f"| {_f(s['early_cents'], '%+.1f')} | {_f(s['late_cents'], '%+.1f')} "
                f"| {s['first_day']} to {s['last_day']} |"
            )
        lines += [
            "",
            "A series with no losing fills has a t that measures only how alike its",
            "small wins are; one loss at a 95¢ NO price erases about 19 of them.",
            "",
        ]
    lines += [
        "## 3. The series singled out earlier (descriptive)",
        "",
        "Chosen on their full samples, so both halves here are in-sample.",
        "",
        "| Series | Fills | Events | ¢ | t | BH q | Earlier ¢ (rank) | Later ¢ | Later t "
        "| Later fills |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in r["named_series"]:
        rank = f" (#{s['earlier_rank']})" if s.get("earlier_rank") else ""
        lines.append(
            f"| {s['series']} | {s['full_fills']:,.0f} | {s['full_events']} "
            f"| {_f(s['full_cents'], '%+.1f')} "
            f"| {_f(s['full_t'], '%.2f')} | {_f(s['q_bh'], '%.2f')} "
            f"| {_f(s['early_cents'], '%+.1f')}{rank} | {_f(s['late_cents'], '%+.1f')} "
            f"| {_f(s['late_t'], '%.2f')} | {s['late_fills']:,.0f} |"
        )
    lines += [
        "",
        "## 4. NBA combo markets, resting NO (scan rows)",
        "",
        "Every hourly look in the scan's window (about 1 to 4.5 hours before tip),",
        "each order resting one hour. Halves by game date; cells are ¢ (t, fills).",
        "",
        "| Series | Flow | Orders | Fill rate | Fills | ¢/contract | t | ¢ per 100 orders "
        "| Before 2026-02-09 | From 2026-02-09 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for series, c in r["combos"].items():
        for flow in ("1.0", "0.25"):
            k = c["scan_fee"][f"flow_{flow}"]
            a, e, lt = k["all"], k["before_2026_02_09"], k["from_2026_02_09"]
            lines.append(
                f"| {series} | {flow} | {a['orders']:,} | {a['fill_rate']:.0%} "
                f"| {a['fills']:,.0f} | {a['cents']:+.2f} | {a['t']:.2f} "
                f"| {a['cents_per_100_orders']:+.0f} "
                f"| {e['cents']:+.2f} ({e['t']:.2f}, {e['fills']:,.0f}) "
                f"| {lt['cents']:+.2f} ({lt['t']:.2f}, {lt['fills']:,.0f}) |"
            )
    lines.append("")
    for series, c in r["combos"].items():
        f = c["fee_sensitivity_flow_1"]
        band = c["extra_no_price_5_95"]["flow_1.0"]["all"]
        first = c["extra_first_look_per_market"]["flow_1.0"]["all"]
        lines.append(
            f"- {series}: {c['markets']} markets (of {_f(c['markets_listed_in_history'], '%d')} "
            f"listed in data/kalshi_history) in {c['games']} games "
            f"({c['first_game_day']} to {c['last_game_day']}); "
            f"{c['share_of_fills_at_no_96c_plus']:.0%} of fills at NO 96¢+. Fees: no "
            f"maker fee {f['no_maker_fee']:+.2f}¢, scan fee {f['scan_fee']:+.2f}¢, 1¢ per "
            f"contract {f['one_cent_per_contract']:+.2f}¢. Extra variants: NO 5-95¢ "
            f"{band['cents']:+.2f}¢ (t {band['t']:.2f}, {band['fills']:,.0f} fills); first "
            f"look per market {first['cents']:+.2f}¢ (t {first['t']:.2f}, "
            f"{first['fills']:,.0f} fills)."
        )
    v = r["variants"]
    lines += [
        "",
        "## Variant count",
        "",
        f"Planned: {v['planned']} (2 combo series, 10 holdout series). Extra: "
        f"{v['extra_total']} ({v['extra_detail']}). Total: {v['total']}. Fee and flow "
        "share versions are sensitivities of the same orders, not new selections.",
        "",
        "## Data gaps and caveats",
        "",
        f"- Unreadable scan files (skipped): {', '.join(r['unreadable_files']) or 'none'}.",
        "- No trade prints for KXNBA2D/KXNBA3D in data/kalshi_history, so the combo",
        "  replay is the scan's sample (400 markets drawn, fewer with quotes) with",
        "  its hourly one-hour orders, not a v5-style order resting until tip, and",
        "  with no model filter.",
        "- Fills assume first in line at our price. Flow share 0.25 barely changes",
        "  the numbers because many contracts usually trade through within the hour;",
        "  queue position and whether the quote is there at all matter more.",
        "- Each series' sample is a few weeks to a year, and the two halves come from",
        "  the same stretch of time, so the holdout is not a different season.",
        "- Fee: the scan's unrounded quarter fee for every series. Series with",
        "  'quadratic' fees (NBA props among them) charge makers nothing; a series",
        "  that charges makers rounds a one-contract fee up to 1¢.",
        "- A clustered t from fewer than about 20 events, or from a series with few",
        "  or no losing fills (NO prices near 95¢), is not reliable.",
        "",
    ]
    return "\n".join(lines)


def run(o, unreadable):
    table = series_table(o)
    pool = holdout_pool(table)
    main_ = holdout(o, table, "early_cents")
    by_t = holdout(o, table, "early_t")
    new_by_t = len(
        {s["series"] for s in by_t["top"]} - {s["series"] for s in main_["top"]}
    )
    combo = combos(o)
    extra_combo = 2 * len(COMBOS)
    return {
        "labels": "exploratory, simulated, in-sample; fills as if first in line "
        "unless flow 0.25; scan maker fee unless marked",
        "thresholds": {
            "min_fills": MIN_FILLS,
            "min_events": MIN_EVENTS,
            "top": TOP,
            "fdr": FDR,
            "flow_share": FLOW,
            "combo_split": str(SPLIT.date()),
        },
        "unreadable_files": unreadable,
        "fee_types_seen": fee_types(),
        "holdout": main_,
        "extra_holdout_ranked_by_t": by_t,
        "multiple_testing": multiple_testing(table),
        "named_series": named(table, pool),
        "combos": combo,
        "variants": {
            "planned": 12,
            "extra_total": new_by_t + extra_combo,
            "extra_detail": f"{new_by_t} new series from ranking by t; "
            f"{extra_combo} combo variants (NO 5-95¢, first look per market)",
            "total": 12 + new_by_t + extra_combo,
        },
    }


def main():
    o, unreadable = load_scan()
    results = _clean(run(o, unreadable))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "explore_markets.json").write_text(
        json.dumps(results, indent=1, allow_nan=False) + "\n"
    )
    text = report(results)
    (OUT / "explore_markets.md").write_text(text)
    print(text)


def _clean(value):
    """Plain JSON values: numpy scalars unwrapped, NaN and infinity as null."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if value is None or isinstance(value, str):
        return value
    return str(value)


if __name__ == "__main__":
    main()
