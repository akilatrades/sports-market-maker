"""Esports team ratings against Kalshi's pre-match price (RESEARCH_LOG.md,
2026-11-24, plan written before any data). Research only: no orders.

    python -m research.esports_ratings fetch   # network (GitHub's runners)
    python -m research.esports_ratings score   # no network

``fetch`` reads every settled market in Kalshi's esports match series from
the public API: team, event, start, result, and the last hourly candle at
least 30 minutes before the start. One market per match. Resumable; writes
``data/esports/matches.csv.gz`` (Kalshi public data).

``score`` rates teams with Elo (K = 32, start 1500, per game title; fixed
before any data), then compares with Kalshi's midpoint and scores the plan's
rule. Writes ``outputs/esports_ratings/summary.json``.
"""

import argparse
import json
import math
import re
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.stats import clustered_mean_t

DATA = Path("data/esports/matches.csv.gz")
OUT = Path("outputs/esports_ratings")
SERIES = {
    "KXCS2GAME": "cs2",
    "KXCSGOGAME": "cs2",
    "KXDOTA2GAME": "dota2",
    "KXLOLGAME": "lol",
    "KXOWGAME": "ow",
    "KXR6GAME": "r6",
    "KXCODGAME": "cod",
    "KXVALORANTGAME": "valorant",
}
COLUMNS = [
    "series", "title", "event_ticker", "ticker", "team", "opponent", "start_utc",
    "result", "yes_bid", "yes_ask", "last_price", "candle_utc",
]  # fmt: skip

# --- the plan, fixed before any data ------------------------------------------
K, START_RATING, SCALE = 32.0, 1500.0, 400.0
MIN_HISTORY = 5  # a team's first matches are rated but not scored
QUOTE_LEAD_MINUTES = 30
PRICE_RANGE = (0.02, 0.98)
EDGE = 0.05
PASS_T, PASS_BETS = 2.0, 200
EXPLORE_K, EXPLORE_EDGES = (16.0, 48.0), (0.03, 0.08)
TAKER_FEE_RATE = 0.07
RESULT_DELAY_HOURS = 4  # a result is used only this long after its start
TIME_BUDGET_SECONDS = 50 * 60


# --- names ----------------------------------------------------------------------


def norm(name):
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore")
    text = re.sub(r"[^a-z0-9 ]", " ", text.decode().lower())
    return " ".join(text.split())


# Kalshi words each esports market "<Team> wins"; both teams appear only in
# the rules: "If X wins the <event>: A vs. B <game> match originally ...".
RULES_TEAMS = re.compile(r":\s*(.+?)\s+vs\.?\s+(.+?)\s+match\b", re.I)


def teams_of(market):
    """(team this market pays on, opponent), or None when they cannot be read."""
    team_raw = str(market.get("yes_sub_title") or "").strip()
    team = norm(team_raw)
    if not team:
        return None
    found = RULES_TEAMS.search(str(market.get("rules_primary") or ""))
    if found:
        first, second = found.group(1).strip(), found.group(2).strip()
    else:  # older wording: "A vs B" in the title
        title = re.sub(
            r"(?i)^will\s+|\s+win.*$|\?$", "", str(market.get("title") or "")
        )
        parts = re.split(r"(?i)\s+(?:vs\.?|v\.?|versus)\s+", title)
        if len(parts) != 2:
            return None
        first, second = parts
    a, b = norm(first), norm(second)
    # The second name runs into the game's name ("PRIVATE CS2"), so match the
    # team by the start of each side.
    if a == team or (a.startswith(team) and not b.startswith(team)):
        opponent = _without_game(second)  # "PRIVATE CS2" -> "private"
    elif b == team or b.startswith(team):
        opponent = a
    else:
        return None
    return (team, opponent) if opponent and opponent != team else None


GAME_NAMES = (
    "counter strike 2", "counter strike", "cs2", "cs go", "csgo", "dota 2", "dota",
    "league of legends", "lol", "overwatch 2", "overwatch", "rainbow six siege",
    "rainbow six", "r6 siege", "r6", "call of duty", "cod", "valorant",
)  # fmt: skip


def _without_game(name):
    text = norm(name)
    for game in sorted(GAME_NAMES, key=len, reverse=True):
        if text.endswith(" " + game):
            return text[: -len(game) - 1].strip()
    return text


def start_of(market):
    for key in ("occurrence_datetime", "expected_expiration_time", "close_time"):
        stamp = pd.to_datetime(market.get(key), utc=True, errors="coerce")
        if pd.notna(stamp):
            return stamp, key
    return None, None


# --- fetch (network) ------------------------------------------------------------


