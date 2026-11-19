"""Read-only watcher: are late-game "dead ticket" bids really there for us?

RESEARCH_LOG.md, 2026-11-16, "Dead-ticket watch". During NBA games this
polls ESPN's public box score and Kalshi's public quotes and writes down
every prop market where a trade would have qualified:

* ``dead``: the line is out of reach (`markets.nba.dead_ticket`) and
  someone is bidding 2c or more for YES. Selling to that bid is buying NO.
* ``reached``: the line is already met with one to spare and YES is offered
  at 99c or less.

It places no orders, reads no account and uses no keys: public GETs only.

    python -m research.dead_ticket_watch watch --hours 5.5
    python -m research.dead_ticket_watch summarize
"""

import argparse
import json
import math
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from kalshi import api as kalshi_api
from kalshi.stats import clustered_mean_t
from markets.nba import dead_ticket as D
from markets.nba import live as espn

OUT = Path("outputs/dead_ticket")
NY = ZoneInfo("America/New_York")
MIN_YES_BID = 0.02  # a 1c bid leaves nothing after the fee
MAX_DEAD_BID = 0.10  # a higher bid on a "dead" ticket means our state is wrong
MAX_REACHED_ASK = 0.99
POLL_SECONDS = 30
BOOK_EVERY_SECONDS = 300  # depth per market: first sighting, then every 5 min
FLUSH_SECONDS = 900
SOON_HOURS = 2.0  # a game this close to its start keeps the watcher waiting
COLUMNS = [
    "utc",
    "kind",
    "strict",
    "ticker",
    "game",
    "stat",
    "line",
    "so_far",
    "need",
    "period",
    "minutes_left",
    "margin",
    "yes_bid",
    "yes_ask",
    "size",
]


def game_code(event):
    """ESPN scoreboard event -> Kalshi's game code, e.g. 26NOV14BKNMEM."""
    competition = event["competitions"][0]
    teams = {
        c["homeAway"]: D.kalshi_team(c["team"]["abbreviation"])
        for c in competition["competitors"]
    }
    day = pd.Timestamp(event["date"]).tz_convert(NY).strftime("%y%b%d").upper()
    return day + teams["away"] + teams["home"]


def games_in_play(payload, now=None):
    """(ESPN id, Kalshi game code) for games in progress, and how many that
    have not started will start within SOON_HOURS of ``now`` (all of them
    when ``now`` is not given)."""
    live, waiting = [], 0
    for event in (payload or {}).get("events", []):
        try:
            state = event["competitions"][0]["status"]["type"]["state"]
            if state == "in":
                live.append((str(event["id"]), game_code(event)))
            elif state == "pre":
                if now is None:
                    waiting += 1
                    continue
                lead = pd.Timestamp(event["date"]) - pd.Timestamp(now)
                if lead <= pd.Timedelta(hours=SOON_HOURS):
                    waiting += 1
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return live, waiting


