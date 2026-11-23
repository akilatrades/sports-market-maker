"""Do Kalshi's YES buyers overpay more for some types of NBA player?

RESEARCH_LOG.md, 2026-11-23, "Do YES buyers overpay more for some types of
player?". Exploratory, on the in-sample 2025-26 replay file. It reads files
and writes tables; nothing here is used by the projections job or the bots.

Players are grouped by k-means on box scores from before the replay file's
first day (so a type cannot depend on the results tested), and each type is
compared with all other players on three measures, with game-clustered t.

    python -m live.fetch_nba_data       # data/player_games.parquet
    python -m research.player_types     # writes outputs/player_types/
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

from kalshi.stats import clustered_mean_t

ORDERS = Path("outputs/decompose/orders_no.csv.gz")
BOX = Path("data/player_games.parquet")
OUT = Path("outputs/player_types")
FIRST_SEASON = 2025  # the 2024-25 season, named by the year it ends
MIN_GAMES = 20
TYPES = 5  # the pre-registered grouping
SENSITIVITY = (4, 6)
V9_MIN_NO = 0.65
HALF = "2026-02-01"
LEAD_T = 3.0
NO_HISTORY = "little history"
FEATURES = ["minutes", "pts36", "reb36", "ast36", "fg3a36", "fga36", "three_share"]
MEASURES = {
    "fills": "Profit per filled contract, after fees (fills first in line)",
    "fills_v9": "The same, NO price 65 cents or more (rules v9)",
    "yes_overpay": "YES ask minus YES result, every market, before fees",
}


def player_features(box, before, min_games=MIN_GAMES):
    """Per-player averages from games before ``before``; index player_id."""
    played = box[
        (box.season >= FIRST_SEASON)
        & (box.tip_utc < before)
        & ~box.did_not_play
        & (box.minutes > 0)
    ]
    sums = played.groupby("player_id")[
        ["minutes", "points", "rebounds", "assists", "fg3a", "fga"]
    ].sum()
    games = played.groupby("player_id").size()
    per36 = 36 / sums.minutes
    out = pd.DataFrame(
        {
            "games": games,
            "minutes": sums.minutes / games,
            "pts36": sums.points * per36,
            "reb36": sums.rebounds * per36,
            "ast36": sums.assists * per36,
            "fg3a36": sums.fg3a * per36,
            "fga36": sums.fga * per36,
            "three_share": sums.fg3a / sums.fga.where(sums.fga > 0),
        }
    )
    return out[(out.games >= min_games) & out[FEATURES].notna().all(axis=1)]


def assign_types(features, k, seed=0):
    """k-means on standardised features. Types are numbered by points per 36,
    highest first, so the numbering does not depend on k-means' own order."""
    z = (features[FEATURES] - features[FEATURES].mean()) / features[FEATURES].std()
    raw = KMeans(n_clusters=k, random_state=seed, n_init=20).fit_predict(z)
    order = features.pts36.groupby(raw).mean().sort_values(ascending=False).index
    rank = {old: new + 1 for new, old in enumerate(order)}
    return pd.Series([rank[r] for r in raw], index=features.index, name="type")


def difference_t(values, inside, clusters):
    """Mean inside, mean outside, their difference and its game-clustered t."""
    values = np.asarray(values, dtype=float)
    inside = np.asarray(inside, dtype=bool)
    n_in, n_out = inside.sum(), (~inside).sum()
    if n_in < 2 or n_out < 2:
        return np.nan, np.nan, np.nan, np.nan
    mean_in, mean_out = values[inside].mean(), values[~inside].mean()
    # Each row's share of (mean inside - mean outside), linearised.
    n = len(values)
    z = n * np.where(inside, (values - mean_in) / n_in, -(values - mean_out) / n_out)
    _, t = clustered_mean_t(z + (mean_in - mean_out), clusters)
    return mean_in, mean_out, mean_in - mean_out, t