def fetch(path=DATA, clock=time.monotonic, api=None):
    """Add newly settled matches to ``path``. Returns counts."""
    if api is None:
        from kalshi import api
    began = clock()
    try:
        have = pd.read_csv(path)
    except (OSError, ValueError):
        have = pd.DataFrame(columns=COLUMNS)
    seen = set(have.event_ticker)
    rows, counts = [], {"events_new": 0, "no_teams": 0, "no_candle": 0}
    for series, title in SERIES.items():
        markets = []
        for historical in (True, False):
            try:
                markets += api.fetch_markets(
                    series, status="settled", historical=historical
                )
            except Exception:
                continue
        by_event = {}
        for m in markets:
            if m.get("result") in ("yes", "no") and m.get("event_ticker") not in seen:
                by_event.setdefault(m["event_ticker"], []).append(m)
        for event, ms in sorted(by_event.items()):
            if clock() - began > TIME_BUDGET_SECONDS:
                counts["note"] = "out of time; run again"
                break
            m = sorted(ms, key=lambda x: x["ticker"])[0]  # one market per match
            pair = teams_of(m)
            start, _ = start_of(m)
            if pair is None or start is None:
                counts["no_teams"] += 1
                continue
            end = int((start - pd.Timedelta(minutes=QUOTE_LEAD_MINUTES)).timestamp())
            candles = []
            for historical in (True, False):
                try:
                    candles = api.candles(
                        m["ticker"], end - 48 * 3600, end, historical=historical
                    )
                except Exception:
                    candles = []
                if candles:
                    break
            last = candles[-1] if candles else {}
            if not candles:
                counts["no_candle"] += 1
            rows.append(
                {
                    "series": series, "title": title, "event_ticker": event,
                    "ticker": m["ticker"], "team": pair[0], "opponent": pair[1],
                    "start_utc": start.isoformat(), "result": m["result"],
                    "yes_bid": last.get("yes_bid"), "yes_ask": last.get("yes_ask"),
                    "last_price": last.get("price"),
                    "candle_utc": pd.Timestamp(last["end_ts"], unit="s", tz="UTC").isoformat()
                    if last else "",
                }
            )  # fmt: skip
            counts["events_new"] += 1
    out = pd.concat([have, pd.DataFrame(rows, columns=COLUMNS)], ignore_index=True)
    out = out.drop_duplicates("event_ticker").sort_values("start_utc")
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    counts["events_total"] = int(len(out))
    return counts


# --- ratings ----------------------------------------------------------------------


def elo(matches, k=K):
    """Pre-match Elo chance that ``team`` wins, with both teams' match counts.
    A result changes the ratings only RESULT_DELAY_HOURS after its start, so a
    match is never rated from one that had not finished when it began."""
    m = matches.sort_values("start_utc").reset_index(drop=True)
    starts = pd.to_datetime(m.start_utc, utc=True, format="ISO8601")
    ratings, played, pending = {}, {}, []
    p, n_team, n_opp = [], [], []
    for start, row in zip(starts, m.itertuples(index=False)):
        while pending and pending[0][0] <= start:
            _, a, b, won = pending.pop(0)
            ra, rb = ratings.get(a, START_RATING), ratings.get(b, START_RATING)
            expected = 1 / (1 + 10 ** ((rb - ra) / SCALE))
            ratings[a] = ra + k * (won - expected)
            ratings[b] = rb - k * (won - expected)
            played[a] = played.get(a, 0) + 1
            played[b] = played.get(b, 0) + 1
        a, b = (row.title, row.team), (row.title, row.opponent)
        ra, rb = ratings.get(a, START_RATING), ratings.get(b, START_RATING)
        p.append(1 / (1 + 10 ** ((rb - ra) / SCALE)))
        n_team.append(played.get(a, 0))
        n_opp.append(played.get(b, 0))
        won = 1.0 if row.result == "yes" else 0.0
        pending.append((start + pd.Timedelta(hours=RESULT_DELAY_HOURS), a, b, won))
        pending.sort(key=lambda x: x[0])
    return m.assign(p_elo=p, n_team=n_team, n_opp=n_opp)


def fee(price):
    return np.ceil(100 * TAKER_FEE_RATE * price * (1 - price) - 1e-9) / 100


def scored(matches, k=K):
    """Matches that count: both teams past MIN_HISTORY, a two-sided quote."""
    m = elo(matches, k)
    for c in ("yes_bid", "yes_ask"):
        m[c] = pd.to_numeric(m[c], errors="coerce")
    low, high = PRICE_RANGE
    ok = (
        m.n_team.ge(MIN_HISTORY) & m.n_opp.ge(MIN_HISTORY)
        & m.yes_bid.between(low, high) & m.yes_ask.between(low, high)
        & (m.yes_ask > m.yes_bid)
    )  # fmt: skip
    m = m[ok].copy()
    m["mid"] = (m.yes_bid + m.yes_ask) / 2
    m["y"] = (m.result == "yes").astype(float)
    return m


