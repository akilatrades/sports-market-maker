"""Novig, ProphetX and other US exchanges against the sportsbook consensus.

Exploratory, read-only, one snapshot (RESEARCH_LOG.md, 2026-10-23, "Novig and
ProphetX price check"). For upcoming NBA and NFL games it pulls The Odds
API's ``us`` (sportsbooks) and ``us_ex`` (exchanges) regions and asks:

1. Taking a price on an exchange: how often is it better than the de-vigged
   consensus of two or more sportsbooks on the same line (a +EV take)?
2. How wide is each exchange (its two sides' implied prices summed)?
3. Cross-exchange locks: the best price for one side on any exchange plus the
   best price for the other side on any exchange costing under $1.

Only aggregated results are written (outputs/exchange_gaps/); raw odds are
licensed and never saved. Exchange prices are the feed's quoted take prices;
depth (how much is available) is not in the feed. Fees are not subtracted
here: Novig pregame 0%, ProphetX 0-2% of net winnings, Kalshi about
0.07 x p x (1 - p) per contract.
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi import books

OUT = Path("outputs/exchange_gaps")
EXCHANGES = ("novig", "prophetx", "kalshi", "polymarket_us", "betopenly")
SPORTS = {
    "nba": (
        "basketball_nba",
        "h2h,spreads,totals,player_points,player_rebounds,player_assists,player_threes",
        30,
    ),
    "nfl": (
        "americanfootball_nfl",
        "h2h,spreads,totals,player_pass_yds,player_rush_yds,player_reception_yds,"
        "player_receptions",
        100,
    ),
}
MIN_REMAINING = 5000  # never draw the shared key below this
MAX_RUN_CREDITS = 700


def flatten(odds):
    """One row per book, market line and side, with a two-sided ``key``."""
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
                    key, side = (mk, "", None), "home" if name == home else "away"
                elif mk == "spreads":
                    hp = point if name == home else -point
                    key, side = (mk, "", hp), "home" if name == home else "away"
                else:  # totals and player props: Over/Under at one point
                    key = (mk, o.get("description") or "", point)
                    side = str(name).lower()
                rows.append(
                    {
                        "event": odds.get("id"),
                        "market": mk,
                        "who": key[1],
                        "point": key[2],
                        "side": side,
                        "book": book.get("key"),
                        "p": float(books.implied(price)),
                    }
                )
    return rows


def analyse(frame):
    keys = ["event", "market", "who", "point"]
    # pivot_table drops rows whose key is missing: moneylines have no point.
    frame = frame.assign(point=frame.point.astype(float).fillna(-9999.0))
    frame = frame.drop_duplicates(keys + ["side", "book"])
    wide = frame.pivot_table(
        index=keys + ["book"], columns="side", values="p", aggfunc="first"
    ).reset_index()
    for column in ("home", "away", "over", "under"):
        if column not in wide:
            wide[column] = np.nan
    wide["a"] = wide.home.fillna(wide.over)
    wide["b"] = wide.away.fillna(wide.under)
    two = wide.dropna(subset=["a", "b"]).copy()
    two["kind"] = np.where(two.market.str.startswith("player_"), "props", "game lines")
    is_ex = two.book.isin(EXCHANGES)
    # Sportsbook consensus: de-vig each book, average over books, need 2+.
    sb = two[~is_ex].copy()
    sb["fair_a"] = sb.a / (sb.a + sb.b)
    fair = sb.groupby(keys).agg(fair_a=("fair_a", "mean"), n=("fair_a", "size"))
    fair = fair[fair.n >= 2].reset_index()
    ex = two[is_ex].merge(fair, on=keys, how="left")
    out = {"exchanges": {}, "locks": {}}
    for venue, g in ex.groupby("book"):
        row = {
            "lines_quoted": int(len(g)),
            "lines_with_consensus": int(g.fair_a.notna().sum()),
        }
        row["overround_median"] = round(float((g.a + g.b - 1).median()), 4)
        for kind, k in g.groupby("kind"):
            row[f"{kind}_lines"] = int(len(k))
        c = g.dropna(subset=["fair_a"])
        if len(c):
            # Edge of taking each side: fair probability minus the price paid.
            edge = np.concatenate([c.fair_a - c.a, (1 - c.fair_a) - c.b])
            row.update(
                {
                    "sides_checked": int(len(edge)),
                    "take_edge_mean": round(float(edge.mean()), 4),
                    "share_take_edge_over_0": round(float((edge > 0).mean()), 3),
                    "share_take_edge_over_2pct": round(float((edge > 0.02).mean()), 3),
                    "share_take_edge_over_5pct": round(float((edge > 0.05).mean()), 3),
                    "edge_p90": round(float(np.percentile(edge, 90)), 4),
                }
            )
            for kind, k in c.groupby("kind"):
                e = np.concatenate([k.fair_a - k.a, (1 - k.fair_a) - k.b])
                row[f"{kind}_share_edge_over_2pct"] = round(float((e > 0.02).mean()), 3)
        out["exchanges"][venue] = row
    # Cross-exchange locks: cheapest side A + cheapest side B across exchanges.
    best = (
        two[is_ex]
        .groupby(keys)
        .agg(a=("a", "min"), b=("b", "min"), venues=("book", "nunique"))
    )
    multi = best[best.venues >= 2]
    margin = 1 - (multi.a + multi.b)
    out["locks"] = {
        "lines_on_2plus_exchanges": int(len(multi)),
        "locks_before_fees": int((margin > 0).sum()),
        "locks_over_1pct": int((margin > 0.01).sum()),
        "locks_over_2pct": int((margin > 0.02).sum()),
        "best_margin": round(float(margin.max()), 4) if len(margin) else None,
        "median_margin": round(float(margin.median()), 4) if len(margin) else None,
    }
    return out


def main():
    key = books.api_key()
    now = datetime.now(UTC)
    result = {
        "note": "Exploratory, one read-only snapshot; prices only, no depth; fees not "
        "subtracted; never add to live results",
        "snapshot_utc": now.isoformat(),
    }
    spent, remaining = 0, None
    for name, (sport, markets, hours) in SPORTS.items():
        evs, usage = books.events(key, sport)
        remaining = int(usage.get("remaining") or 0)
        soon = [
            e
            for e in evs
            if now
            < pd.Timestamp(e["commence_time"]).to_pydatetime()
            < now + timedelta(hours=hours)
        ]
        rows = []
        for e in soon:
            if remaining < MIN_REMAINING or spent > MAX_RUN_CREDITS:
                result.setdefault("stopped_early", []).append(name)
                break
            try:
                odds, usage = books.event_odds(
                    key, e["id"], sport, markets.split(","), "us,us_ex"
                )
            except books.BooksError as error:
                print(name, "event failed:", str(error)[:120])
                continue
            before = remaining
            remaining = int(usage.get("remaining") or remaining)
            spent += max(0, before - remaining)
            rows += flatten(odds)
        frame = pd.DataFrame(rows)
        result[name] = {"events": len(soon), **(analyse(frame) if len(frame) else {})}
        books_seen = sorted(frame.book.unique()) if len(frame) else []
        result[name]["books_seen"] = books_seen
    result["credits_spent"] = spent
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M")
    (OUT / f"snapshot_{stamp}.json").write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    sys.exit(main())
