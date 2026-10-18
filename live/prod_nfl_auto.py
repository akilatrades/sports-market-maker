"""Bounded unattended NFL production experiment. NOT the general-purpose trader.

This worker is isolated from the Demo service and has a lifetime *gross-cost*
budget below $25 including a fee buffer. One new post-only order max per pass,
no automatic re-arming, and durable journal before each network write. Fail
closed on inconsistent balances, orders, positions, fills or model data.
"""

import argparse
import fcntl
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from kalshi.api import fetch_market
from kalshi.paper_props import candidate_orders
from kalshi.trading import Order, TradingClient, TradingError

MAX_GROSS_COST = 25.0
MAX_ORDER_COST = 2.0
MAX_ACTIVE_COST = 5.0
MAX_GAME_COST = 3.0
MAX_TEAM_COST = 3.0
MAX_DAILY_COST = 10.0
MAX_GAME_ORDERS = 2
MAX_CONTRACTS = 5
FEE_RESERVE = 1.10
WINDOW = (0.5, 2.0)
STATE = Path("/home/trader/prod-nfl-auto")
REQUIRED = {
    "KALSHI_ENV": "prod",
    "TRADE_MODE": "live",
    "PROD_AUTO_ARM": "YES",
    "ALLOW_PRODUCTION_TRADING": "YES",
}


def guard(env, client):
    for name, expected in REQUIRED.items():
        if env.get(name) != expected:
            raise TradingError(f"Unarmed production auto: {name} must be {expected}")
    if env.get("DEMO_PILOT") == "1" or env.get("TRADE_MARKET", "nfl") != "nfl":
        raise TradingError("Prod auto cannot use Demo pilot or another market")
    if client.env != "prod" or client.dry_run or not client.can_sign:
        raise TradingError("Signed production execution client required")