def _price(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def best_size(book, side):
    """Contracts at the best bid of ``side`` ('yes' or 'no'), or None."""
    try:
        levels = book[f"{side}_dollars"]
        return float(levels[-1][1]) if levels else 0.0
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def observe(state, game, markets, now, fetch_book=None):
    """Rows for the markets of one game that qualify right now."""
    rows = []
    for market in markets:
        parsed = D.parse_ticker(market.get("ticker"))
        if parsed is None or parsed["game"] != game:
            continue
        if market.get("status") not in (None, "active", "open"):
            continue
        so_far = state["players"].get((parsed["team"], parsed["key"]))
        if so_far is None:
            continue
        stat, line = parsed["stat"], parsed["line"]
        need = line - so_far[stat]
        bid = _price(market.get("yes_bid_dollars"))
        ask = _price(market.get("yes_ask_dollars"))
        kind = strict = side = None
        if need >= 1 and bid is not None and MIN_YES_BID <= bid <= MAX_DEAD_BID:
            if D.out_of_reach(stat, need, state["minutes_left"], overtime=False):
                kind, side = "dead", "yes"
                strict = D.out_of_reach(stat, need, state["minutes_left"])
        elif need <= -1 and ask is not None and 0 < ask <= MAX_REACHED_ASK:
            kind, strict, side = "reached", True, "no"
        if kind is None:
            continue
        book = fetch_book(market["ticker"]) if fetch_book else None
        rows.append(
            {
                "utc": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
                "kind": kind,
                "strict": bool(strict),
                "ticker": market["ticker"],
                "game": game,
                "stat": stat,
                "line": line,
                "so_far": so_far[stat],
                "need": need,
                "period": state["period"],
                "minutes_left": round(state["minutes_left"], 2),
                "margin": state["margin"],
                "yes_bid": bid,
                "yes_ask": ask,
                # contracts resting at the price we would take
                "size": best_size(book, side) if book else None,
            }
        )
    return rows


def fetch_game_markets(game):
    markets = []
    for series in D.STATS:
        page = kalshi_api.get_json(
            "/markets",
            {"event_ticker": f"{series}-{game}", "status": "open", "limit": 1000},
            retries=2,
        )
        markets.extend((page or {}).get("markets", []))
    return markets


def fetch_summary(game_id):
    return espn.get_json(f"{espn.ESPN}/summary?event={urllib.parse.quote(game_id)}")


def scoreboards(now):
    """Today's and yesterday's US-Eastern scoreboards (late games run past
    midnight)."""
    events = []
    local = now.astimezone(NY)
    for day in (local, local - timedelta(days=1)):
        try:
            payload = espn.get_json(f"{espn.ESPN}/scoreboard?dates={day:%Y%m%d}")
        except OSError:
            continue
        events.extend((payload or {}).get("events", []))
    return {"events": events}


def throttled_books(fetch=None, every=BOOK_EVERY_SECONDS, clock=time.monotonic):
    """Order-book reader that asks about each market at most once per
    ``every`` seconds (None in between)."""
    fetch = fetch or kalshi_api.fetch_orderbook
    last = {}

    def read(ticker):
        now = clock()
        if ticker in last and now - last[ticker] < every:
            return None
        last[ticker] = now
        try:
            return fetch(ticker)
        except OSError:
            return None

    return read


def one_pass(now, sources=None):
    """Every qualifying row right now, and whether any game is in play or
    starts within SOON_HOURS."""
    s = sources or {}
    live, waiting = games_in_play(s.get("scoreboards", scoreboards)(now), now)
    rows = []
    for game_id, game in live:
        try:
            state = D.parse_summary(s.get("summary", fetch_summary)(game_id))
            if state is None or state["minutes_left"] > D.MAX_MINUTES_LEFT:
                continue
            markets = s.get("markets", fetch_game_markets)(game)
            book = s.get("book", kalshi_api.fetch_orderbook)
            rows.extend(observe(state, game, markets, now, book))
        except (OSError, ValueError, KeyError):
            continue  # one game's hiccup must not stop the night
    return rows, bool(live or waiting)


def save(rows, out=OUT):
    if not rows:
        return None
    frame = pd.DataFrame(rows, columns=COLUMNS)
    folder = out / "observations"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp(frame.utc.iloc[0]).strftime("%Y-%m-%dT%H%MZ")
    path = folder / f"{stamp}.csv.gz"
    frame.to_csv(path, index=False)
    return path


def watch(hours, poll=POLL_SECONDS, out=OUT, sleep=time.sleep, clock=None):
    clock = clock or (lambda: datetime.now(timezone.utc))
    start = clock()
    end = start + timedelta(hours=hours)
    sources = {"book": throttled_books()}
    rows, idle, total, files, flushed = [], 0, 0, [], start
    while clock() < end:
        found, active = one_pass(clock(), sources)
        rows.extend(found)
        total += len(found)
        idle = 0 if active else idle + 1
        if (clock() - flushed).total_seconds() >= FLUSH_SECONDS:
            files.append(save(rows, out))  # a killed job keeps what it saw
            rows, flushed = [], clock()
        if idle * poll >= 600:  # ten minutes with nothing in play or about to start
            break
        sleep(poll)
    files.append(save(rows, out))
    files = [str(f) for f in files if f]
    print(json.dumps({"rows": total, "files": files}))
    return files


def first_sightings(obs, poll=POLL_SECONDS):
    """One row per market and kind: the first sighting, how long the quote
    stayed (seconds between first and last sighting at that price or
    better), and whether it was still there on the next poll."""
    obs = obs.assign(when=pd.to_datetime(obs.utc, utc=True)).sort_values("when")
    rows = []
    for (ticker, kind), g in obs.groupby(["ticker", "kind"], sort=False):
        first = g.iloc[0]
        if kind == "dead":
            same = g[g.yes_bid >= first.yes_bid]
        else:
            same = g[g.yes_ask <= first.yes_ask]
        seconds = (same.when.iloc[-1] - first.when).total_seconds()
        rows.append(
            first.to_dict()
            | {"stayed_seconds": seconds, "there_next_poll": seconds >= poll * 0.8}
        )
    return pd.DataFrame(rows)


def settle(first, results):
    """Would-be profit in cents per contract at the first sighting, after
    the taker fee on a 10-contract order. ``results``: ticker -> 'yes'/'no'."""
    first = first.assign(result=first.ticker.map(results))
    first = first[first.result.isin(["yes", "no"])].copy()
    won_yes = (first.result == "yes").astype(float)
    dead = first.kind == "dead"
    price = first.yes_bid.where(dead, first.yes_ask)
    fee = price.map(D.taker_fee_cents)
    # dead: sell YES at the bid (buy NO); reached: buy YES at the ask
    gross = ((price - won_yes).where(dead, won_yes - price)) * 100
    first["lost"] = won_yes.where(dead, 1 - won_yes).astype(bool)
    first["pnl_cents"] = gross - fee
    return first


def report(settled):
    out = {}
    cuts = {
        "dead_strict": (settled.kind == "dead") & settled.strict,
        "dead_loose_only": (settled.kind == "dead") & ~settled.strict,
        "reached": settled.kind == "reached",
    }
    for name, mask in cuts.items():
        g = settled[mask]
        if g.empty:
            out[name] = {"markets": 0}
            continue
        t = clustered_mean_t(g.pnl_cents.to_numpy(), g.game.to_numpy())[1]
        mean = g.pnl_cents.mean()
        sized = g["size"].dropna()
        out[name] = {
            "markets": int(len(g)),
            "games": int(g.game.nunique()),
            "nights": int(pd.to_datetime(g.utc, utc=True).dt.date.nunique()),
            "lost": int(g.lost.sum()),
            "cents_per_contract_after_fee": round(float(mean), 3),
            "game_clustered_t": round(float(t), 2) if math.isfinite(t) else None,
            "share_still_there_next_poll": round(float(g.there_next_poll.mean()), 3),
            "median_seconds_quote_stayed": float(g.stayed_seconds.median()),
            "median_contracts_at_price": float(sized.median()) if len(sized) else None,
        }
    return out


def fetch_results(tickers):
    results = {}
    for ticker in tickers:
        path = f"/markets/{urllib.parse.quote(ticker, safe='')}"
        market = (kalshi_api.get_json(path, {}, retries=2) or {}).get("market") or {}
        if market.get("result") in ("yes", "no"):
            results[ticker] = market["result"]
    return results


def summarize(out=OUT, results_for=fetch_results):
    files = sorted((out / "observations").glob("*.csv.gz"))
    if not files:
        print("no observations yet")
        return None
    obs = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    first = first_sightings(obs)
    settled = settle(first, results_for(sorted(first.ticker.unique())))
    summary = {
        "what": "watch-only sightings, public quotes; not fills, not live P&L",
        "observation_files": len(files),
        "sightings": int(len(obs)),
        "unsettled_markets": int(first.ticker.nunique() - settled.ticker.nunique()),
        "rules": report(settled),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    settled.drop(columns=["when"], errors="ignore").to_csv(
        out / "first_sightings.csv", index=False
    )
    print(json.dumps(summary, indent=2))
    return summary


def probe(now=None, sources=None):
    """One look at the public feeds, for a pull request's check: what the
    scoreboard lists, and whether a finished game's box score parses the way
    a live one must (its state is read as "in" for this check only)."""
    s = sources or {}
    now = now or datetime.now(timezone.utc)
    board = s.get("scoreboards", scoreboards)(now)
    live, waiting = games_in_play(board, now)
    out = {"events": len(board["events"]), "in_play": len(live), "soon": waiting}
    for event in board["events"]:
        try:
            status = event["competitions"][0]["status"]["type"]
            if status["state"] != "post":
                continue
            payload = s.get("summary", fetch_summary)(str(event["id"]))
            payload["header"]["competitions"][0]["status"]["type"]["state"] = "in"
            state = D.parse_summary(payload)
        except (OSError, KeyError, IndexError, TypeError, ValueError) as error:
            out["box_score_error"] = type(error).__name__
            break
        out["box_score_game"] = game_code(event)
        out["box_score_parsed"] = state is not None
        if state is not None:
            players = state["players"]
            out["players"] = len(players)
            out["period"] = state["period"]
            top = max(players.items(), key=lambda kv: kv[1]["points"], default=None)
            out["top_scorer"] = None if top is None else [*top[0], top[1]]
        break
    print(json.dumps(out))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("watch")
    w.add_argument("--hours", type=float, default=5.5)
    w.add_argument("--poll", type=int, default=POLL_SECONDS)
    sub.add_parser("summarize")
    sub.add_parser("probe")
    args = parser.parse_args()
    if args.command == "watch":
        watch(args.hours, args.poll)
    elif args.command == "probe":
        found = probe()
        # A finished game was listed but its box score did not parse: fail.
        if found.get("box_score_error") or found.get("box_score_parsed") is False:
            raise SystemExit(1)
    else:
        summarize()


if __name__ == "__main__":
    main()
