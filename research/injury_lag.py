"""Does Kalshi lag the official NBA injury report? (RESEARCH_LOG.md,
2026-11-24, plan written before any data.)

When the league's official injury report newly lists a player as Out, do
Kalshi's prop markets on him keep trading at the old price long enough for a
bot to sell YES at that price? Research only: nothing here places an order.

    python -m research.injury_lag reports    # network: the official reports
    python -m research.injury_lag results    # network: Kalshi's public results
    python -m research.injury_lag score      # no network

``reports`` and ``results`` run on GitHub's runners (this workspace cannot
reach the league or Kalshi). Parsed reports and results are kept in
``state/injury_lag/`` (an Actions cache, git-ignored); the events found and
the aggregate result go to ``outputs/injury_lag/``.

Data: Kalshi's public trade prints already in ``data/kalshi_history/``
(2025-26, points, rebounds, assists, threes).
"""

import argparse
import json
import math
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from kalshi.stats import clustered_mean_t

STATE = Path("state/injury_lag")
OUT = Path("outputs/injury_lag")
TRADES = sorted(Path("data/kalshi_history").glob("trades_KXNBA*.parquet"))
SERIES = ("KXNBAPTS", "KXNBAREB", "KXNBAAST", "KXNBA3PT")

# --- the plan, fixed before any data ------------------------------------------
FIRST_SLOT, LAST_SLOT = (11, 0), (23, 45)  # Eastern time, every 15 minutes
MAX_GAP_MINUTES = 60  # the previous report that day must be this recent
MIN_LEAD_MINUTES = 15  # the game must tip this long after the slot
P0_LOOKBACK_MINUTES = 60
MIN_P0 = 0.10
STALE_SHARE, STALE_FLOOR = 0.5, 0.10
REACT_MINUTES = 2  # a bot reading the report every minute or two
WINDOWS = (15, 30, 60)
DECIDING_WINDOW = 30
PASS_EVENTS, PASS_GAMES, PASS_T, PASS_MEDIAN_FIRST = 50, 30, 2.0, 2.0
TAKER_FEE_RATE = 0.07  # kalshi.api.FEE_RATE; rounded up to the cent per contract

# --- fetching limits ------------------------------------------------------------
WORKERS = 6
TIME_BUDGET_SECONDS = 45 * 60

# Team names in the report -> Kalshi's codes in tickers.
KALSHI_CODES = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "LA Clippers": "LAC", "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM", "Miami Heat": "MIA", "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}  # fmt: skip
SUFFIXES = {"JR", "SR", "II", "III", "IV", "V"}


# --- names ----------------------------------------------------------------------


def letters(text):
    import unicodedata

    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z]", "", text.upper())


def ticker_code(team, name):
    """'New York Knicks', 'Brunson, Jalen' -> 'NYKJBRUNSON' (Kalshi's ticker
    prefix for the player, before the jersey number)."""
    team_code = KALSHI_CODES.get(str(team).strip())
    last, _, first = str(name).partition(",")
    words = [w for w in re.split(r"[\s.]+", last.strip()) if w]
    words = [w for w in words if letters(w) not in SUFFIXES]
    if not team_code or not words or not first.strip():
        return None
    return team_code + letters(first.strip())[:1] + "".join(letters(w) for w in words)


def split_ticker(ticker):
    """'KXNBAPTS-26JUN13NYKSAS-SASVWEMBANYAMA1-40' -> (series, game day, player
    code without the jersey number)."""
    parts = str(ticker).split("-")
    if len(parts) != 4:
        return None
    try:
        day = datetime.strptime(parts[1][:7], "%y%b%d").date()
    except ValueError:
        return None
    return parts[0], day, re.sub(r"\d+$", "", parts[2])


# --- reports (network) ----------------------------------------------------------


def slots(day):
    from markets.nba.official_injuries import ET

    start = datetime(day.year, day.month, day.day, *FIRST_SLOT, tzinfo=ET)
    end = datetime(day.year, day.month, day.day, *LAST_SLOT, tzinfo=ET)
    out = []
    while start <= end:
        out.append(start)
        start += timedelta(minutes=15)
    return out


def trade_days():
    days = set()
    for path in TRADES:
        t = pd.read_parquet(path, columns=["ticker"]).ticker.drop_duplicates()
        for parsed in t.map(split_ticker).dropna():
            days.add(parsed[1])
    return sorted(days)


