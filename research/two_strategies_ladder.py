"""Ladder maker checks (exploratory; RESEARCH_LOG.md, 2026-10-22, two
proposed NBA strategies). Run through ``python -m research.two_strategies ladder``.

1. Splits of exploration C's negative-binomial ladder replay (2025-26, rungs
   without a two-book line), descriptive only.
2. This season's sportsbook feed: alternate-line coverage, and how many
   Kalshi rungs get a ladder price without a two-book line, with spreads.
3. A pipeline check on this season's nights with logged results: ladder
   prices, the stat model and Kalshi's mid against outcomes, and paper fills
   from public trade prints. Far too small to be evidence.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from research import explore_ladder as el
from research.fill_sizing_replay import clustered_mean_t, load_orders
from research.two_strategies import write

ET = "America/New_York"
SERIES = ("KXNBAPTS", "KXNBAREB", "KXNBAAST", "KXNBA3PT")
TICK = 0.01


# ------------------------------------------------------------ 1. splits


def nearest_book_line(rungs, book):
    """Distance from each rung's line to the nearest book line, same ladder."""
    lines = book[el.KEYS + ["line"]].rename(columns={"line": "book_line"})
    m = rungs[el.KEYS + ["line"]].reset_index().merge(lines, on=el.KEYS)
    m["gap"] = (m.line - m.book_line).abs()
    return m.groupby("index").gap.min().reindex(rungs.index)


def splits(rungs, book):
    r = rungs[~rungs.exact2].copy()
    r["gap"] = nearest_book_line(r, book)
    r["spread"] = (r.yes_ask.astype(float) - r.yes_bid.astype(float)).round(2)
    bins = {
        "stat": r.stat,
        "book lines for player and stat": r.n_lines.clip(upper=3).map(
            {1: "1", 2: "2", 3: "3+"}
        ),
        "spread at posting": np.where(r.spread >= 0.02 - 1e-9, "2¢+", "1¢"),
        "distance from nearest book line": pd.cut(
            r.gap,
            [-0.1, 0.1, 3.0, 1e9],
            labels=["0 (one-book line)", "1-3", "more than 3"],
        ),
    }
    out = {}
    for name, labels in bins.items():
        rows = []
        for label in pd.unique(pd.Series(labels).dropna()):
            part = r[pd.Series(labels, index=r.index).eq(label)]
            row = {"bin": str(label), "rungs": len(part)}
            for source in ("ladder_nb", "live"):
                ok, _ = el.eligible(part, source)
                q = part[ok]
                fill = el.fill_amount(q.through, 1.0)
                if fill.sum() >= 2:
                    mean, t = clustered_mean_t(q.pnl_c, fill, q.game_id)
                    row[source] = {
                        "eligible": int(ok.sum()),
                        "fills": float(fill.sum()),
                        "cents": 100 * float(mean),
                        "t": float(t),
                    }
            rows.append(row)
        out[name] = sorted(rows, key=lambda x: x["bin"])
    return out


# ----------------------------------------------------- 2. this season


def season_frames(root):
    root = Path(root)
    snaps = sorted((root / "data/kalshi/2027").glob("*.csv.gz"))
    cols = ["snapshot_utc", "series", "ticker", "yes_bid_dollars", "yes_ask_dollars"]
    k = pd.concat([pd.read_csv(f, usecols=cols) for f in snaps], ignore_index=True)
    k = k[k.series.isin(SERIES)]
    lad = pd.concat(
        [
            pd.read_csv(f)
            for f in sorted((root / "outputs/projections/ladders").glob("*.csv"))
        ],
        ignore_index=True,
    )
    lad["run_utc"] = pd.to_datetime(lad.snapshot_utc, utc=True, format="ISO8601")
    lad["tip"] = pd.to_datetime(lad.tip_utc, utc=True, format="ISO8601")
    books = pd.concat(
        [
            pd.read_csv(f)
            for f in sorted((root / "outputs/books").glob("nba_20*.csv.gz"))
        ],
        ignore_index=True,
    )
    books["snap"] = pd.to_datetime(books.snapshot_utc, utc=True, format="ISO8601")
    books["commence"] = pd.to_datetime(books.commence_utc, utc=True, format="ISO8601")
    books["line"] = pd.to_numeric(books.line).round(1)
    return k, lad, books


