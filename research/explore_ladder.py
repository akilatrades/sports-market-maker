"""Ladder prices from the sportsbooks for every Kalshi rung (exploratory, test C).

Plan: RESEARCH_LOG.md, "2026-10-22: Where is the NO edge thicker?", test C.
Kalshi lists a ladder of lines per player and stat (10+, 15+, 20+ points);
the live bot trusts the books only at a line at least two books quote, and
other rungs fall back to the stat model. Here a count distribution is fitted
to every sportsbook line for the player, stat and game, and used to price
every Kalshi rung. Exactly two variants: negative binomial (mean, size) and
normal (mean, sd, continuity at x.5).

Fitting (fixed before running, not varied):

- Book lines come from ``outputs/bookline/book_lines.csv.gz`` (de-vigged
  consensus, one snapshot per game). An order uses the latest snapshot at or
  before its posting time (``end_ts``), matched on game, player, stat and
  line as in ``research/bookline_backtest.py``; an order posted before every
  snapshot of its game gets no book price.
- Each line L (x.5) says P(X >= L + 0.5) = p_book. The fit minimises the
  cross-entropy between p_book and the fitted probability, weighted by
  ``book_n``, within bounds (NB mean 0.05-80, size 0.3-2000; normal mean
  -10-80, sd 0.2-40).
- Two or more lines: both parameters are free. One line: the shape is fixed
  at a per-stat median (NB size; normal sd / mean) from player-stat-games
  with three or more lines in games before 2026-02-09 only.

Scoring: log loss (probabilities clipped to 0.5-99.5%) and Brier score of
each source against outcomes, with game-clustered t for paired differences;
and a replay of one-contract NO orders with 0-15 cents of edge against each
source, NO price 5-95 cents, no caps, no maker fee. Fills are read from public
trade prints as if first in line (flow share 1.0: fills if at least one
contract traded through the price before tip) and at flow share 0.25 (the
expected fill 1 - 0.75 ** contracts through). Everything is simulated and
in-sample (2025-26, the season the live rules were chosen on), in the 151
games with sportsbook history.

    python -m research.explore_ladder   # writes outputs/research/explore_ladder.*
"""

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, stats

from kalshi.stats import clustered_mean_t as plain_mean_t
from research.fill_sizing_replay import clustered_mean_t, load_orders

BOOK = Path("outputs/bookline/book_lines.csv.gz")
OUT = Path("outputs/research")
SPLIT = dt.date(2026, 2, 9)  # halves of the season; shapes come from before it
MIN_LINES_FOR_SHAPE = 3
EDGE = (0.0, 0.15)
BAND = (0.05, 0.95)
SHARES = (1.0, 0.25)
CLIP = 0.005  # log loss clip, as in kalshi.stats.logit
FAMILIES = ("nb", "normal")  # the two pre-registered variants
MEAN_BOUNDS = {"nb": (0.05, 80.0), "normal": (-10.0, 80.0)}
SHAPE_BOUNDS = {"nb": (0.3, 2000.0), "normal": (0.2, 40.0)}  # size; sd
KEYS = ["game_id", "snap_ts", "player_key", "stat"]
SOURCES = {
    "ladder_nb": "Ladder, negative binomial",
    "ladder_normal": "Ladder, normal",
    "p_model": "Stat model",
    "mid": "Kalshi mid at posting",
    "live": "Live rule (2-book exact line, else model)",
}
REPLAY_SOURCES = ("ladder_nb", "ladder_normal", "p_model", "live")
STRATA = {
    "all": "All rungs with a ladder",
    "no_exact2": "No exact line with 2+ books",
    "exact2": "Exact line with 2+ books",
}


# ------------------------------------------------------------- distributions


def nb_over(line, mean, size):
    """P(X >= line + 0.5) for a negative binomial with this mean and size."""
    k = np.floor(np.asarray(line, dtype=float))  # 24.5 -> P(X > 24) = P(X >= 25)
    mean, size = np.asarray(mean, dtype=float), np.asarray(size, dtype=float)
    return stats.nbinom.sf(k, size, size / (size + mean))


