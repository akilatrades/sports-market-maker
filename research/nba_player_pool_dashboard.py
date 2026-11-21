"""Build the NBA player-pool page: research/nba_player_pool_dashboard.html.

A read-only research page. It places no orders and reads no account. Every
number comes from public files:

- box scores (data/player_games.parquet, written by live.fetch_nba_data);
- the stat model's projections for today's games with Kalshi's quotes
  (outputs/projections/latest.csv, rewritten by scheduled jobs; on game
  days it has changed about five times, from early afternoon to late
  evening US time);
- the sportsbook consensus for the same players (outputs/books/nba_latest.csv,
  which has changed three or four times a day).

Players tab: season averages and a *baseline* for each player's next game.
The baseline is half his recent form and half his per-minute rates times his
expected minutes, all taken from the stat model's own features
(markets/nba/features.py). It knows nothing about the opponent, the betting
line or who is out; the stat model on the props tab does.

Props tab: for each Kalshi prop on today's games, three probabilities side
by side: the stat model, the sportsbooks and Kalshi's own bid and ask. A
sportsbook price is shown only where the books quote Kalshi's exact line. No
price on the page is simulated. A gap between two of them is a
disagreement, not a profit.

The page keeps itself current when it is open on the project site. It
re-reads three small public files and prefers them to the copy built in:

- outputs/player_pool/latest.json: the Players tab, rewritten by the
  player-pool workflow when new box scores arrive (``--data-only`` below);
- the two price files above, for the props tab;
- Kalshi's current bid and ask, published every few minutes on game days
  by research/player_pool_quotes.py.

    python -m live.fetch_nba_data
    python -m research.nba_player_pool_dashboard              # page and data
    python -m research.nba_player_pool_dashboard --data-only  # data file only
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from markets.nba.dead_ticket import kalshi_team
from markets.nba.features import (
    SHRINK_MINUTES,
    STATS,
    played_rows,
    player_history,
    position_rates,
)

HERE = Path(__file__).parent
TEMPLATE = HERE / "nba_player_pool_dashboard.template.html"
PAGE = HERE / "nba_player_pool_dashboard.html"
DATA = Path("outputs/player_pool/latest.json")  # the Players tab, read live
PLACEHOLDER = "/*__PAYLOAD__*/null"

BLEND = 0.5  # weight on per-minute rates x expected minutes; the rest is form
MIN_GAMES_FOR_CHECK = 5  # a season average needs a few games to mean much
# Value index: weights on z-scores of the baseline and of true shooting.
VALUE_WEIGHTS = {
    "points": 0.39,
    "rebounds": 0.17,
    "assists": 0.17,
    "threes": 0.10,
    "ts": 0.17,
}
VALUE_MINUTES = 15.0  # z-scores are taken over players projected this much
REPLACEMENT_RANK = 150  # value is measured against the player at this rank
TS_SHRINK_ATTEMPTS = 120.0  # true-shooting attempts of league-average shooting
SWING_LEVELS = (0, 5, 10, 15, 20, 25, 100)  # baseline points, for the +/- column
SLATE_COLUMNS = [
    "tip_utc",
    "ticker",
    "event_ticker",
    "player",
    "player_id",
    "player_key",
    "team",
    "stat",
    "line",
    "model_mean",
    "p_model",
    "yes_bid_dollars",
    "yes_ask_dollars",
    "injury_status",
]
BOOK_COLUMNS = [
    "player_key",
    "stat",
    "line",
    "away",
    "home",
    "p_book",
    "book_n",
    "updated_utc",
    "commence_utc",
]
LINE_KEY = ["player_key", "stat", "line"]


def season_label(season):
    return f"{season - 1}-{str(season)[2:]}"


def regular(players, season):
    rows = players[(players.season == season) & (players.season_type == "regular")]
    return played_rows(rows)


def season_table(players, season):
    """One row per player: this season's per-game numbers from box scores.

    Usage is an estimate of the share of his team's possessions a player used
    while he was on the floor (shots, free-throw trips and turnovers). True
    shooting is points per shooting possession, halved.
    """
    p = regular(players, season).sort_values("tip_utc").copy()
    p["used"] = p.fga + 0.44 * p.fta + p.tov
    team = p.groupby(["game_id", "team"])[["used", "minutes"]].transform("sum")
    # The team's possessions while he was on the floor (five players share
    # the team's minutes, so his minutes cover minutes / (team minutes / 5)).
    p["team_used"] = team.used * p.minutes / (team.minutes / 5.0)
    p["shots"] = p.fga + 0.44 * p.fta
    grouped = p.groupby("player_id")
    out = grouped.agg(
        player=("player", "last"),
        team=("team", "last"),
        position=("position", "last"),
        games=("minutes", "size"),
        minutes=("minutes", "mean"),
        points=("points", "mean"),
        rebounds=("rebounds", "mean"),
        assists=("assists", "mean"),
        threes=("threes", "mean"),
        used=("used", "sum"),
        team_used=("team_used", "sum"),
        total_points=("points", "sum"),
        shots=("shots", "sum"),
    )
    out["team"] = out.team.map(kalshi_team)
    out["usage"] = out.used / out.team_used.where(out.team_used > 0)
    out["ts"] = out.total_points / (2 * out.shots.where(out.shots > 0))
    return out.drop(columns=["used", "team_used"])


def _with_rates(rows, players):
    """Per-minute rates as the stat model builds them: the last 30 games,
    pulled toward the position's rate from earlier seasons."""
    rates = position_rates(players)
    rows = rows.merge(rates, on=["position", "season"], how="left")
    latest = rates.sort_values("season").groupby("position").last()
    minutes = rows.sum_minutes.fillna(0) + SHRINK_MINUTES
    for stat in STATS:
        mu = rows[f"mu_{stat}"].fillna(rows.position.map(latest[f"mu_{stat}"]))
        numer = rows[f"sum_{stat}"].fillna(0) + SHRINK_MINUTES * mu
        rows[f"rate_{stat}"] = numer / minutes
    return rows