def read_slot(slot):
    """Parsed rows of one report slot, or None if that slot was not published."""
    from markets.nba import official_injuries as O

    for attempt in range(3):
        try:
            data = O.download(O.slot_url(slot), timeout=15)
            break
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    if not data or not data.startswith(b"%PDF-"):
        return None
    try:
        _, rows = O.parse(data)  # (report time, table rows)
    except O.ReportError:
        return pd.DataFrame({"error": ["unreadable"]})
    return rows


def collect_reports(days=None, state=STATE, read=read_slot, clock=time.monotonic):
    """Save every slot's rows, one file per day; resumable. Returns counts."""
    folder = state / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    days = trade_days() if days is None else days
    began, done, skipped = clock(), 0, 0
    for day in days:
        path = folder / f"{day.isoformat()}.csv"
        if path.exists():
            skipped += 1
            continue
        if clock() - began > TIME_BUDGET_SECONDS:
            return {"days_done": done, "days_already": skipped, "note": "out of time"}
        frames = []
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for slot, rows in zip(slots(day), pool.map(read, slots(day))):
                if rows is None or rows.empty or "error" in rows:
                    continue
                frames.append(rows.assign(slot_et=slot.isoformat()))
        table = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        table.to_csv(path, index=False)
        done += 1
    return {"days_done": done, "days_already": skipped, "note": "finished"}


# --- events -----------------------------------------------------------------------


def out_events(reports):
    """Players newly listed Out, with the previous report within the limit.

    ``reports``: rows with slot_et, team, player, status, game_date, game_time.
    """
    if reports.empty:
        return pd.DataFrame()
    r = reports.copy()
    r["slot"] = pd.to_datetime(r.slot_et, utc=True)
    r["status"] = r.status.astype(str).str.strip()
    r = r[r.player.notna() & r.team.notna()]
    events = []
    for day, part in r.groupby(r.slot.dt.tz_convert("America/New_York").dt.date):
        day_slots = sorted(part.slot.unique())
        by_slot = {s: g.set_index(["team", "player"]) for s, g in part.groupby("slot")}
        for previous, current in zip(day_slots, day_slots[1:]):
            gap = (current - previous) / pd.Timedelta(minutes=1)
            if gap > MAX_GAP_MINUTES:
                continue
            before, now = by_slot[previous], by_slot[current]
            outs = now[now.status.eq("Out")]
            for (team, player), row in outs.iterrows():
                was = (
                    before.status.get((team, player))
                    if (team, player) in before.index
                    else None
                )
                if isinstance(was, pd.Series):
                    was = was.iloc[0]
                if was == "Out":
                    continue
                events.append(
                    {
                        "slot_utc": current,
                        "previous_slot_utc": previous,
                        "team": team,
                        "player": player,
                        "was": was or "not listed",
                        "game_date": row.get("game_date"),
                        "game_time": row.get("game_time"),
                        "code": ticker_code(team, player),
                    }
                )
    return pd.DataFrame(events)


def trades_table():
    frames = []
    for path in TRADES:
        t = pd.read_parquet(path)
        frames.append(t)
    t = pd.concat(frames, ignore_index=True)
    t["time"] = pd.to_datetime(t.created_time, utc=True, format="ISO8601")
    t["yes"] = pd.to_numeric(t.yes_price, errors="coerce")
    if t.yes.max() > 1.5:
        t["yes"] = t.yes / 100
    parsed = t.ticker.map(split_ticker)
    t = t[parsed.notna()].copy()
    parsed = parsed[parsed.notna()]
    t["game_day"] = [p[1] for p in parsed]
    t["code"] = [p[2] for p in parsed]
    t["game"] = t.ticker.str.split("-").str[1]
    return t.sort_values("time")


def match(events, trades):
    """Each event's tickers: same game day and player code; events that match
    no ticker, or codes shared by two players of a team, are dropped."""
    if events.empty:
        return events.assign(tickers=[], game=[])
    keys = trades.groupby(["game_day", "code"]).agg(
        tickers=("ticker", lambda s: sorted(set(s))), game=("game", "first")
    )
    rows = []
    for e in events.itertuples(index=False):
        day = pd.Timestamp(e.slot_utc).tz_convert("America/New_York").date()
        hit = (
            keys.loc[(day, e.code)] if e.code and (day, e.code) in keys.index else None
        )
        rows.append(
            {**e._asdict(), "tickers": None if hit is None else hit.tickers,
             "game": None if hit is None else hit.game}
        )  # fmt: skip
    return pd.DataFrame(rows)