def normal_over(line, mean, sd):
    """P(X >= line + 0.5) for a normal with continuity at x.5: P(Y > line)."""
    return stats.norm.sf((np.asarray(line, dtype=float) - mean) / sd)


def over_prob(family, line, mean, shape):
    """``shape`` is the NB size or the normal sd."""
    if family == "nb":
        return nb_over(line, mean, shape)
    return normal_over(line, mean, shape)


def _cross_entropy(q, p, w):
    """Weighted cross-entropy of fitted ``q`` against book ``p``; rows on the last axis."""
    q = np.clip(q, 1e-12, 1 - 1e-12)
    return -(w * (p * np.log(q) + (1 - p) * np.log1p(-q))).sum(axis=-1) / w.sum()


def fit_ladder(line, p_book, weight, family, fixed_shape=None):
    """Fit one player-stat-game ladder; returns mean, shape (size or sd), at_bound.

    ``fixed_shape`` (NB size, or normal sd / mean) fixes the shape and fits
    the mean only; without it both parameters are free.
    """
    line = np.asarray(line, dtype=float)
    p = np.clip(np.asarray(p_book, dtype=float), 1e-6, 1 - 1e-6)
    w = np.asarray(weight, dtype=float)
    m_lo, m_hi = MEAN_BOUNDS[family]
    if fixed_shape is not None:
        m_lo = max(m_lo, 0.05)  # sd = ratio x mean needs a positive mean

        def shape_of(m):
            m = np.asarray(m, dtype=float)
            s = np.full_like(m, fixed_shape) if family == "nb" else fixed_shape * m
            return np.clip(s, *SHAPE_BOUNDS[family])

        grid = np.linspace(m_lo, m_hi, 321)
        q = over_prob(family, line[None, :], grid[:, None], shape_of(grid)[:, None])
        i = int(np.argmin(_cross_entropy(q, p, w)))
        lo, hi = grid[max(i - 1, 0)], grid[min(i + 1, len(grid) - 1)]
        res = optimize.minimize_scalar(
            lambda m: _cross_entropy(over_prob(family, line, m, shape_of(m)), p, w),
            bounds=(lo, hi),
            method="bounded",
            options={"xatol": 1e-7},
        )
        mean = float(res.x)
        shape = float(shape_of(mean))
        at_bound = bool(np.isclose(mean, m_lo) or np.isclose(mean, m_hi))
        return {"mean": mean, "shape": shape, "at_bound": at_bound}
    s_lo, s_hi = np.log(SHAPE_BOUNDS[family])
    # Coarse grid start, then a bounded quasi-Newton polish of (mean, log shape).
    means = np.linspace(max(m_lo, line.min() - 15), min(m_hi, line.max() + 15), 61)
    logs = np.linspace(s_lo, s_hi, 13)
    mm, ll = np.meshgrid(means, logs, indexing="ij")
    q = over_prob(family, line[None, None, :], mm[..., None], np.exp(ll)[..., None])
    loss = _cross_entropy(q, p, w)
    i, j = np.unravel_index(int(np.argmin(loss)), loss.shape)

    def objective(x):
        return _cross_entropy(over_prob(family, line, x[0], np.exp(x[1])), p, w)

    res = optimize.minimize(
        objective,
        x0=[means[i], logs[j]],
        method="L-BFGS-B",
        bounds=[(m_lo, m_hi), (s_lo, s_hi)],
    )
    mean, log_shape = float(res.x[0]), float(res.x[1])
    at_bound = bool(
        np.isclose(mean, m_lo)
        or np.isclose(mean, m_hi)
        or abs(log_shape - s_lo) < 1e-3
        or abs(log_shape - s_hi) < 1e-3
    )
    return {"mean": mean, "shape": float(np.exp(log_shape)), "at_bound": at_bound}


