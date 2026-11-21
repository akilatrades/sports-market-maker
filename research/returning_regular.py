"""A candidate input for the NBA stat model: stand-ins when a regular returns.

RESEARCH_LOG.md, 2026-11-21, "a returning regular and his stand-ins". The
production model is too high on players who filled in for an absent regular,
in the game he comes back. This file holds a research-only candidate that
adds one input (two in variant 3) to the production features, and the
walk-forward test written down before it was built. Nothing here is used by
the projections job or the bots.

The input, for a player whose team has a regular returning tonight (15+
weighted minutes, missed his team's previous game)::

    revert = min(0, log((prior + 1) / (recent + 1)))

``recent`` is his average minutes over the team games the returning regular
missed (the longest such absence, at most MAX_STRETCH games) and ``prior`` is
his weighted minutes going into that stretch. It is 0 for everyone else. Like
every production feature it uses only games before the one predicted.

    python -m research.returning_regular design     # 2022-23 to 2024-25, 3 variants
    python -m research.returning_regular confirm 1  # 2025-26 and 2026-27, once
    python -m research.returning_regular pooled 1   # the five seasons together

``--predictions DIR`` keeps each stage's row-by-row predictions there (they
are large and are not committed); ``pooled`` reads them back.
"""

import argparse
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.stats import clustered_mean_t
from markets.nba.evaluate import FIRST_TRAIN_SEASON, log_loss, month_of
from markets.nba.features import (
    REGULAR_MINUTES,
    build_features,
    model_rows,
    player_history,
)
from markets.nba.marginals import STATS, StatModel

OUT = Path("outputs/research/returning_regular")
DESIGN_SEASONS = [2023, 2024, 2025]
CONFIRM_SEASONS = [2026, 2027]
MAX_STRETCH = 10  # team games looked back over, at most
# The three variants written down before the test; no others are tried.
VARIANTS = {
    1: {"min_missed": 1, "columns": ["revert"]},
    2: {"min_missed": 3, "columns": ["revert"]},
    3: {"min_missed": 1, "columns": ["revert_same", "revert_other"]},
}
# The stand-in definition the bias was measured with, fixed before looking.
RETURN_MISSED = 3  # the regular missed at least this many team games in a row
RETURN_MINUTES = 24.0  # and averaged this many minutes over his 10 games before
STAND_IN_GAIN = 5.0  # a stand-in played this many more minutes while he was out


