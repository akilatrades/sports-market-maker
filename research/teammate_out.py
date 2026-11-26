"""Do sportsbooks under-react when a regular is ruled out on game day?
(RESEARCH_LOG.md, 2026-11-26, plan written before any result.)

This season only. A "regular" (5+ of the team's previous 10 games, 24+
minutes) who did not play was "ruled out on game day" when his own props are
in the game's first snapshot 3-30 hours before tip-off and in none of the
snapshots in the last 2 hours. For his teammates' main lines at the close,
the primary measure is mean(over won - closing over chance), game-clustered.

    python -m research.teammate_out

Writes outputs/teammate_out/summary.json (aggregates only; no odds rows).
"""

import glob
import io
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.stats import clustered_mean_t
from markets.nba.kalshi import normalize_name

BOX = Path("data/player_games.parquet")
BOOKS = "outputs/books/nba_2*.csv.gz"
LATEST = "outputs/books/nba_latest.csv"
OUT = Path("outputs/teammate_out")
SEASON = 2027
COLUMNS = ["event_id", "commence_utc", "player_key", "stat", "line", "p_book",
           "book_n", "snapshot_utc", "home", "away"]  # fmt: skip
STATS = ("points", "rebounds", "assists", "threes")
ALIASES = {"carlton carrington": "bub carrington", "herb jones": "herbert jones",
           "ron holland": "ronald holland"}  # fmt: skip
TEAM = {"GSW": "GS", "NYK": "NY", "SAS": "SA", "NOP": "NO", "UTA": "UTAH", "WAS": "WSH"}

# --- the plan, fixed before results ---------------------------------------------
REGULAR_GAMES, REGULAR_OF, REGULAR_MINUTES = 5, 10, 24
OPEN_HOURS = (3, 30)
LATE_HOURS = 2
MIN_BOOKS = 2
BAR = {"points": 0.04, "t": 2.5, "team_games": 30, "control": 0.02}


def key(name):
    """One spelling per player across the two sources: initials joined
    ("a j green" -> "aj green") and a few known nicknames."""
    words, out = str(name).split(), []
    for w in words:
        if (
            len(w) == 1
            and out
            and len(out[-1]) <= 2
            and out[-1].isalpha()
            and out[-1] != ""
        ):
            out[-1] += w
        else:
            out.append(w)
    joined = " ".join(out)
    return ALIASES.get(joined, joined)


