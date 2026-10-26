"""Novig, ProphetX and other US exchanges against the sportsbook consensus.

Exploratory, read-only (RESEARCH_LOG.md, 2026-10-23, "Novig and ProphetX
price check" and its forward study). Each run pulls The Odds API's ``us``
(sportsbooks) and ``us_ex`` (exchanges) regions for NBA and NFL games.

- **Early runs** (EARLY_HOURS, UTC) take every game starting in the next
  EARLY_WINDOW_HOURS and flag each exchange price that is at least FLAG_EDGE
  better than the de-vigged consensus of two or more sportsbooks on the same
  line (a +EV take, if the consensus is right).
- **Every run** takes a closing snapshot of games starting in the next
  CLOSE_WINDOW_MINUTES (once per game) and scores the flags on that game by
  closing line value: the closing consensus probability of the flagged side
  minus the price the flag would have paid. Positive on average means the
  flagged prices really were good; the standard test for a betting edge.

Per-line state lives in an Actions cache (``state/``), never in the
repository: raw odds are licensed. Only aggregates are committed
(outputs/exchange_gaps/). Prices are quoted take prices without depth; fees
are not subtracted (Novig pregame 0%, ProphetX 0-2% of net winnings, Kalshi
about 0.07 x p x (1 - p) per contract).
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi import books
from kalshi.stats import clustered_mean_t

OUT = Path("outputs/exchange_gaps")
STATE = Path("state/exchange_gaps")
EXCHANGES = ("novig", "prophetx", "kalshi", "polymarket_us", "betopenly")
SPORTS = {
    "nba": (
        "basketball_nba",
        "h2h,spreads,totals,player_points,player_rebounds,player_assists,player_threes",
    ),
    "nfl": (
        "americanfootball_nfl",
        "h2h,spreads,totals,player_pass_yds,player_rush_yds,player_reception_yds,"
        "player_receptions",
    ),
}
EARLY_HOURS = (15, 19)  # UTC hours whose run also flags (all games ahead)
EARLY_WINDOW_HOURS = 14
CLOSE_WINDOW_MINUTES = 75
FLAG_EDGE = 0.02
MIN_REMAINING = 20000  # never draw the shared key below this (100K plan)
MAX_RUN_CREDITS = 1500
STUDY_END = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)  # one week; then runs do nothing
KEYS = ["event", "market", "who", "point"]


def flatten(odds):
    """One row per book, market line and side, with a two-sided key."""
    rows = []
    home = odds.get("home_team")
    for book in odds.get("bookmakers") or []:
        for market in book.get("markets") or []:
            mk = market.get("key")
            for o in market.get("outcomes") or []:
                name, point, price = o.get("name"), o.get("point"), o.get("price")
                if price is None:
                    continue
                if mk == "h2h":
                    who, pt, side = "", None, "home" if name == home else "away"
                elif mk == "spreads":
                    who, side = "", "home" if name == home else "away"
                    pt = point if name == home else -point
                else:  # totals and player props: Over/Under at one point
                    who, pt, side = o.get("description") or "", point, str(name).lower()
                rows.append(
                    {
                        "event": odds.get("id"),
                        "commence": odds.get("commence_time"),
                        "market": mk,
                        "who": who,
                        "point": pt,
                        "side": side,
                        "book": book.get("key"),
                        "p": float(books.implied(price)),
                    }
                )
    return rows


def two_sided(frame):
    """(event, market, who, point, book) with ``a`` (home/over) and ``b``
    (away/under) take prices; only lines quoted on both sides."""
    if frame.empty:
        return pd.DataFrame(columns=KEYS + ["book", "a", "b", "kind", "commence"])
    # pivot_table drops rows whose key is missing: moneylines have no point.
    frame = frame.assign(point=frame.point.astype(float).fillna(-9999.0))
    frame = frame.drop_duplicates(KEYS + ["side", "book"])
    wide = frame.pivot_table(
        index=KEYS + ["book"], columns="side", values="p", aggfunc="first"
    ).reset_index()
    for column in ("home", "away", "over", "under"):
        if column not in wide:
            wide[column] = np.nan
    wide["a"] = wide.home.fillna(wide.over)
    wide["b"] = wide.away.fillna(wide.under)
    two = wide.dropna(subset=["a", "b"])[KEYS + ["book", "a", "b"]].copy()
    two["kind"] = np.where(two.market.str.startswith("player_"), "props", "game lines")
    starts = frame.drop_duplicates("event").set_index("event").commence
    two["commence"] = two.event.map(starts)
    return two


def consensus(two):
    """Fair probability of side ``a`` per line from 2+ sportsbooks, de-vigged."""
    sb = two[~two.book.isin(EXCHANGES)].copy()
    sb["fair_a"] = sb.a / (sb.a + sb.b)
    fair = sb.groupby(KEYS).agg(fair_a=("fair_a", "mean"), n=("fair_a", "size"))
    return fair[fair.n >= 2].reset_index()


def take_edges(two, fair):
    """Exchange sides with the consensus: one row per side, ``edge`` = fair
    probability of that side minus the price paid to take it."""
    ex = two[two.book.isin(EXCHANGES)].merge(fair, on=KEYS, how="inner")
    a = ex.assign(side="a", price=ex.a, fair=ex.fair_a)
    b = ex.assign(side="b", price=ex.b, fair=1 - ex.fair_a)
    out = pd.concat([a, b], ignore_index=True)
    out["edge"] = out.fair - out.price
    return out[KEYS + ["commence", "kind", "book", "side", "price", "fair", "edge"]]


def snapshot_summary(two, fair):
    """Aggregates for one snapshot (as the first run reported)."""
    out = {"exchanges": {}, "locks": {}}
    is_ex = two.book.isin(EXCHANGES)
    edges = take_edges(two, fair)
    for venue, g in two[is_ex].groupby("book"):
        row = {
            "lines_quoted": int(len(g)),
            "overround_median": round(float((g.a + g.b - 1).median()), 4),
            "props_lines": int((g.kind == "props").sum()),
        }
        e = edges[edges.book == venue].edge
        if len(e):
            row.update(
                {
                    "sides_checked": int(len(e)),
                    "take_edge_mean": round(float(e.mean()), 4),
                    "share_over_2pct": round(float((e > 0.02).mean()), 3),
                    "share_over_5pct": round(float((e > 0.05).mean()), 3),
                }
            )
        out["exchanges"][venue] = row
    best = (
        two[is_ex]
        .groupby(KEYS)
        .agg(a=("a", "min"), b=("b", "min"), venues=("book", "nunique"))
    )
    multi = best[best.venues >= 2]
    margin = 1 - (multi.a + multi.b)
    out["locks"] = {
        "lines_on_2plus_exchanges": int(len(multi)),
        "locks_before_fees": int((margin > 0).sum()),
        "locks_over_1pct": int((margin > 0.01).sum()),
        "best_margin": round(float(margin.max()), 4) if len(margin) else None,
    }
    return out


def closing_value(flags, closing_fair):
    """Flags scored at the close: ``clv`` = closing fair probability of the
    flagged side minus the price the flag would have paid."""
    if flags.empty or closing_fair.empty:
        return flags.iloc[0:0].assign(close_fair=[], clv=[])
    m = flags.merge(closing_fair[KEYS + ["fair_a"]], on=KEYS, how="inner")
    m["close_fair"] = np.where(m.side == "a", m.fair_a, 1 - m.fair_a)
    m["clv"] = m.close_fair - m.price
    return m.drop(columns="fair_a")


def clv_summary(scored):
    out = {"flags_scored": int(len(scored))}
    if scored.empty:
        return out
    scored = scored.assign(bucket=np.where(scored.edge >= 0.05, "5+ pts", "2-5 pts"))
    for (venue, bucket), g in scored.groupby(["book", "bucket"]):
        # Lines in one game move together: report games as well as flags.
        out[f"{venue} {bucket}"] = {
            "flags": int(len(g)),
            "games": int(g.event.nunique()),
            "edge_at_flag": round(float(g.edge.mean()), 4),
            "clv_mean": round(float(g.clv.mean()), 4),
            "clv_t_game_clustered": (
                round(float(clustered_mean_t(g.clv, g.event)[1]), 2)
                if g.event.nunique() >= 2
                else None
            ),
            "share_clv_positive": round(float((g.clv > 0).mean()), 3),
        }
    return out


def _read(name):
    path = STATE / name
    return pd.read_parquet(path) if path.exists() else None


def main(now=None):
    now = now or datetime.now(UTC)
    if now >= STUDY_END:
        print("study ended", STUDY_END.isoformat(), "- nothing fetched")
        return
    key = books.api_key()
    early = now.hour in EARLY_HOURS
    flags = _read("flags.parquet")
    scored = _read("scored.parquet")
    done = (
        set(_read("closed.parquet").event)
        if _read("closed.parquet") is not None
        else set()
    )
    run = {"utc": now.isoformat(), "early": early}
    spent, quota = 0, None
    new_flags, new_scored, closed = [], [], []
    for name, (sport, markets) in SPORTS.items():
        evs, usage = books.events(key, sport)
        remaining = int(usage.get("remaining") or 0)
        used = int(usage.get("used") or 0)
        quota = remaining + used  # this month's allowance (plan size)
        rows, wanted = [], []
        for e in evs:
            start = pd.Timestamp(e["commence_time"]).to_pydatetime()
            minutes = (start - now).total_seconds() / 60
            if e["id"] in done:
                continue  # already closed and scored
            closing = 5 < minutes <= CLOSE_WINDOW_MINUTES
            # Flags need time before the close; a game about to close is not re-flagged.
            ahead = CLOSE_WINDOW_MINUTES < minutes <= EARLY_WINDOW_HOURS * 60
            if closing or (early and ahead):
                wanted.append((e, closing))
        for e, closing in wanted:
            if remaining < MIN_REMAINING or spent > MAX_RUN_CREDITS:
                run.setdefault("stopped_early", []).append(name)
                break
            try:
                odds, usage = books.event_odds(
                    key, e["id"], sport, markets.split(","), "us,us_ex"
                )
            except books.BooksError as error:
                print(name, "event failed:", str(error)[:120])
                continue
            before, remaining = remaining, int(usage.get("remaining") or remaining)
            spent += max(0, before - remaining)
            got = flatten(odds)
            rows += got
            if closing:
                closed.append(e["id"])
                two = two_sided(pd.DataFrame(got))
                if flags is not None and len(two):
                    new_scored.append(
                        closing_value(flags[flags.event == e["id"]], consensus(two))
                    )
        frame = pd.DataFrame(rows)
        two = two_sided(frame)
        fair = consensus(two) if len(two) else pd.DataFrame(columns=KEYS + ["fair_a"])
        run[name] = {
            "games": len(wanted),
            **(snapshot_summary(two, fair) if len(two) else {}),
        }
        if early and len(two):
            edges = take_edges(two, fair)
            f = edges[edges.edge >= FLAG_EDGE].assign(flagged_utc=now.isoformat())
            new_flags.append(f)
    run["credits_spent"], run["monthly_quota"] = spent, quota
    STATE.mkdir(parents=True, exist_ok=True)
    if new_flags:
        both = [x for x in (flags, *new_flags) if x is not None and len(x)]
        flags = pd.concat(both, ignore_index=True) if both else flags
        if flags is not None:
            flags = flags.drop_duplicates(KEYS + ["book", "side"], keep="first")
            flags.to_parquet(STATE / "flags.parquet")
    if new_scored:
        parts = [x for x in (scored, *new_scored) if x is not None and len(x)]
        if parts:
            scored = pd.concat(parts, ignore_index=True)
            scored.to_parquet(STATE / "scored.parquet")
    if closed:
        pd.DataFrame({"event": sorted(done | set(closed))}).to_parquet(
            STATE / "closed.parquet"
        )
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "history.jsonl").open("a") as f:
        f.write(json.dumps(run) + "\n")
    summary = {
        "note": "Exploratory forward study, read-only. CLV = closing sportsbook "
        "consensus minus the exchange price a flag would have paid; quoted prices "
        "without depth; fees not subtracted; never add to live results.",
        "updated_utc": now.isoformat(),
        "flags_recorded": 0 if flags is None else int(len(flags)),
        **clv_summary(scored if scored is not None else pd.DataFrame()),
    }
    (OUT / "clv_summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps({"run": run, "summary": summary}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