def revert_inputs(rows, players, min_missed=1):
    """``revert``, ``revert_same`` and ``revert_other`` for every row of ``rows``.

    ``rows`` is build_features' output (one row per player-game, with
    team_game, games_missed, ew_minutes, played); ``players`` the box scores
    it was built from.
    """
    out = pd.DataFrame(
        0.0, index=rows.index, columns=["revert", "revert_same", "revert_other"]
    )
    back = rows[
        rows.played
        & (rows.games_missed >= min_missed)
        & (rows.ew_minutes >= REGULAR_MINUTES)
    ]
    if back.empty:
        return out
    keys = ["game_id", "team"]
    stretch = back.groupby(keys).games_missed.max().clip(upper=MAX_STRETCH)
    groups = back.groupby(keys).position.agg(set)
    target = rows[["game_id", "team", "season", "player_id", "team_game", "position"]]
    target = target.join(stretch.rename("stretch"), on=keys)
    target = target.join(groups.rename("back_groups"), on=keys)
    target = target[target.stretch.notna() & rows.played].copy()
    # A season's first games cannot look back before the season started.
    target["stretch"] = np.minimum(target.stretch, target.team_game).astype(int)
    target = target[target.stretch >= 1]
    if target.empty:
        return out

    # Minutes each player actually played, by his team's game number.
    actual = rows[(~rows.did_not_play) & (rows.minutes > 0)]
    actual = actual[["team", "season", "player_id", "team_game", "minutes"]]
    recent = pd.Series(np.nan, index=target.index)
    for (team, season), group in target.groupby(["team", "season"]):
        played = actual[(actual.team == team) & (actual.season == season)]
        table = played.pivot_table(
            index="player_id", columns="team_game", values="minutes", aggfunc="first"
        )
        if table.empty:
            continue
        last = int(max(table.columns.max(), group.team_game.max()))
        table = table.reindex(columns=range(last + 1))
        total = np.nancumsum(table.to_numpy(float), axis=1)
        count = np.cumsum(table.notna().to_numpy(), axis=1)
        total = np.concatenate([np.zeros((len(table), 1)), total], axis=1)
        count = np.concatenate([np.zeros((len(table), 1)), count], axis=1)
        row_of = {pid: i for i, pid in enumerate(table.index)}
        who = group.player_id.map(row_of)
        known = who.notna().to_numpy()
        i = who[known].astype(int).to_numpy()
        end = group.team_game[known].to_numpy(int)  # games 0..end-1 are before
        start = end - group.stretch[known].to_numpy(int)
        games = count[i, end] - count[i, start]
        minutes = total[i, end] - total[i, start]
        with np.errstate(invalid="ignore", divide="ignore"):
            recent.loc[group.index[known]] = np.where(
                games > 0, minutes / games, np.nan
            )
    target["recent"] = recent

    # His weighted minutes going into the stretch: history strictly before
    # the team's first game of it.
    tips = rows.drop_duplicates(["team", "season", "team_game"])
    tips = tips.set_index(["team", "season", "team_game"]).tip_utc
    first = pd.MultiIndex.from_arrays(
        [target.team, target.season, target.team_game - target.stretch]
    )
    target["start_tip"] = tips.reindex(first).to_numpy()
    target = target[target.start_tip.notna() & target.recent.notna()]
    if target.empty:
        return out
    target["start_tip"] = pd.to_datetime(target.start_tip, utc=True)
    history = player_history(players)[["player_id", "tip_utc", "ew_minutes"]]
    history = history.rename(columns={"tip_utc": "start_tip", "ew_minutes": "prior"})
    history["start_tip"] = history.start_tip.astype(target.start_tip.dtype)
    merged = pd.merge_asof(
        target.reset_index().sort_values("start_tip"),
        history.sort_values("start_tip"),
        on="start_tip",
        by="player_id",
        allow_exact_matches=False,
    ).set_index("index")
    merged = merged[merged.prior.notna()]
    revert = np.minimum(0.0, np.log((merged.prior + 1) / (merged.recent + 1)))
    same = np.array(
        [
            position in groups_
            for position, groups_ in zip(merged.position, merged.back_groups)
        ]
    )
    out.loc[merged.index, "revert"] = revert
    out.loc[merged.index, "revert_same"] = np.where(same, revert, 0.0)
    out.loc[merged.index, "revert_other"] = np.where(same, 0.0, revert)
    return out


def candidate_spec(spec, columns):
    """The production spec with the extra input(s) appended to its features."""
    base = spec.features

    def features(rows):
        return np.column_stack(
            [base(rows)] + [rows[c].to_numpy(float) for c in columns]
        )

    return replace(spec, features=features, feature_names=spec.feature_names + columns)