def rule(frame, edge=EDGE):
    """Buy the side Elo rates ``edge`` above its ask, at the ask, taker fee."""
    yes_ask, no_ask = frame.yes_ask, 1 - frame.yes_bid
    buy_yes = frame.p_elo - yes_ask >= edge
    buy_no = (1 - frame.p_elo) - no_ask >= edge
    rows = []
    for r, by, bn, ya, na in zip(
        frame.itertuples(index=False), buy_yes, buy_no, yes_ask, no_ask
    ):
        if by:
            rows.append((r.event_ticker, r.title, r.y - ya - fee(ya)))
        elif bn:
            rows.append((r.event_ticker, r.title, (1 - r.y) - na - fee(na)))
    return pd.DataFrame(rows, columns=["event", "title", "pnl"])


def logloss(p, y):
    p = np.clip(np.asarray(p, float), 0.01, 0.99)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def summarize(matches):
    import statsmodels.api as sm

    m = scored(matches).sort_values("start_utc")
    out = {"matches_scored": int(len(m)), "by_title": m.title.value_counts().to_dict()}
    if len(m) < 50:
        out["verdict"] = {"passes": False, "reason": "too few matches"}
        return out
    half = m.start_utc.iloc[len(m) // 2]
    first, second = m[m.start_utc < half], m[m.start_utc >= half]

    def lg(p):
        p = np.clip(np.asarray(p, float), 0.01, 0.99)
        return np.log(p / (1 - p))

    def X(f):
        frame = pd.DataFrame({"mid": lg(f.mid), "elo": lg(f.p_elo)}, index=f.index)
        return sm.add_constant(frame, has_constant="add")

    try:
        fit = sm.Logit(first.y, X(first)).fit(disp=0)
        blend = fit.predict(X(second))
        full = sm.Logit(second.y, X(second)).fit(
            disp=0,
            cov_type="cluster",
            cov_kwds={"groups": pd.factorize(second.event_ticker)[0]},
        )
    except (np.linalg.LinAlgError, ValueError) as error:
        out["verdict"] = {"passes": False, "reason": f"regression failed: {error}"}
        return out
    out["second_half"] = {
        "matches": int(len(second)),
        "from": str(half),
        "logloss_mid": round(logloss(second.mid, second.y), 4),
        "logloss_elo": round(logloss(second.p_elo, second.y), 4),
        "logloss_blend": round(logloss(blend, second.y), 4),
        "blend_weights_first_half": {
            k: round(float(v), 3) for k, v in fit.params.items()
        },
        "elo_coefficient": round(float(full.params["elo"]), 3),
        "elo_t": round(float(full.tvalues["elo"]), 2),
    }
    bets = rule(second)
    mean, t = (
        clustered_mean_t(bets.pnl.to_numpy(), bets.event.to_numpy())
        if len(bets) > 1
        else (math.nan, math.nan)
    )
    out["rule"] = {"bets": int(len(bets)), "cents_per_contract": round(100 * mean, 2) if len(bets) else None,
                   "t": round(float(t), 2) if math.isfinite(t) else None,
                   "by_title": bets.groupby("title").pnl.agg(["size", "mean"]).round(3).to_dict("index") if len(bets) else {}}  # fmt: skip
    s = out["second_half"]
    checks = {
        "blend_beats_mid": s["logloss_blend"] < s["logloss_mid"],
        "elo_t": s["elo_t"] >= PASS_T,
        "rule_bets": out["rule"]["bets"] >= PASS_BETS,
        "rule_profit": (out["rule"]["cents_per_contract"] or 0) > 0,
        "rule_t": (out["rule"]["t"] or 0) >= PASS_T,
    }
    out["verdict"] = {"passes": all(checks.values()), **checks}
    explore = {}
    for k in (K, *EXPLORE_K):
        mk = scored(matches, k)
        sk = mk[mk.start_utc >= half]
        for e in (EDGE, *EXPLORE_EDGES):
            b = rule(sk, e)
            if len(b) > 1:
                mm, tt = clustered_mean_t(b.pnl.to_numpy(), b.event.to_numpy())
                explore[f"K{int(k)}_edge{int(100 * e)}"] = {
                    "bets": int(len(b)),
                    "cents": round(100 * mm, 2),
                    "t": round(float(tt), 2),
                }
    out["exploratory"] = explore
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("stage", choices=("fetch", "score"))
    args = parser.parse_args(argv)
    if args.stage == "fetch":
        print(json.dumps(fetch()))
        return 0
    matches = pd.read_csv(DATA)
    summary = {
        "note": "historical, Kalshi public data; rule at the ask (taker), simulated",
        **summarize(matches),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=1, default=str) + "\n", "utf-8"
    )
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