# --------------------------------------------------------------------- data


def epoch_seconds(times):
    t = pd.to_datetime(pd.Series(times), utc=True)
    return ((t - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta("1s")).astype(
        "int64"
    )


def load_books(path=BOOK):
    """The derived consensus table (read directly: ``bookline_backtest.book_table``
    would rebuild and overwrite it when the raw cache is present)."""
    b = pd.read_csv(path)
    b["game_id"] = b.game_id.astype("int64")
    b["line"] = b.line.astype(float).round(1)
    b["p_book"] = b.p_book.astype(float)
    b["book_n"] = b.book_n.astype(int)
    b["snap_ts"] = epoch_seconds(b.snapshot_utc).to_numpy()
    b["snap_day"] = (
        pd.to_datetime(b.snapshot_utc, utc=True)
        .dt.tz_convert("America/New_York")
        .dt.date
    )
    return b


def _fit_groups(book, family, fixed=None):
    rows = []
    for key, g in book.groupby(KEYS, sort=False):
        f = fit_ladder(
            g.line.to_numpy(),
            g.p_book.to_numpy(),
            g.book_n.to_numpy(),
            family,
            None if fixed is None else fixed[key[3]],
        )
        rows.append(dict(zip(KEYS, key)) | f)
    return pd.DataFrame(rows, columns=KEYS + ["mean", "shape", "at_bound"])


def pooled_shapes(free, split=SPLIT):
    """Per-stat median shape from 3+ line ladders in games before ``split``.

    NB: the size. Normal: sd / mean (ladders with a positive mean only).
    """
    early = free[(free.n_lines >= MIN_LINES_FOR_SHAPE) & (free.snap_day < split)]
    out = {}
    for family in FAMILIES:
        mean, shape = early[f"{family}_mean"], early[f"{family}_shape"]
        if family == "nb":
            value = shape
        else:
            value = (shape / mean)[mean > 0]
        by_stat = value.groupby(early.stat[value.index]).agg(["median", "size"])
        out[family] = {
            stat: {"shape": float(r["median"]), "ladders": int(r["size"])}
            for stat, r in by_stat.iterrows()
        }
    return out


def fit_all(book, split=SPLIT):
    """One row per (game, snapshot, player, stat): both fits and the pooled shapes."""
    info = book.groupby(KEYS, sort=False).agg(
        n_lines=("line", "size"), snap_day=("snap_day", "first")
    )
    info = info.reset_index()
    multi_keys = info[info.n_lines >= 2][KEYS]
    multi = book.merge(multi_keys, on=KEYS)
    single = book.merge(info[info.n_lines == 1][KEYS], on=KEYS)
    free = info[info.n_lines >= 2].copy()
    for family in FAMILIES:
        f = _fit_groups(multi, family).rename(
            columns={
                "mean": f"{family}_mean",
                "shape": f"{family}_shape",
                "at_bound": f"{family}_at_bound",
            }
        )
        free = free.merge(f, on=KEYS, how="left")
    shapes = pooled_shapes(free, split)
    fits = free
    if len(single):
        one = info[info.n_lines == 1].copy()
        for family in FAMILIES:
            fixed = {s: v["shape"] for s, v in shapes[family].items()}
            missing = set(one.stat) - set(fixed)
            if missing:
                raise ValueError(f"no 3+ line ladders before {split} for {missing}")
            f = _fit_groups(single, family, fixed=fixed).rename(
                columns={
                    "mean": f"{family}_mean",
                    "shape": f"{family}_shape",
                    "at_bound": f"{family}_at_bound",
                }
            )
            one = one.merge(f, on=KEYS, how="left")
        fits = pd.concat([free, one], ignore_index=True)
    return fits, shapes


def fit_error(book, fits):
    """Absolute error of each fitted ladder at the book's own lines."""
    m = book.merge(fits, on=KEYS)
    out = {}
    for family in FAMILIES:
        q = over_prob(family, m.line, m[f"{family}_mean"], m[f"{family}_shape"])
        err = np.abs(q - m.p_book)
        parts = {
            "all lines": np.ones(len(m), dtype=bool),
            "ladders with 3+ lines": m.n_lines.ge(3).to_numpy(),
            "ladders with 2 lines": m.n_lines.eq(2).to_numpy(),
            "single-line ladders": m.n_lines.eq(1).to_numpy(),
            "lines with 2+ books": m.book_n.ge(2).to_numpy(),
        }
        out[family] = {
            name: {
                "lines": int(mask.sum()),
                "median_abs_error": round(float(np.median(err[mask])), 4),
                "p90_abs_error": round(float(np.quantile(err[mask], 0.9)), 4),
            }
            for name, mask in parts.items()
            if mask.any()
        }
        out[family]["ladders at a bound"] = int(fits[f"{family}_at_bound"].sum())
    return out


def match_snapshot(orders, book):
    """Each order's latest snapshot at or before its posting time, per game."""
    snaps = book[["game_id", "snap_ts"]].drop_duplicates().sort_values("snap_ts")
    o = orders.copy()
    o["game_id"] = o.game_id.astype("int64")
    o["_post"] = o.end_ts.astype("int64")
    o = o.sort_values("_post")
    o = pd.merge_asof(
        o,
        snaps,
        left_on="_post",
        right_on="snap_ts",
        by="game_id",
        direction="backward",
    )
    return o.drop(columns="_post")


def price_rungs(orders, book, fits):
    """Every Kalshi rung in the book games that has a ladder fitted before posting."""
    o = orders[orders.game_id.astype("int64").isin(set(book.game_id))].copy()
    o["line"] = o.line.astype(float).round(1)
    o = match_snapshot(o, book)
    counts = {
        "rungs_in_book_games": int(len(o)),
        "posted_before_snapshot": int(o.snap_ts.isna().sum()),
    }
    o = o[o.snap_ts.notna()].copy()
    o["snap_ts"] = o.snap_ts.astype("int64")
    exact = book[KEYS + ["line", "p_book", "book_n"]]
    o = o.merge(exact, on=KEYS + ["line"], how="left")
    o["book_n"] = o.book_n.fillna(0).astype(int)
    o = o.merge(fits, on=KEYS, how="left")
    counts["no_book_line_for_player_stat"] = int(o.n_lines.isna().sum())
    o = o[o.n_lines.notna()].copy()
    for family in FAMILIES:
        o[f"ladder_{family}"] = over_prob(
            family, o.line, o[f"{family}_mean"], o[f"{family}_shape"]
        )
    o["mid"] = (o.yes_bid.astype(float) + o.yes_ask.astype(float)) / 2
    o["live"] = live_rule(o.p_book, o.book_n, o.p_model)
    o["exact2"] = o.book_n.ge(2)
    o["half"] = np.where(pd.Series(o.day).lt(SPLIT), "h1", "h2")
    counts["rungs_priced"] = int(len(o))
    counts["games"] = int(o.game_id.nunique())
    counts["exact2"] = int(o.exact2.sum())
    counts["exact1"] = int(o.book_n.eq(1).sum())
    counts["no_exact"] = int(o.book_n.eq(0).sum())
    return o.reset_index(drop=True), counts


def live_rule(p_book, book_n, p_model):
    """The live bot's fair value: the book at the exact line with 2+ books, else the model."""
    p_book = pd.Series(p_book, dtype=float)
    ok = pd.Series(book_n).ge(2).to_numpy() & p_book.between(0, 1).to_numpy()
    return np.where(ok, p_book.to_numpy(), np.asarray(p_model, dtype=float))


# ------------------------------------------------------------------ scoring


def log_loss(p, y):
    p = np.clip(np.asarray(p, dtype=float), CLIP, 1 - CLIP)
    y = np.asarray(y, dtype=float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _stratum(rungs, name):
    if name == "all":
        return rungs
    return rungs[rungs.exact2] if name == "exact2" else rungs[~rungs.exact2]


def calibration(rungs):
    """Log loss and Brier per source and stratum; paired log-loss differences."""
    out = {}
    for name in STRATA:
        r = _stratum(rungs, name)
        if r.empty:
            continue
        y = r.over.to_numpy()
        losses = {s: log_loss(r[s], y) for s in SOURCES}
        block = {
            "rungs": int(len(r)),
            "games": int(r.game_id.nunique()),
            "over_rate": round(float(y.mean()), 4),
            "sources": {
                s: {
                    "log_loss": round(float(losses[s].mean()), 4),
                    "brier": round(float(((r[s] - y) ** 2).mean()), 4),
                }
                for s in SOURCES
            },
            "paired_log_loss": [],
        }
        pairs = [
            (a, b)
            for a in ("ladder_nb", "ladder_normal")
            for b in ("p_model", "mid", "live")
        ]
        pairs.append(("ladder_nb", "ladder_normal"))
        for a, b in pairs:
            mean, t = plain_mean_t(losses[a] - losses[b], r.game_id)
            block["paired_log_loss"].append(
                {
                    "a": a,
                    "b": b,
                    "a_minus_b": round(float(mean), 4),
                    "t": round(float(t), 2) if np.isfinite(t) else None,
                }
            )
        out[name] = block
    return out


def fill_amount(through, share):
    """Contracts filled for a one-contract order (expected value below share 1)."""
    k = np.floor(np.asarray(through, dtype=float))
    if share >= 1:
        return (k >= 1).astype(float)
    return 1 - (1 - share) ** k


def eligible(rungs, source):
    edge = (1 - rungs[source].astype(float)) - rungs.price.astype(float)
    ok = edge.between(EDGE[0] - 1e-9, EDGE[1] + 1e-9)
    ok &= rungs.price.astype(float).between(BAND[0] - 1e-9, BAND[1] + 1e-9)
    return ok.to_numpy(), edge.to_numpy()


def replay_one(rungs, source, share):
    ok, edge = eligible(rungs, source)
    q = rungs[ok]
    fill = fill_amount(q.through, share)
    pnl = q.pnl_c.to_numpy(dtype=float)
    row = {"eligible": int(ok.sum()), "fills": round(float(fill.sum()), 1)}
    if fill.sum() >= 2:
        mean, t = clustered_mean_t(pnl, fill, q.game_id)
        row["cents_per_fill"] = round(100 * float(mean), 2)
        row["t_per_fill"] = round(float(t), 2) if np.isfinite(t) else None
        row["stated_edge_cents"] = round(
            100 * float((fill * edge[ok]).sum() / fill.sum()), 2
        )
    if len(q) >= 2:
        mean, t = plain_mean_t(fill * pnl, q.game_id)
        row["usd_per_100_eligible"] = round(100 * float(mean), 2)
        row["t_per_order"] = round(float(t), 2) if np.isfinite(t) else None
        row["usd_total"] = round(float((fill * pnl).sum()), 2)
    return row


def per_rung_profit(rungs, source, share):
    ok, _ = eligible(rungs, source)
    return ok * fill_amount(rungs.through, share) * rungs.pnl_c.to_numpy(dtype=float)


def replay(rungs):
    """Per source, flow share, stratum and half; plus paired ladder-vs-live profit."""
    rows, paired = [], []
    for share in SHARES:
        for name in STRATA:
            for half in ("all", "h1", "h2"):
                r = _stratum(rungs, name)
                if half != "all":
                    r = r[r.half.eq(half)]
                if r.empty:
                    continue
                for s in REPLAY_SOURCES:
                    row = {"flow_share": share, "stratum": name, "half": half}
                    rows.append(row | {"source": s} | replay_one(r, s, share))
                base = per_rung_profit(r, "live", share)
                for s in ("ladder_nb", "ladder_normal"):
                    diff = per_rung_profit(r, s, share) - base
                    mean, t = plain_mean_t(diff, r.game_id)
                    paired.append(
                        {
                            "flow_share": share,
                            "stratum": name,
                            "half": half,
                            "a": s,
                            "b": "live",
                            "rungs": int(len(r)),
                            "usd_per_100_rungs_a_minus_b": round(100 * float(mean), 2),
                            "t": round(float(t), 2) if np.isfinite(t) else None,
                        }
                    )
    return rows, paired


# ------------------------------------------------------------------- report


def run(orders=None, book=None):
    book = load_books() if book is None else book
    orders = load_orders() if orders is None else orders
    fits, shapes = fit_all(book)
    rungs, counts = price_rungs(orders, book, fits)
    rows, paired = replay(rungs)
    ladders = fits.n_lines.clip(upper=3).map({1: "1", 2: "2", 3: "3+"})
    return {
        "plan": "RESEARCH_LOG.md, 2026-10-22, test C (exploratory, in-sample 2025-26)",
        "variants": list(FAMILIES),
        "variant_count": len(FAMILIES),
        "simulated": "Replay P&L is simulated from public trade prints, first in "
        "line at flow share 1.0; 0.25 is the expected fill. No live data.",
        "split": SPLIT.isoformat(),
        "book_games": int(book.game_id.nunique()),
        "ladders": {k: int(v) for k, v in ladders.value_counts().sort_index().items()},
        "pooled_shapes_first_half": shapes,
        "fit_error": fit_error(book, fits),
        "coverage": counts,
        "calibration": calibration(rungs),
        "replay": rows,
        "paired_replay": paired,
    }


def _md_replay(results, stratum, half, share):
    rows = [
        r
        for r in results["replay"]
        if r["stratum"] == stratum and r["half"] == half and r["flow_share"] == share
    ]
    lines = []
    for r in rows:
        lines.append(
            f"| {SOURCES[r['source']]} | {r['eligible']:,} | {r['fills']:,.1f} | "
            f"{r.get('stated_edge_cents', float('nan')):+.2f} | "
            f"{r.get('cents_per_fill', float('nan')):+.2f} | {r.get('t_per_fill')} | "
            f"{r.get('usd_per_100_eligible', float('nan')):+.2f} | {r.get('t_per_order')} |"
        )
    return lines


def write_markdown(results, path):
    c = results["coverage"]
    lines = [
        "# Ladder prices from the sportsbooks (test C; exploratory, in-sample, simulated)",
        "",
        "Plan: RESEARCH_LOG.md, 2026-10-22, test C. Variants: negative binomial and "
        f"normal ({results['variant_count']}). 2025-26 season, "
        f"{results['book_games']} games with sportsbook history. Replay fills come "
        "from public trade prints as if first in line (flow share 1.0) or as the "
        "expected fill at flow share 0.25; nothing here is live.",
        "",
        f"Rungs in those games: {c['rungs_in_book_games']:,}; posted before the "
        f"game's book snapshot (excluded): {c['posted_before_snapshot']:,}; no book "
        f"line at all for the player and stat (excluded): "
        f"{c['no_book_line_for_player_stat']:,}. Priced: {c['rungs_priced']:,} in "
        f"{c['games']} games; exact line with 2+ books {c['exact2']:,}, with 1 book "
        f"{c['exact1']:,}, not quoted {c['no_exact']:,}.",
        "",
        "## Fit check",
        "",
        f"Ladders (player-stat-game) by number of book lines: {results['ladders']}.",
        "Single-line ladders use a per-stat shape from 3+ line ladders before "
        f"{results['split']}:",
        "",
        "| Stat | NB size | ladders | Normal sd / mean | ladders |",
        "|---|---:|---:|---:|---:|",
    ]
    shapes = results["pooled_shapes_first_half"]
    for stat in sorted(shapes["nb"]):
        nb, n = shapes["nb"][stat], shapes["normal"].get(stat, {})
        lines.append(
            f"| {stat} | {nb['shape']:.2f} | {nb['ladders']} | "
            f"{n.get('shape', float('nan')):.3f} | {n.get('ladders', 0)} |"
        )
    lines += [
        "",
        "Fitted minus book probability at the book's own lines (absolute):",
        "",
        "| Lines | NB median | NB 90th pct | Normal median | Normal 90th pct | Lines (n) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    fe = results["fit_error"]
    for name, v in fe["nb"].items():
        if not isinstance(v, dict):
            continue
        n = fe["normal"][name]
        lines.append(
            f"| {name} | {v['median_abs_error']:.4f} | {v['p90_abs_error']:.4f} | "
            f"{n['median_abs_error']:.4f} | {n['p90_abs_error']:.4f} | {v['lines']:,} |"
        )
    lines.append(
        f"\nLadders ending on a parameter bound: NB {fe['nb']['ladders at a bound']}, "
        f"normal {fe['normal']['ladders at a bound']}."
    )
    lines += ["", "## Calibration on Kalshi rungs (outcomes, in-sample)", ""]
    for name, block in results["calibration"].items():
        lines += [
            f"**{STRATA[name]}**: {block['rungs']:,} rungs, {block['games']} games, "
            f"over rate {block['over_rate']:.3f}.",
            "",
            "| Source | Log loss | Brier |",
            "|---|---:|---:|",
        ]
        for s, v in block["sources"].items():
            lines.append(f"| {SOURCES[s]} | {v['log_loss']:.4f} | {v['brier']:.4f} |")
        lines += [
            "",
            "| Paired log loss | A minus B | clustered t |",
            "|---|---:|---:|",
        ]
        for p in block["paired_log_loss"]:
            lines.append(
                f"| {SOURCES[p['a']]} − {SOURCES[p['b']]} | {p['a_minus_b']:+.4f} | {p['t']} |"
            )
        lines.append("")
    head = (
        "| Fair value | Eligible | Fills | Stated edge ¢ | ¢ per fill | t | "
        "$ per 100 eligible | t |"
    )
    sep = "|---|---:|---:|---:|---:|---:|---:|---:|"
    lines += [
        "## Replay (simulated): one-contract NO, 0-15¢ edge, NO 5-95¢, no caps, no fee",
        "",
        "Stated edge: the source's fair value minus our price, averaged over fills. "
        "t: game-clustered.",
        "",
    ]
    for share in SHARES:
        for name in STRATA:
            lines += [f"**{STRATA[name]}, flow share {share:g}**", "", head, sep]
            lines += _md_replay(results, name, "all", share)
            lines.append("")
    lines += ["### By half, rungs with no 2-book exact line", ""]
    for share in SHARES:
        for half, label in (("h1", "before"), ("h2", "from")):
            lines += [
                f"**{label} {results['split']}, flow share {share:g}**",
                "",
                head,
                sep,
            ]
            lines += _md_replay(results, "no_exact2", half, share)
            lines.append("")
    lines += [
        "### Paired: ladder minus live rule, $ per 100 rungs (same rungs)",
        "",
        "| Flow share | Rungs | Half | Ladder | Rungs (n) | $ per 100 rungs | t |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for p in results["paired_replay"]:
        lines.append(
            f"| {p['flow_share']:g} | {STRATA[p['stratum']]} | {p['half']} | "
            f"{SOURCES[p['a']]} | {p['rungs']:,} | "
            f"{p['usd_per_100_rungs_a_minus_b']:+.2f} | {p['t']} |"
        )
    Path(path).write_text("\n".join(lines) + "\n")


def main():
    results = run()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "explore_ladder.json").write_text(json.dumps(results, indent=1) + "\n")
    write_markdown(results, OUT / "explore_ladder.md")
    print(json.dumps(results["calibration"], indent=1))
    print(json.dumps(results["coverage"], indent=1))


if __name__ == "__main__":
    main()