def rungs_this_season(root):
    """Kalshi rungs 2-6 hours before tip with the sportsbook ladder at that time."""
    k, lad, books = season_frames(root)
    k["snap"] = pd.to_datetime(k.snapshot_utc, utc=True, format="ISO8601")
    keys = lad.sort_values("run_utc").drop_duplicates("ticker", keep="last")
    keys = keys[["ticker", "player_key", "stat", "line", "tip", "game_id"]]
    r = k.merge(keys, on="ticker")
    hours = (r.tip - r.snap).dt.total_seconds() / 3600
    bid, ask = r.yes_bid_dollars.astype(float), r.yes_ask_dollars.astype(float)
    r = r[hours.between(2, 6) & (bid > 0) & (ask < 1) & (ask > bid)].copy()
    r = r.sort_values("snap").drop_duplicates("ticker", keep="first")  # earliest look
    r["line"] = pd.to_numeric(r.line).round(1)
    # The model's probability at the latest projection run before the look.
    runs = lad[["ticker", "run_utc", "p_model"]].sort_values("run_utc")
    r["snap"] = r.snap.astype("datetime64[ns, UTC]")
    runs["run_utc"] = runs.run_utc.astype("datetime64[ns, UTC]")
    r = pd.merge_asof(
        r.sort_values("snap"), runs, left_on="snap", right_on="run_utc", by="ticker"
    )
    # The sportsbook ladder: latest book snapshot at or before the look.
    ladders = []
    for row in r.itertuples():
        g = books[
            books.player_key.eq(row.player_key)
            & books.stat.eq(row.stat)
            & (books.snap <= row.snap)
            & ((books.commence - row.tip).abs() <= pd.Timedelta(minutes=15))
        ]
        if g.empty:
            ladders.append(None)
            continue
        g = g[g.snap.eq(g.snap.max())]
        ladders.append(g[["line", "p_book", "book_n"]])
    r["book"] = ladders
    r["n_lines"] = [0 if b is None else len(b) for b in ladders]
    r["exact2"] = [
        bool((((b.line - ln).abs() < 1e-6) & (b.book_n >= 2)).any())
        if b is not None
        else False
        for b, ln in zip(ladders, r.line)
    ]
    r["night"] = r.tip.dt.tz_convert(ET).dt.strftime("%Y-%m-%d")
    r["spread"] = (r.yes_ask_dollars - r.yes_bid_dollars).round(2)
    return r


def coverage(r, books):
    near = books.copy()
    per = near.groupby(["snapshot_utc", "player_key", "stat"]).line.nunique()
    has = r.n_lines > 0
    no2 = has & ~r.exact2
    return {
        "nights": sorted(r.night.unique()),
        "book_lines_per_player_stat": {
            "median": float(per.median()),
            "mean": float(per.mean()),
            "share_with_3_plus": float((per >= 3).mean()),
        },
        "kalshi_rungs": len(r),
        "with_two_book_line": int(r.exact2.sum()),
        "ladder_price_but_no_two_book_line": int(no2.sum()),
        "no_book_line_for_player_stat": int((~has).sum()),
        "spread_2c_plus_two_book": float((r.spread[r.exact2] >= 0.02).mean()),
        "spread_2c_plus_ladder_only": float((r.spread[no2] >= 0.02).mean()),
    }


# ------------------------------------------------ 3. pipeline check


def nb_price(r, shapes):
    out = []
    for b, ln, stat in zip(r.book, r.line, r.stat):
        if b is None or len(b) == 0:
            out.append(np.nan)
            continue
        fixed = None if len(b) >= 2 else shapes["nb"][stat]["shape"]
        f = el.fit_ladder(
            b.line.to_numpy(float),
            b.p_book.to_numpy(float),
            b.book_n.to_numpy(float),
            "nb",
            fixed,
        )
        out.append(float(el.over_prob("nb", np.array([ln]), f["mean"], f["shape"])[0]))
    return np.array(out)


def paper_fills(r, root):
    """Contracts a YES taker bought through each paper NO order before tip."""
    root = Path(root)
    files = sorted((root / "data/kalshi/2027/trades").glob("20??-??-??.csv.gz"))
    t = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    t["when"] = pd.to_datetime(t.created_time, utc=True, format="ISO8601")
    m = t.merge(r[["ticker", "snap", "tip", "yes_level", "improved"]], on="ticker")
    m = m[(m.when > m.snap) & (m.when <= m.tip)]
    same = (m.yes_price.astype(float) - m.yes_level).abs() < 1e-6
    better = m.yes_price.astype(float) > m.yes_level + 1e-6
    hit = m.taker_outcome_side.astype(str).str.lower().eq("yes") & (
        better | (same & m.improved)
    )
    return r.ticker.map(m[hit].groupby("ticker")["count"].sum()).fillna(0.0)