def measures(orders):
    """The three samples: name -> (frame, value column)."""
    filled = orders[orders.filled]
    every = orders[orders.yes_ask.notna() & orders.over.notna()].copy()
    every["yes_overpay"] = every.yes_ask - every.over
    return {
        "fills": (filled, "pnl_if_filled"),
        "fills_v9": (filled[filled.price >= V9_MIN_NO], "pnl_if_filled"),
        "yes_overpay": (every, "yes_overpay"),
    }


def compare(orders, labels):
    """One row per type and measure, in cents."""
    rows = []
    for name, (frame, column) in measures(orders).items():
        group = frame.player_id.map(labels).fillna(0).astype(int)
        for label in sorted(group.unique()):
            inside = (group == label).to_numpy()
            mean_in, _, diff, t = difference_t(frame[column], inside, frame.game_id)
            early = (frame.game_date < HALF).to_numpy()
            halves = [
                difference_t(frame[column][m], inside[m], frame.game_id[m])[2]
                for m in (early, ~early)
            ]
            rows.append(
                {
                    "measure": name,
                    "type": int(label),
                    "rows": int(inside.sum()),
                    "games": int(frame.game_id[inside].nunique()),
                    "mean_cents": 100 * mean_in,
                    "diff_cents": 100 * diff,
                    "t": t,
                    "diff_first_half_cents": 100 * halves[0],
                    "diff_second_half_cents": 100 * halves[1],
                }
            )
    return pd.DataFrame(rows)


def leads(table):
    """Types that clear the pre-registered bar (the "little history" group,
    type 0, is shown but cannot be a lead)."""
    wide = table[table.type > 0].pivot(index="type", columns="measure")
    found = []
    for label in wide.index:
        diff, t = wide.diff_cents.fills[label], wide.t.fills[label]
        # A NO seller gains where YES buyers overpay, so the signs must agree.
        same = np.sign(wide.diff_cents.yes_overpay[label]) == np.sign(diff)
        halves = (
            np.sign(wide.diff_first_half_cents.fills[label])
            == np.sign(wide.diff_second_half_cents.fills[label])
            == np.sign(diff)
        )
        if abs(t) >= LEAD_T and same and halves:
            found.append(int(label))
    return found


def describe(features, labels):
    """Each type's size and average features, for naming it."""
    joined = features.join(labels)
    table = joined.groupby("type")[FEATURES].mean().round(2)
    table.insert(0, "players", joined.groupby("type").size())
    return table


def main():
    orders = pd.read_csv(ORDERS)
    box = pd.read_parquet(BOX)
    first_day = pd.Timestamp(orders.game_date.min(), tz="UTC")
    features = player_features(box, first_day)
    features = features[features.index.isin(orders.player_id.unique())]
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {
        "status": "exploratory, in-sample (2025-26); fills assume first in line",
        "features_from_games_before": str(first_day.date()),
        "players_in_replay": int(orders.player_id.nunique()),
        "players_grouped": len(features),
        "comparisons": TYPES * len(MEASURES),
        "groupings_tried": 1 + len(SENSITIVITY),
        "lead_bar_t": LEAD_T,
    }
    for k in (TYPES, *SENSITIVITY):
        labels = assign_types(features, k)
        table = compare(orders, labels)
        suffix = "" if k == TYPES else f"_k{k}"
        table.round(3).to_csv(OUT / f"by_type{suffix}.csv", index=False)
        describe(features, labels).to_csv(OUT / f"types{suffix}.csv")
        if k == TYPES:
            names = box.drop_duplicates("player_id").set_index("player_id").player
            listing = labels.to_frame().join(names).sort_values(["type", "player"])
            listing.to_csv(OUT / "players.csv")
        summary[f"leads_k{k}"] = leads(table)
        summary[f"max_abs_t_fills_k{k}"] = round(
            float(table[(table.measure == "fills") & (table.type > 0)].t.abs().max()), 2
        )
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", "utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