def fee(price):
    return np.ceil(100 * TAKER_FEE_RATE * price * (1 - price) - 1e-9) / 100


def measure(matched, trades, results, tips=None):
    """One row per event and market with the measures in the plan."""
    rows = []
    by_ticker = {k: g for k, g in trades.groupby("ticker")}
    for e in matched.itertuples(index=False):
        if not e.tickers:
            continue
        s = pd.Timestamp(e.slot_utc)
        for ticker in e.tickers:
            t = by_ticker.get(ticker)
            if t is None:
                continue
            before = t[
                (t.time < s) & (t.time >= s - pd.Timedelta(minutes=P0_LOOKBACK_MINUTES))
            ]
            if before.empty:
                continue
            p0 = float(before.yes.iloc[-1])
            if p0 < MIN_P0:
                continue
            hour_ago = t[t.time < s - pd.Timedelta(minutes=P0_LOOKBACK_MINUTES)]
            p_hour = float(hour_ago.yes.iloc[-1]) if len(hour_ago) else float("nan")
            after = t[t.time >= s]
            stale_floor = max(STALE_SHARE * p0, STALE_FLOOR)
            stale = after[after.yes >= stale_floor]
            minutes = (stale.time - s).dt.total_seconds() / 60
            row = {
                "game": e.game,
                "player": e.player,
                "ticker": ticker,
                "slot_utc": s,
                "was": e.was,
                "p0": p0,
                "p_hour_before": p_hour,
                "result": results.get(ticker),
                "stale_trades": len(stale),
                "stale_contracts": float(stale["count"].sum()) if len(stale) else 0.0,
                "stale_taker_yes": float(stale.loc[stale.taker_outcome_side == "yes", "count"].sum()),
                "stale_taker_no": float(stale.loc[stale.taker_outcome_side == "no", "count"].sum()),
                "first_stale_minutes": float(minutes.min()) if len(minutes) else float("nan"),
                "last_stale_minutes": float(minutes.max()) if len(minutes) else float("nan"),
            }  # fmt: skip
            for window in WINDOWS:
                take = stale[(minutes >= REACT_MINUTES) & (minutes <= window)]
                won = (
                    1.0
                    if row["result"] == "no"
                    else 0.0
                    if row["result"] == "yes"
                    else math.nan
                )
                # Sell YES at the trade price p = buy NO at 1 - p; NO pays 1 if "no".
                no_price = 1 - take.yes.to_numpy()
                pnl = won - no_price - fee(no_price)
                row[f"rule_{window}_contracts"] = float(len(take))
                row[f"rule_{window}_pnl"] = float(np.nansum(pnl)) if len(take) else 0.0
            rows.append(row)
    return pd.DataFrame(rows)


def score(measured):
    """The plan's verdict and the reported tables."""
    out = {"markets": int(len(measured))}
    if measured.empty:
        out["verdict"] = {"passes": False, "reason": "no events with a prior price"}
        return out
    m = measured[measured.result.isin(["yes", "no"])]
    out["settlement_of_out_players"] = measured.result.value_counts(
        dropna=False
    ).to_dict()
    ev = m.groupby(["game", "player", "slot_utc"]).agg(
        stale_contracts=("stale_contracts", "sum"),
        taker_yes=("stale_taker_yes", "sum"),
        taker_no=("stale_taker_no", "sum"),
        first=("first_stale_minutes", "min"),
        p0=("p0", "mean"),
        p_hour=("p_hour_before", "mean"),
    )
    out["events"] = int(len(ev))
    out["games"] = int(ev.index.get_level_values(0).nunique())
    out["events_with_stale_trades"] = int((ev.stale_contracts > 0).sum())
    out["median_first_stale_minutes"] = (
        float(ev["first"].median()) if ev["first"].notna().any() else None
    )
    out["stale_contracts_taker_yes"] = float(ev.taker_yes.sum())
    out["stale_contracts_taker_no"] = float(ev.taker_no.sum())
    moved = (ev.p_hour - ev.p0) / ev.p_hour
    out["median_move_in_hour_before_report"] = (
        float(moved.median()) if moved.notna().any() else None
    )
    rules = {}
    for window in WINDOWS:
        c, p = f"rule_{window}_contracts", f"rule_{window}_pnl"
        per_market = m[m[c] > 0]
        if per_market.empty:
            rules[window] = {"contracts": 0}
            continue
        # one value per contract, clustered by game
        values, clusters = [], []
        for r in per_market.itertuples(index=False):
            n = int(getattr(r, c))
            values += [getattr(r, p) / n] * n
            clusters += [r.game] * n
        mean, t = clustered_mean_t(np.array(values), np.array(clusters))
        rules[window] = {
            "contracts": int(per_market[c].sum()),
            "events": int(per_market.groupby(["game", "player", "slot_utc"]).ngroups),
            "games": int(per_market.game.nunique()),
            "cents_per_contract": round(100 * mean, 2),
            "t": round(float(t), 2) if math.isfinite(t) else None,
            "dollars": round(float(per_market[p].sum()), 2),
        }
    out["rule"] = rules
    d = rules.get(DECIDING_WINDOW, {})
    median_first = out["median_first_stale_minutes"]
    checks = {
        "events": d.get("events", 0) >= PASS_EVENTS,
        "games": d.get("games", 0) >= PASS_GAMES,
        "profit": (d.get("cents_per_contract") or 0) > 0,
        "t": (d.get("t") or 0) >= PASS_T,
        "reachable": median_first is not None and median_first >= PASS_MEDIAN_FIRST,
    }
    out["verdict"] = {"passes": all(checks.values()), **checks}
    return out