def stand_ins(players, seasons):
    """(game_id, player_id) of stand-ins in the game a regular returns."""
    p = players[players.season.isin(seasons)].copy()
    p["was_in"] = (~p.did_not_play.fillna(False)) & (p.minutes.fillna(0) > 0)
    team_games = p.drop_duplicates(["season", "team", "game_id"]).sort_values("tip_utc")
    team_games["n"] = team_games.groupby(["season", "team"]).cumcount()
    p = p.merge(
        team_games[["season", "team", "game_id", "n"]], on=["season", "team", "game_id"]
    )
    played = p[p.was_in].sort_values("tip_utc")
    minutes = {
        key: group.set_index("n").minutes
        for key, group in played.groupby(["season", "team", "player_id"])
    }
    rosters = {}
    for season, team, player in minutes:
        rosters.setdefault((season, team), []).append(player)
    found = []
    for (season, team, regular), series in minutes.items():
        ns, mins = series.index.to_numpy(), series.to_numpy()
        for i in range(5, len(ns)):
            if ns[i] - ns[i - 1] - 1 < RETURN_MISSED:
                continue
            if mins[max(0, i - 10) : i].mean() < RETURN_MINUTES:
                continue
            back, first = ns[i], ns[i - 1] + 1
            for player in rosters[(season, team)]:
                his = minutes[(season, team, player)]
                if player == regular or back not in his.index:
                    continue
                during = his[(his.index >= first) & (his.index < back)]
                before = his[his.index < first].tail(10)
                if len(during) < 2 or len(before) < 3:
                    continue
                if during.mean() - before.mean() >= STAND_IN_GAIN:
                    found.append((season, team, back, player))
    flags = pd.DataFrame(found, columns=["season", "team", "n", "player_id"])
    flags = flags.drop_duplicates().merge(
        team_games[["season", "team", "n", "game_id"]], on=["season", "team", "n"]
    )
    return flags[["game_id", "player_id"]]


def walk(rows, seasons, variants):
    """Production and candidate predictions, month by month, as evaluate.py does.

    One row per player-game and stat: the actual, each model's expected value
    and its log loss summed over the stat's standard lines.
    """
    rows = rows[rows.season >= FIRST_TRAIN_SEASON].copy()
    rows["month"] = month_of(rows)
    records = []
    for season in seasons:
        for month in sorted(rows.loc[rows.season == season, "month"].unique()):
            test = rows[(rows.season == season) & (rows.month == month)]
            train = rows[rows.month < month]
            for name, spec in STATS.items():
                y = test[name].to_numpy(float)
                frame = {
                    "season": test.season.to_numpy(),
                    "game_id": test.game_id.to_numpy(),
                    "player_id": test.player_id.to_numpy(),
                    "stat": name,
                    "actual": y,
                }
                specs = {"production": spec}
                for number in variants:
                    specs[f"v{number}"] = candidate_spec(
                        spec, VARIANTS[number]["columns"]
                    )
                for label, model_spec in specs.items():
                    fit_rows, score_rows = train, test
                    if label != "production":
                        fit_rows = _with(train, rows, int(label[1:]))
                        score_rows = _with(test, rows, int(label[1:]))
                    model = StatModel(model_spec).fit(fit_rows)
                    mean = model.mean(score_rows)
                    loss = np.zeros(len(test))
                    for line in spec.lines:
                        over = (y > line).astype(float)
                        loss += log_loss(over, model.prob_over(score_rows, line, mean))
                    frame[f"mean_{label}"] = mean
                    frame[f"loss_{label}"] = loss
                records.append(pd.DataFrame(frame))
    return pd.concat(records, ignore_index=True)


def _with(part, rows, number):
    """``part`` with the variant's input columns taken from ``rows``."""
    columns = VARIANTS[number]["columns"]
    return part.assign(**{c: rows.loc[part.index, f"v{number}_{c}"] for c in columns})


def prepare(players, games):
    """Model rows with every variant's inputs attached as v<number>_<column>."""
    built = build_features(players, games)
    for number, variant in VARIANTS.items():
        inputs = revert_inputs(built, players, variant["min_missed"])
        for column in variant["columns"]:
            built[f"v{number}_{column}"] = inputs[column]
    return model_rows(built)