def baseline(state):
    """Add the next-game baseline (proj_*) to rows that carry ew_* and rate_*."""
    out = state.copy()
    out["proj_minutes"] = out.ew_minutes
    for stat in STATS:
        by_rate = out[f"rate_{stat}"] * out.ew_minutes
        out[f"proj_{stat}"] = BLEND * by_rate + (1 - BLEND) * out[f"ew_{stat}"]
    return out


def current_state(players, season):
    """Each player's form and rates after his latest game, for his next one."""
    history = player_history(players)
    latest = history.sort_values("tip_utc").groupby("player_id").tail(1).copy()
    latest["season"] = season  # the position prior for the season being played
    return baseline(_with_rates(latest, players)).set_index("player_id")


def pregame_state(players):
    """Every played game with the form and rates known *before* it (empty
    for a player's first game)."""
    history = player_history(players)
    keep = [c for c in history.columns if c not in {"season", "position"}]
    games = played_rows(players).sort_values("tip_utc")
    rows = pd.merge_asof(
        games,
        history[keep],
        on="tip_utc",
        by="player_id",
        allow_exact_matches=False,
    )
    return baseline(_with_rates(rows, players))


def check_baseline(players, season):
    """How the baseline did over one finished season, against the plain
    season average to date, and the one-game swing in points by level.

    The 50/50 blend was chosen on 2025-26, so for that season this
    comparison is in-sample.
    """
    rows = pregame_state(players)
    rows = rows[(rows.season == season) & (rows.season_type == "regular")].copy()
    rows = rows.sort_values("tip_utc")
    grouped = rows.groupby("player_id")
    rows["games_before"] = grouped.cumcount()
    for stat in STATS:
        total = grouped[stat].cumsum() - rows[stat]
        rows[f"avg_{stat}"] = total / rows.games_before.where(rows.games_before > 0)
    rows = rows[rows.games_before >= MIN_GAMES_FOR_CHECK]
    out = {"season": season_label(season), "player_games": int(len(rows))}
    for stat in STATS:
        out[f"miss_baseline_{stat}"] = float(
            (rows[stat] - rows[f"proj_{stat}"]).abs().mean()
        )
        out[f"miss_average_{stat}"] = float(
            (rows[stat] - rows[f"avg_{stat}"]).abs().mean()
        )
    level = pd.cut(rows.proj_points, SWING_LEVELS, right=False)
    error = rows.points - rows.proj_points
    swing = pd.DataFrame({"level": rows.proj_points, "error": error}).groupby(
        level, observed=True
    )
    curve = swing.agg(
        level=("level", "mean"), swing=("error", "std"), n=("error", "size")
    )
    curve = curve[curve.n >= 30]
    out["swing_curve"] = [
        [float(a), float(b)] for a, b in zip(curve.level, curve.swing, strict=True)
    ]
    return out


def points_swing(projected, curve):
    """Typical one-game swing (standard deviation) in points at this level.

    Read off last season's curve; above its highest level the swing grows
    with the square root of the projection, as counts do.
    """
    if not curve:
        return pd.Series(np.nan, index=projected.index)
    levels, swings = zip(*curve, strict=True)
    swing = np.interp(projected, levels, swings)
    beyond = np.sqrt(np.maximum(projected / levels[-1], 1.0))
    return pd.Series(swing * beyond, index=projected.index)


def value_index(table):
    """A box-score index: weighted z-scores of the baseline and of true
    shooting, minus the same score for the REPLACEMENT_RANK-th player.
    It is not a plus-minus model and says nothing about defence."""
    attempts = table.shots.fillna(0)
    league = table.total_points.sum() / (2 * table.shots.sum())
    made = table.total_points.fillna(0) + TS_SHRINK_ATTEMPTS * 2 * league
    shrunk_ts = made / (2 * (attempts + TS_SHRINK_ATTEMPTS))
    columns = {stat: table[f"proj_{stat}"] for stat in STATS}
    columns["ts"] = shrunk_ts
    base = table.proj_minutes >= VALUE_MINUTES
    score = pd.Series(0.0, index=table.index)
    for name, weight in VALUE_WEIGHTS.items():
        values = columns[name]
        spread = values[base].std()
        if base.sum() < 2 or not spread > 0:
            continue
        score += weight * (values - values[base].mean()) / spread
    ranked = score[base].sort_values(ascending=False)
    if ranked.empty:
        return score * np.nan
    replacement = ranked.iloc[min(REPLACEMENT_RANK, len(ranked)) - 1]
    return score - replacement