# --- results (network) --------------------------------------------------------------


def fetch_results(tickers, state=STATE, get=None):
    """Kalshi's public result for each ticker, cached. Returns {ticker: result}."""
    from kalshi.api import fetch_market

    get = get or fetch_market
    path = state / "results.json"
    try:
        known = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        known = {}
    for ticker in sorted(set(tickers) - set(known)):
        market = get(ticker) or {}
        result = (market.get("result") or "").lower()
        if result:
            known[ticker] = result
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(known, sort_keys=True), "utf-8")
    return known


def load_reports(state=STATE):
    files = sorted((state / "reports").glob("*.csv"))
    frames = []
    for f in files:
        try:
            frames.append(pd.read_csv(f))
        except (ValueError, pd.errors.EmptyDataError):
            continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def diagnose(events, matched, trades):
    """Why events do or do not match a ticker (names are public)."""
    if events.empty:
        return {}
    out = {"events_by_previous_status": events.was.value_counts().to_dict()}
    real = matched[
        matched.was.isin(["Questionable", "Doubtful", "Probable", "Available"])
    ]
    out["status_changes"] = int(len(real))
    out["status_changes_matched"] = int(real.tickers.notna().sum())
    by_day_team = {}
    for day, code in trades.groupby(["game_day", "code"]).size().index:
        by_day_team.setdefault((day, code[:3]), set()).add(code)
    samples = []
    for e in real[real.tickers.isna()].head(15).itertuples(index=False):
        day = pd.Timestamp(e.slot_utc).tz_convert("America/New_York").date()
        team = (e.code or "")[:3]
        nearby = sorted(by_day_team.get((day, team), set()))
        nextday = sorted(by_day_team.get((day + pd.Timedelta(days=1), team), set()))
        samples.append({"player": e.player, "team": e.team, "code": e.code,
                        "slot": str(e.slot_utc), "game_date": e.game_date,
                        "codes_that_day": nearby[:12], "codes_next_day": nextday[:6]})  # fmt: skip
    out["unmatched_samples"] = samples
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("stage", choices=("reports", "results", "score"))
    args = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    if args.stage == "reports":
        print(json.dumps(collect_reports()))
        return 0
    events = out_events(load_reports())
    trades = trades_table()
    matched = match(events, trades)
    if args.stage == "results":
        tickers = [t for ts in matched.tickers.dropna() for t in ts]
        known = fetch_results(tickers)
        print(json.dumps({"tickers": len(tickers), "with_result": len(known)}))
        return 0
    try:
        results = json.loads((STATE / "results.json").read_text("utf-8"))
    except (OSError, ValueError):
        results = {}
    measured = measure(matched, trades, results)
    summary = {
        "diagnostics": diagnose(events, matched, trades),
        "note": "2025-26, historical; trade prints are public; in-sample",
        "events_found": int(len(events)),
        "events_matched": int(matched.tickers.notna().sum()) if len(matched) else 0,
        **score(measured),
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=1, default=str) + "\n", "utf-8"
    )
    if len(measured):
        measured.to_csv(OUT / "markets.csv.gz", index=False)
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