def score(results, flags, label):
    """Stand-in bias and accuracy, everyone-else bias and overall log loss."""
    keys = pd.MultiIndex.from_frame(results[["game_id", "player_id"]])
    stand_in = keys.isin(pd.MultiIndex.from_frame(flags))
    out = {}
    for stat, group in results.groupby("stat"):
        mine = group[stand_in[group.index]]
        rest = group[~stand_in[group.index]]
        row = {
            "stand_in_rows": len(mine),
            "stand_in_games": int(mine.game_id.nunique()),
        }
        for model in ("production", label):
            mean = mine[f"mean_{model}"]
            miss, t = clustered_mean_t(
                (mine.actual - mean).to_numpy(), mine.game_id.to_numpy()
            )
            row[model] = {
                "stand_in_ratio": float(mine.actual.sum() / mean.sum()),
                "stand_in_miss": float(miss),
                "stand_in_t": float(t),
                "stand_in_mse": float(((mine.actual - mean) ** 2).mean()),
                "rest_ratio": float(rest.actual.sum() / rest[f"mean_{model}"].sum()),
                "log_loss": float(group[f"loss_{model}"].mean()),
            }
        gain = (mine.actual - mine[f"mean_{label}"]) ** 2 - (
            mine.actual - mine.mean_production
        ) ** 2
        change, t = clustered_mean_t(gain.to_numpy(), mine.game_id.to_numpy())
        row["mse_change"], row["mse_change_t"] = float(change), float(t)
        out[stat] = row
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("stage", choices=["design", "confirm", "pooled"])
    parser.add_argument("variant", nargs="?", type=int, choices=sorted(VARIANTS))
    parser.add_argument("--players", default="data/player_games.parquet")
    parser.add_argument("--games", default="data/games.parquet")
    parser.add_argument("--until", default="2026-11-21T12:00:00Z")
    parser.add_argument("--predictions", help="folder for row-by-row predictions")
    args = parser.parse_args()
    if (args.stage == "design") == (args.variant is not None):
        parser.error("design takes no variant; confirm and pooled take the chosen one")

    players = pd.read_parquet(args.players)
    players = players[players.tip_utc < pd.Timestamp(args.until)]
    OUT.mkdir(parents=True, exist_ok=True)
    if args.stage == "pooled":
        if not args.predictions:
            parser.error("pooled needs --predictions")
        folder, label = Path(args.predictions), f"v{args.variant}"
        keep = ["season", "game_id", "player_id", "stat", "actual"]
        keep += [
            f"{kind}_{model}"
            for kind in ("mean", "loss")
            for model in ("production", label)
        ]
        parts = [
            pd.read_parquet(folder / f"{name}.parquet")[keep]
            for name in ("design", f"confirm_{label}")
        ]
        results = pd.concat(parts, ignore_index=True)
        seasons = DESIGN_SEASONS + CONFIRM_SEASONS
        summary = {
            "stage": "pooled",
            "seasons": seasons,
            "box_scores_until": args.until,
            "player_game_stats": len(results),
            "variants": {label: score(results, stand_ins(players, seasons), label)},
        }
        (OUT / f"pooled_{label}.json").write_text(
            json.dumps(summary, indent=1) + "\n", "utf-8"
        )
        print(json.dumps(summary, indent=1))
        return

    games = pd.read_parquet(args.games)
    rows = prepare(players, games)
    seasons = DESIGN_SEASONS if args.stage == "design" else CONFIRM_SEASONS
    variants = sorted(VARIANTS) if args.stage == "design" else [args.variant]
    results = walk(rows, seasons, variants)
    flags = stand_ins(players, seasons)
    summary = {
        "stage": args.stage,
        "seasons": seasons,
        "box_scores_until": args.until,
        "player_game_stats": len(results),
        "variants": {f"v{n}": score(results, flags, f"v{n}") for n in variants},
    }
    name = "design" if args.stage == "design" else f"confirm_v{args.variant}"
    (OUT / f"{name}.json").write_text(json.dumps(summary, indent=1) + "\n", "utf-8")
    if args.predictions:
        Path(args.predictions).mkdir(parents=True, exist_ok=True)
        results.to_parquet(Path(args.predictions) / f"{name}.parquet")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