def player_rows(players, season, curve):
    table = season_table(players, season)
    state = current_state(players, season)
    proj = [c for c in state.columns if c.startswith("proj_")]
    table = table.join(state[proj], how="left")
    table["swing"] = points_swing(table.proj_points, curve)
    table["value"] = value_index(table)
    table = table.drop(columns=["total_points", "shots"])
    table = table.sort_values("value", ascending=False, na_position="last")
    return table.reset_index()


def _table(frame, columns):
    frame = frame.reindex(columns=columns)
    frame = frame.astype(object).where(frame.notna(), None)
    return {"columns": columns, "rows": frame.to_numpy().tolist()}


def slate_snapshot(projections):
    """The columns the props tab needs, as the page also reads them live."""
    if projections is None or projections.empty:
        return {"snapshot_utc": None, **_table(pd.DataFrame(), SLATE_COLUMNS)}
    snapshot = projections.snapshot_utc.dropna()
    return {
        "snapshot_utc": None if snapshot.empty else str(snapshot.max()),
        **_table(projections, SLATE_COLUMNS),
    }


def slate_file(projections):
    """``slate_snapshot`` as strict JSON values, for a file of its own."""
    return _clean(slate_snapshot(projections))


def book_lines(books, projections):
    """Sportsbook lines that sit exactly on one of today's Kalshi lines.

    The page does the matching itself (it also re-reads both files live);
    this only leaves out the lines it could never match.
    """
    if books is None or books.empty or projections is None or projections.empty:
        return _table(pd.DataFrame(), BOOK_COLUMNS)
    wanted = projections[LINE_KEY].drop_duplicates()
    return _table(books.merge(wanted, on=LINE_KEY, how="inner"), BOOK_COLUMNS)


def _clean(value):
    """JSON has no NaN; numbers are rounded to keep the page small."""
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return round(float(value), 4) if np.isfinite(value) else None
    return value


def build_payload(players, projections, books=None):
    """Everything the page shows. The same inputs give the same payload, so
    the data file changes only when the box scores do."""
    season = int(players.season.max())
    check = check_baseline(players, season - 1)
    table = player_rows(players, season, check["swing_curve"])
    through = regular(players, season).tip_utc.max()
    payload = {
        "meta": {
            "season": season_label(season),
            "box_scores_through_utc": pd.Timestamp(through).isoformat(),
            "blend": BLEND,
            "shrink_minutes": SHRINK_MINUTES,
            "value_weights": VALUE_WEIGHTS,
            "value_minutes": VALUE_MINUTES,
            "replacement_rank": REPLACEMENT_RANK,
            "check": check,
        },
        "players": table.to_dict("records"),
        "slate": slate_snapshot(projections),
        "books": book_lines(books, projections),
    }
    return _clean(payload)


def player_file(payload):
    """The part of the payload behind the Players tab, as its own file."""
    return {"meta": payload["meta"], "players": payload["players"]}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    path.write_text(text + "\n", "utf-8")


def render(payload, template):
    if PLACEHOLDER not in template:
        raise ValueError("the template has no payload placeholder")
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    # "</script>" inside a name must not close the script tag.
    return template.replace(PLACEHOLDER, text.replace("</", "<\\/"))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--players", default="data/player_games.parquet")
    parser.add_argument("--projections", default="outputs/projections/latest.csv")
    parser.add_argument("--books", default="outputs/books/nba_latest.csv")
    parser.add_argument("--out", default=str(PAGE))
    parser.add_argument("--data", default=str(DATA))
    parser.add_argument(
        "--data-only",
        action="store_true",
        help="write the Players-tab data file and leave the page alone",
    )
    args = parser.parse_args()

    players = pd.read_parquet(args.players)
    projections, books = (
        pd.read_csv(path) if Path(path).exists() else None
        for path in (args.projections, args.books)
    )
    payload = build_payload(players, projections, books)
    write_json(args.data, player_file(payload))
    if not args.data_only:
        page = render(payload, TEMPLATE.read_text("utf-8"))
        Path(args.out).write_text(page, "utf-8")
    meta = payload["meta"]
    print(
        f"{len(payload['players'])} players, {len(payload['slate']['rows'])} props, "
        f"{len(payload['books']['rows'])} matching sportsbook lines, "
        f"box scores through {meta['box_scores_through_utc']}"
    )
    print(f"baseline check: {json.dumps(meta['check'])}")


if __name__ == "__main__":
    main()