def pipeline_check(r, root, shapes):
    root = Path(root)
    res = pd.concat(
        [
            pd.read_csv(f)
            for f in sorted((root / "data/kalshi/2027/results").glob("*.csv.gz"))
        ],
        ignore_index=True,
    )
    r = r.merge(res[["ticker", "result"]], on="ticker")
    r = r[r.result.isin(["yes", "no"]) & (r.n_lines > 0) & ~r.exact2].copy()
    r["over"] = r.result.eq("yes").astype(float)
    r["ladder_nb"] = nb_price(r, shapes)
    r["mid"] = (r.yes_bid_dollars + r.yes_ask_dollars) / 2
    r = r[r.ladder_nb.notna() & r.p_model.notna()]
    out = {
        "rungs": len(r),
        "games": int(r.game_id.nunique()),
        "nights": sorted(r.night.unique()),
    }
    for source in ("ladder_nb", "p_model", "mid"):
        out[f"log_loss_{source}"] = float(el.log_loss(r[source], r.over).mean())
    improve = r.spread >= 0.02 - 1e-9
    r["price"] = (1 - r.yes_ask_dollars + np.where(improve, TICK, 0)).round(4)
    r["improved"] = improve
    r["yes_level"] = (1 - r.price).round(4)
    r["through"] = paper_fills(r, root)
    r["pnl_c"] = (1 - r.over) - r.price
    for source in ("ladder_nb", "p_model"):
        ok, _ = el.eligible(r, source)
        q = r[ok]
        fill = el.fill_amount(q.through, 1.0)
        out[f"paper_{source}"] = {
            "orders": int(ok.sum()),
            "fills": float(fill.sum()),
            "pnl_usd": float((fill * q.pnl_c).sum()),
        }
    return out


def ladder(root="."):
    orders = load_orders()
    book = el.load_books()
    fits, shapes = el.fit_all(book)
    rungs, _ = el.price_rungs(orders, book, fits)
    results = {"splits_2025_26": splits(rungs, book)}
    r = rungs_this_season(root)
    _, _, books = season_frames(root)
    results["this_season"] = coverage(r, books)
    results["pipeline_check"] = pipeline_check(r, root, shapes)
    write("ladder", results, ladder_md(results))


def ladder_md(res):
    lines = [
        "# Ladder maker checks (exploratory)",
        "",
        "## 1. 2025-26 replay, rungs without a two-book line, by slice (simulated, in-sample)",
        "",
        "Negative-binomial ladder against the current rule (two-book line, else the",
        "stat model) on the same rungs; one contract, first in line, no caps.",
        "",
    ]
    for name, rows in res["splits_2025_26"].items():
        lines += [
            f"### {name}",
            "",
            "| Bin | Rungs | Ladder fills | Ladder ¢ (t) | Current rule fills | Current rule ¢ (t) |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for row in rows:
            a, b = row.get("ladder_nb", {}), row.get("live", {})
            lines.append(
                f"| {row['bin']} | {row['rungs']:,} | {a.get('fills', 0):,.0f} | "
                f"{a.get('cents', float('nan')):+.2f} ({a.get('t', float('nan')):.2f}) | "
                f"{b.get('fills', 0):,.0f} | {b.get('cents', float('nan')):+.2f} "
                f"({b.get('t', float('nan')):.2f}) |"
            )
        lines.append("")
    c = res["this_season"]
    lines += [
        "## 2. This season's feed (public snapshots, 2-6 hours before tip)",
        "",
        f"Nights: {', '.join(c['nights'])}. Sportsbook lines per player and stat in a "
        f"snapshot: median {c['book_lines_per_player_stat']['median']:.0f}, mean "
        f"{c['book_lines_per_player_stat']['mean']:.1f}; "
        f"{c['book_lines_per_player_stat']['share_with_3_plus']:.0%} have 3 or more "
        "(the feed already includes alternate lines).",
        "",
        f"Of {c['kalshi_rungs']:,} Kalshi rungs: {c['with_two_book_line']:,} have a two-book "
        f"line (v5's universe), {c['ladder_price_but_no_two_book_line']:,} would get a "
        f"ladder price without one, {c['no_book_line_for_player_stat']:,} have no book line "
        f"for the player and stat. Spread of 2¢ or more: "
        f"{c['spread_2c_plus_two_book']:.0%} of two-book rungs, "
        f"{c['spread_2c_plus_ladder_only']:.0%} of ladder-only rungs.",
        "",
        "## 3. Pipeline check on this season (not evidence: two nights)",
        "",
    ]
    p = res["pipeline_check"]
    lines += [
        f"{p['rungs']:,} ladder-only rungs with results in {p['games']} games "
        f"({', '.join(p['nights'])}). Log loss: ladder {p['log_loss_ladder_nb']:.4f}, "
        f"stat model {p['log_loss_p_model']:.4f}, Kalshi mid {p['log_loss_mid']:.4f}.",
        "",
        f"Paper orders (edge 0-15¢, NO 5-95¢, first in line): ladder "
        f"{p['paper_ladder_nb']['orders']} orders, {p['paper_ladder_nb']['fills']:.0f} fills, "
        f"${p['paper_ladder_nb']['pnl_usd']:+.2f}; stat model "
        f"{p['paper_p_model']['orders']} orders, {p['paper_p_model']['fills']:.0f} fills, "
        f"${p['paper_p_model']['pnl_usd']:+.2f}. Simulated.",
        "",
    ]
    return "\n".join(lines)