def write_event(path, data):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_journal(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def money(n):
    value = float(n)
    if not math.isfinite(value) or value < 0:
        raise TradingError(f"Invalid risk value {n!r}")
    return round(value, 4)


def reserve(cost):
    return math.ceil(money(cost) * FEE_RESERVE * 100 - 1e-8) / 100


def records(events):
    attempts = [e for e in events if e.get("event") == "intent"]
    accepted = {e["client_order_id"]: e for e in events if e.get("event") == "accepted"}
    if len({e["client_order_id"] for e in attempts}) != len(attempts):
        raise TradingError("Duplicate client order ID in production journal")
    for attempt in attempts:
        if attempt["client_order_id"] not in accepted:
            raise TradingError(
                "Uncertain production order attempt: HALT, reconcile manually"
            )
    return attempts, accepted


def current_production_state(client, attempts, accepted):
    """Verify every live order/position belongs to the strategy journal."""
    resting = client.orders("resting")
    positions = client.positions()
    if not isinstance(resting, list) or not isinstance(positions, list):
        raise TradingError("Unparseable production orders/positions")
    # A live account should be dedicated to this pilot. If there are foreign
    # resting orders or positions, do not allocate additional risk.
    known_ids = {r["order_id"] for r in accepted.values()}
    tickers = {a["ticker"] for a in attempts}
    unknown_orders = [r for r in resting if r.get("order_id") not in known_ids]
    if unknown_orders:
        raise TradingError("Foreign resting production orders: HALT")
    held = []
    for p in positions:
        pos = p.get("position", p.get("position_fp"))
        if pos is None:
            raise TradingError("Cannot parse production position")
        try:
            qty = float(pos)
        except (TypeError, ValueError) as error:
            raise TradingError("Cannot parse production position") from error
        if not math.isfinite(qty):
            raise TradingError("Nonfinite production position")
        if qty:
            ticker = p.get("market_ticker", p.get("ticker"))
            if not ticker or ticker not in tickers:
                raise TradingError("Foreign open production position: HALT")
            held.append(ticker)
    settlements = client.settlements() if attempts else []
    if not isinstance(settlements, list):
        raise TradingError("Cannot inspect production settlements")
    settled = set()
    for r in settlements:
        ticker = r.get("market_ticker") or r.get("ticker")
        if ticker in tickers:
            settled.add(ticker)
    # A buy can be accepted and disappear from resting before a later GET
    # (canceled, filled, exchange failure). Never free reservation unless
    # settlement is verified. Conservatively keeps it in active exposure.
    still_at_risk = [a for a in attempts if a["ticker"] not in settled]
    return {
        "resting": resting,
        "held": held,
        "settled": settled,
        "settlements": settlements,
        "active": still_at_risk,
    }


def cancel_invalid_resting(client, journal, state, frame, now):
    """Withdraw owned orders after new roster/injury/market safety failures."""
    if frame.empty:
        invalid = set(o.get("order_id") for o in state["resting"])
    else:
        status = frame.set_index("ticker")["injury_status"].fillna("UNVERIFIED")
        valid = set(status[status.eq("")].index)
        invalid = set()
        for resting in state["resting"]:
            ticker = resting.get("ticker")
            if ticker not in valid:
                invalid.add(resting["order_id"])
    canceled = 0
    for resting in state["resting"]:
        order_id = resting.get("order_id")
        if order_id not in invalid:
            continue
        ticker = resting.get("ticker")
        if not ticker:
            raise TradingError("Cannot cancel order without its ticker: HALT")
        write_event(
            journal,
            {
                "event": "cancel_intent",
                "utc": now.isoformat(),
                "order_id": order_id,
                "ticker": ticker,
                "reason": "availability no longer verified",
            },
        )
        try:
            client.cancel(order_id, ticker=ticker)
        except Exception as error:
            raise TradingError(
                "Cannot confirm cancellation; HALT and inspect Kalshi orders"
            ) from error
        write_event(
            journal,
            {
                "event": "cancel_accepted",
                "utc": datetime.now(UTC).isoformat(),
                "order_id": order_id,
            },
        )
        canceled += 1
    return canceled


def cancel_owned_on_kill(client, journal):
    """Emergency stop: only cancel orders provably from this pilot journal."""
    events = load_journal(journal)
    ids = {e["order_id"] for e in events if e.get("event") == "accepted"}
    client_ids = {e["client_order_id"] for e in events if e.get("event") == "intent"}
    canceled = 0
    for item in client.orders("resting"):
        if (
            item.get("order_id") not in ids
            and item.get("client_order_id") not in client_ids
        ):
            continue
        oid, ticker = item.get("order_id"), item.get("ticker")
        if not oid or not ticker:
            raise TradingError("Emergency cancellation cannot route: inspect Kalshi")
        client.cancel(oid, ticker=ticker)
        write_event(
            journal,
            {
                "event": "emergency_cancel",
                "utc": datetime.now(UTC).isoformat(),
                "order_id": oid,
                "ticker": ticker,
            },
        )
        canceled += 1
    print(f"PROD AUTO HALTED: canceled {canceled} owned resting orders")
    return canceled


def record_execution(journal, events, attempts, accepted, fills, settlements):
    """Store distinct actual fills and exchange settlement amounts for audit."""
    known_orders = {e["order_id"] for e in accepted.values()}
    tickers = {a["ticker"] for a in attempts}
    seen_fills = {e.get("fill_id") for e in events if e.get("event") == "fill"}
    seen_results = {e.get("ticker") for e in events if e.get("event") == "settlement"}
    for fill in fills:
        oid = fill.get("order_id")
        fid = fill.get("fill_id") or fill.get("trade_id")
        if not fid or fid in seen_fills or oid not in known_orders:
            continue
        write_event(journal, {
            "event": "fill", "fill_id": str(fid),
            "utc": str(fill.get("created_time", "")),
            "ticker": str(fill.get("ticker") or fill.get("market_ticker") or ""),
            "order_id": str(oid), "count": str(fill.get("count_fp", "")),
            "yes_price": str(fill.get("yes_price_dollars", "")),
            "no_price": str(fill.get("no_price_dollars", "")),
            "fee": str(fill.get("fee_cost", "")),
        })
        seen_fills.add(fid)
    for result in settlements:
        ticker = result.get("market_ticker") or result.get("ticker")
        if ticker not in tickers or ticker in seen_results:
            continue
        write_event(journal, {
            "event": "settlement", "ticker": ticker,
            "utc": str(result.get("settled_time", "")),
            "revenue_cents": result.get("revenue"),
            "yes_cost_cents": result.get("yes_total_cost"),
            "no_cost_cents": result.get("no_total_cost"),
            "fee_cents": result.get("fee_cost"),
        })
        seen_results.add(ticker)


def verify_quote(candidate):
    """Re-read production quote immediately before placing the selected order."""
    market = fetch_market(str(candidate.ticker))
    if not market or market.get("status") not in {"active", "open"}:
        raise TradingError("Selected market no longer active")
    try:
        bid = float(market["yes_bid_dollars"])
        ask = float(market["yes_ask_dollars"])
    except (KeyError, TypeError, ValueError) as err:
        raise TradingError("Production quote fields missing") from err
    if not all(math.isfinite(x) for x in (bid, ask)):
        raise TradingError("Nonfinite production quote")
    if not 0 < bid < ask < 1:
        raise TradingError("Production market is not truly two-sided")
    no_bid = 1 - ask
    expected = round(no_bid + (0.01 if ask - bid >= 0.019999 else 0), 2)
    if abs(expected - float(candidate.price)) > 0.001:
        raise TradingError("Price moved since model snapshot; wait for next pass")


def select_candidates(frame, events, state, now):
    attempts, _ = records(events)
    if frame.empty:
        return []
    eligible = frame[
        frame.injury_status.fillna("").eq("")
        & frame.hours_to_tip.between(*WINDOW)
        & frame.tip_utc.notna()
        & frame.ticker.astype(str).str.startswith(("KXNFLRECYDS-", "KXNFLANYTD-"))
    ]
    if eligible.empty:
        return []
    found = candidate_orders(eligible, "no_seller_bookline", window=WINDOW)
    if found.empty:
        return []
    found = found[found.side.eq("no")].copy()
    found["edge"] = pd.to_numeric(found.edge, errors="coerce")
    # Extremely large modeled edges are suspicious: wrong player, mismatched
    # line, or stale sportsbook feed. Such markets need human review.
    found = found[found.edge.between(0, 0.15)]
    already = {a["ticker"] for a in attempts}
    found = found[~found.ticker.isin(already)]
    if found.empty:
        return []
    return list(found.sort_values("edge", ascending=False).itertuples())


def order_from_row(row, now):
    price = float(row.price)
    cents = round(price * 100)
    if not math.isfinite(price) or abs(cents - price * 100) > 1e-6:
        raise TradingError("Order price not a whole cent")
    if not 10 <= cents <= 90:
        raise TradingError("Order price outside safe 10c–90c range")
    count = min(int((MAX_ORDER_COST + 1e-8) // price), MAX_CONTRACTS)
    if count <= 0:
        raise TradingError("Zero affordable contracts")
    tip = pd.Timestamp(row.tip_utc)
    if pd.isna(tip) or int(tip.timestamp()) < int(now.timestamp()) + 31 * 60:
        raise TradingError("Too close to kickoff")
    cost = round(count * cents / 100, 2)
    order = Order(
        ticker=str(row.ticker),
        side="no",
        count=count,
        price_cents=cents,
        expiration_ts=int(tip.timestamp()),
        post_only=True,
    )
    return order, cost


def room_for(attempts, active, row, cost, now):
    today = now.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date()
    total = sum(reserve(a["cost"]) for a in attempts)
    open_now = sum(reserve(a["cost"]) for a in active)
    game_cost = sum(
        reserve(a["cost"]) for a in attempts if a["game_id"] == str(row.game_id)
    )
    team_cost = sum(reserve(a["cost"]) for a in attempts if a["team"] == str(row.team))
    game_orders = sum(a["game_id"] == str(row.game_id) for a in attempts)
    day_cost = sum(
        reserve(a["cost"])
        for a in attempts
        if datetime.fromisoformat(a["utc"])
        .astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))
        .date()
        == today
    )
    r = reserve(cost)
    return (
        total + r <= MAX_GROSS_COST + 1e-9
        and open_now + r <= MAX_ACTIVE_COST + 1e-9
        and game_cost + r <= MAX_GAME_COST + 1e-9
        and team_cost + r <= MAX_TEAM_COST + 1e-9
        and day_cost + r <= MAX_DAILY_COST + 1e-9
        and game_orders < MAX_GAME_ORDERS
    )


def pass_once(client, env, frame, now, journal, *, dry=False):
    if not dry:
        guard(env, client)
    events = load_journal(journal)
    attempts, accepted = records(events)
    if not dry:
        state = current_production_state(client, attempts, accepted)
        free = money(client.balance()["balance"])
        if free < MAX_ORDER_COST * FEE_RESERVE:
            raise TradingError("Production cash balance insufficient")
    else:
        state = {"active": []}
    candidates = select_candidates(frame, events, state, now)
    if not dry:
        min_ts = (
            int(datetime.fromisoformat(attempts[0]["utc"]).timestamp()) - 60
            if attempts
            else int(now.timestamp()) - 60
        )
        # Capture fill data or halt on read failure (do not silently use zero).
        fills = client.fills(min_ts=min_ts)
        if not isinstance(fills, list):
            raise TradingError("Cannot read production fills")
        record_execution(
            journal, load_journal(journal), attempts, accepted,
            fills, state["settlements"],
        )
        canceled = cancel_invalid_resting(client, journal, state, frame, now)
        if canceled:
            print(f"PROD AUTO: canceled {canceled} unsafe resting orders")
            # Require another reconciliation pass after cancellation.
            return False
        print(
            f"PROD AUTO: attempts={len(attempts)}, resting={len(state['resting'])}, "
            f"held={len(state['held'])}, settled_tickers={len(state['settled'])}, "
            f"fills={len(fills)}, gross_reserved=${sum(reserve(a['cost']) for a in attempts):.2f}/$25"
        )
    if not candidates:
        print("No eligible late-window NFL opportunities")
        return False
    for row in candidates:
        try:
            order, cost = order_from_row(row, now)
        except TradingError:
            continue
        if not room_for(attempts, state["active"], row, cost, now):
            continue
        try:
            verify_quote(row)
        except TradingError:
            continue
        if dry:
            print(
                "DRY CANDIDATE",
                json.dumps(
                    {
                        "ticker": order.ticker,
                        "side": order.side,
                        "count": order.count,
                        "cost": cost,
                        "price_cents": order.price_cents,
                    },
                    sort_keys=True,
                ),
            )
            return False

        # Durable intent first; any failure after this (including a timeout)
        # disables all future automatic orders until manually investigated.
        write_event(
            journal,
            {
                "event": "intent",
                "utc": now.isoformat(),
                "client_order_id": order.client_order_id,
                "ticker": order.ticker,
                "cost": cost,
                "count": order.count,
                "price_cents": order.price_cents,
                "game_id": str(row.game_id),
                "team": str(row.team),
                "tip_utc": pd.Timestamp(row.tip_utc).isoformat(),
                "edge": round(float(row.edge), 4),
            },
        )
        try:
            result = client.place(order)
        except Exception as error:
            write_event(
                journal,
                {
                    "event": "unknown_outcome",
                    "utc": datetime.now(UTC).isoformat(),
                    "client_order_id": order.client_order_id,
                    "type": type(error).__name__,
                },
            )
            raise TradingError(
                "Ambiguous production submission. Auto halted until manual audit."
            ) from error
        write_event(
            journal,
            {
                "event": "accepted",
                "utc": datetime.now(UTC).isoformat(),
                "client_order_id": order.client_order_id,
                "order_id": result["order_id"],
            },
        )
        print(
            "PROD AUTO ACCEPTED",
            order.ticker,
            "cost",
            cost,
            "order_id",
            result["order_id"],
        )
        try:
            queue = client.queue_position(str(result["order_id"]))
        except Exception:
            queue = None
        write_event(
            journal,
            {
                "event": "queue",
                "utc": datetime.now(UTC).isoformat(),
                "order_id": result["order_id"],
                "ahead": queue,
            },
        )
        return True
    print("No opportunities fit remaining production risk budget or fresh quotes")
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if sum((args.dry_run, args.live, args.status)) != 1:
        parser.error("Choose exactly one mode")
    directory = (
        STATE if args.live or args.status else Path("/tmp/smm-nfl-auto-readonly")
    )
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    with (directory / "lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        journal = directory / "journal.jsonl"
        if args.status:
            events = load_journal(journal)
            print("Pilot attempts:", len([e for e in events if e["event"] == "intent"]))
            print("Accepted:", len([e for e in events if e["event"] == "accepted"]))
            print(
                "Uncertain:",
                len([e for e in events if e["event"] == "unknown_outcome"]),
            )
            return
        if os.environ.get("KALSHI_ENV") != "prod":
            raise TradingError(
                "Production auto requires production venue even for dry run"
            )
        client = TradingClient(dry_run=args.dry_run, env="prod")
        if args.live:
            guard(os.environ, client)
            if (directory / "KILL").exists():
                cancel_owned_on_kill(client, journal)
                return
        from live.nfl_trade import candidates

        now = datetime.now(UTC)
        frame = candidates(now)
        pass_once(client, os.environ, frame, now, journal, dry=args.dry_run)


if __name__ == "__main__":
    main()