def snapshots(ref="origin/main"):
    """Every sportsbook snapshot: the daily files plus each committed
    version of the latest file."""
    frames = [
        pd.read_csv(p, usecols=lambda c: c in COLUMNS) for p in sorted(glob.glob(BOOKS))
    ]
    shas = subprocess.run(
        ["git", "log", ref, "--format=%H", "--", LATEST],
        capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    for sha in shas:
        text = subprocess.run(["git", "show", f"{sha}:{LATEST}"], capture_output=True,
                              text=True).stdout  # fmt: skip
        if text:
            frames.append(
                pd.read_csv(io.StringIO(text), usecols=lambda c: c in COLUMNS)
            )
    s = pd.concat(frames, ignore_index=True)
    s = s[s.stat.isin(STATS)].drop_duplicates(
        ["event_id", "player_key", "stat", "line", "snapshot_utc"]
    )
    s["snap"] = pd.to_datetime(
        s.snapshot_utc, utc=True, format="ISO8601", errors="coerce"
    )
    s["commence"] = pd.to_datetime(
        s.commence_utc, utc=True, format="ISO8601", errors="coerce"
    )
    s["home"] = s.home.replace(TEAM)
    s["player_key"] = s.player_key.map(key)
    return s.dropna(subset=["snap", "commence"])


def box(path=BOX, season=SEASON):
    b = pd.read_parquet(path)
    b = b[(b.season == season) & (b.season_type == "regular")].copy()
    b["tip"] = pd.to_datetime(b.tip_utc, utc=True)
    b["player_key"] = b.player.map(normalize_name).map(key)
    return b


def regulars_out(b):
    """(game_id, team, player_key) of regulars with no minutes in the game."""
    games = b[["game_id", "team", "tip"]].drop_duplicates().sort_values("tip")
    played = b[b.minutes > 0]
    rows = []
    for team, tg in games.groupby("team"):
        ids = tg.game_id.tolist()
        for i, gid in enumerate(ids):
            prior = ids[max(0, i - REGULAR_OF) : i]
            if len(prior) < REGULAR_GAMES:
                continue
            p = played[(played.team == team) & played.game_id.isin(prior)]
            per = p.groupby("player_key").minutes.agg(["size", "mean"])
            regular = per[
                (per["size"] >= REGULAR_GAMES) & (per["mean"] >= REGULAR_MINUTES)
            ]
            now = set(
                played[(played.game_id == gid) & (played.team == team)].player_key
            )
            for key in regular.index:
                if key not in now:
                    rows.append({"game_id": gid, "team": team, "player_key": key})
    return pd.DataFrame(rows, columns=["game_id", "team", "player_key"])


def match_events(s, b):
    """Book event_id -> box game_id, by home team and tip within 3 hours."""
    homes = b[b.home.astype(bool)][["game_id", "team", "tip"]].drop_duplicates()
    ev = s.groupby("event_id").agg(
        home=("home", "first"), commence=("commence", "first")
    )
    m = ev.reset_index().merge(homes, left_on="home", right_on="team")
    m = m[(m.commence - m.tip).abs() <= pd.Timedelta(hours=3)]
    return m.drop_duplicates("event_id").set_index("event_id")[["game_id", "tip"]]


def classify(s, outs, events):
    """For each out regular: same_day, before_day, late_unpriced or unknown."""
    s = s.join(events, on="event_id", how="inner")
    s["hours"] = (s.tip - s.snap).dt.total_seconds() / 3600
    labels = []
    for (gid,), g in s.groupby(["game_id"]):
        open_snaps = g[g.hours.between(*OPEN_HOURS)]
        late = g[g.hours.between(0, LATE_HOURS, inclusive="right")]
        first = (
            open_snaps[open_snaps.snap == open_snaps.snap.min()]
            if len(open_snaps)
            else g.iloc[0:0]
        )
        for o in outs[outs.game_id == gid].itertuples():
            if first.empty or late.empty:
                label = "unknown"
            elif o.player_key in set(late.player_key):
                label = "late_unpriced"
            elif o.player_key in set(first.player_key):
                label = "same_day"
            else:
                label = "before_day"
            labels.append({"game_id": gid, "team": o.team, "player_key": o.player_key,
                           "label": label})  # fmt: skip
    return pd.DataFrame(labels, columns=["game_id", "team", "player_key", "label"]), s


def main_lines(rows):
    """One line per player, stat and game: over price closest to 50%."""
    r = rows[rows.book_n >= MIN_BOOKS].copy()
    r["dist"] = (r.p_book - 0.5).abs()
    return r.sort_values("dist").drop_duplicates(["game_id", "player_key", "stat"])


def graded(s, b):
    """Main lines at the close (last snapshot before tip, within 2 hours),
    joined to the player's team and result."""
    pre = s[s.hours > 0]
    last = pre.groupby("game_id").snap.transform("max")
    close = pre[(pre.snap == last) & (pre.hours <= LATE_HOURS)]
    lines = main_lines(close)
    played = b[b.minutes > 0][["game_id", "player_key", "team", *STATS]]
    lines = lines.merge(played, on=["game_id", "player_key"], how="inner")
    lines["actual"] = lines.apply(lambda r: r[r.stat], axis=1).astype(float)
    lines = lines[lines.actual != lines.line]
    lines["over_won"] = (lines.actual > lines.line).astype(float)
    lines["miss"] = lines.over_won - lines.p_book
    return lines[
        ["game_id", "team", "player_key", "stat", "line", "p_book", "over_won", "miss"]
    ]


def moves(s, labels):
    """Teammates' points main line: open to close, for each group."""
    pre = s[(s.hours > 0) & (s.stat == "points")]
    first = pre[pre.hours.between(*OPEN_HOURS)]
    first = first[first.snap == first.groupby("game_id").snap.transform("min")]
    last = pre[pre.snap == pre.groupby("game_id").snap.transform("max")]
    a, z = main_lines(first), main_lines(last)
    m = a.merge(z, on=["game_id", "player_key"], suffixes=("_open", "_close"))
    m["move"] = m.line_close - m.line_open
    return m[["game_id", "player_key", "move"]]


def measure(part):
    if len(part) < 2:
        return {"lines": int(len(part))}
    mean, t = clustered_mean_t(
        part.miss.to_numpy(), part.game_id.astype(str).to_numpy()
    )
    return {"lines": int(len(part)), "games": int(part.game_id.nunique()),
            "over_won": round(float(part.over_won.mean()), 4),
            "closing_chance": round(float(part.p_book.mean()), 4),
            "miss_points": round(100 * float(mean), 2),
            "t": round(float(t), 2) if np.isfinite(t) else None}  # fmt: skip


def run(s, b):
    outs = regulars_out(b)
    events = match_events(s, b)
    labels, s = classify(s, outs, events)
    lines = graded(s, b)
    team_games = lines[["game_id", "team"]].drop_duplicates()
    tg = team_games.merge(
        labels.groupby(["game_id", "team"]).label.agg(set).reset_index(), how="left"
    )
    tg["label"] = tg.label.apply(lambda x: x if isinstance(x, set) else set())
    tg["group"] = np.select(
        [tg.label.apply(lambda x: "same_day" in x),
         tg.label.apply(lambda x: len(x) > 0 and x <= {"before_day"}),
         tg.label.apply(lambda x: len(x) == 0)],
        ["same_day", "before_day", "control"], "other",
    )  # fmt: skip
    lines = lines.merge(tg[["game_id", "team", "group"]], on=["game_id", "team"])
    lines = lines.merge(labels[["game_id", "player_key"]].assign(out=1), how="left")
    lines = lines[lines.out.isna()]  # never grade the player who was out
    groups = {
        g: measure(lines[lines.group == g])
        for g in ("same_day", "control", "before_day")
    }
    by_stat = {
        st: measure(lines[(lines.group == "same_day") & (lines.stat == st)])
        for st in STATS
    }
    mv = moves(s, labels).merge(
        lines[["game_id", "player_key", "group"]].drop_duplicates()
    )
    move = mv.groupby("group").move.agg(["size", "mean"]).round(3).to_dict("index")
    same, control = groups["same_day"], groups["control"]
    tg_same = int(tg[tg.group == "same_day"].shape[0])
    passed = bool(
        same.get("miss_points") is not None
        and same["miss_points"] >= 100 * BAR["points"]
        and (same.get("t") or 0) >= BAR["t"]
        and tg_same >= BAR["team_games"]
        and abs(control.get("miss_points") or 99) <= 100 * BAR["control"]
    )
    return {
        "note": "This season, sportsbook consensus at the close (last snapshot within "
        "2 hours of tip-off) vs box scores. miss_points = over won minus closing "
        "over chance, game-clustered. Not a forecast.",
        "box_scores_through": str(b.tip.max().date()),
        "out_regulars": labels.label.value_counts().to_dict(),
        "team_games": tg.group.value_counts().to_dict(),
        "groups": groups,
        "same_day_by_stat": by_stat,
        "points_line_move_open_to_close": move,
        "bar": BAR,
        "variants": 5,
        "pass": passed,
    }


def main(argv=None):
    result = run(snapshots(), box())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(
        json.dumps(result, indent=1, default=str) + "\n", "utf-8"
    )
    print(json.dumps(result, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
