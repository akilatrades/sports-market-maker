"""Supervised, one-order NFL production execution pilot.

Never imported by the always-on Demo service. No production writes unless
--live, KALSHI_ENV=prod, TRADE_MODE=live, PROD_PILOT_ARM=YES and
ALLOW_PRODUCTION_TRADING=YES are *all* supplied from a separate production
environment. The journal is outside Git; one attempt permanently blocks
further placement until a human audits it.
"""

import argparse
import fcntl
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path

from kalshi.paper_props import candidate_orders
from kalshi.trading import Order, TradingClient, TradingError

STATE_DIR = Path("/home/trader/prod-nfl-pilot")
MAX_ORDER = 2.0
MAX_OPEN = 5.0
MAX_EXPERIMENT = 25.0
WINDOW = (0.5, 2.0)
REQUIRED_ENV = {
    "KALSHI_ENV": "prod",
    "TRADE_MODE": "live",
    "PROD_PILOT_ARM": "YES",
    "ALLOW_PRODUCTION_TRADING": "YES",
}


def assert_live_safety(env):
    for key, expected in REQUIRED_ENV.items():
        if env.get(key) != expected:
            raise TradingError(f"Production pilot blocked: {key} must equal {expected}")
    if env.get("DEMO_PILOT") == "1":
        raise TradingError("Production pilot cannot run in Demo mode")
    if env.get("TRADE_MARKET", "nfl") != "nfl":
        raise TradingError("Production pilot restricted to NFL")


def append_event(journal, event):
    with journal.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, sort_keys=True) + "\n")
        file.flush()
        os.fsync(file.fileno())


def read_events(journal):
    if not journal.exists():
        return []
    return [json.loads(line) for line in journal.read_text().splitlines() if line]


def choose_market(frame, now, window=WINDOW):
    """Retain the sportsbook-veto rule; override *only* the entry window."""
    if frame.empty:
        return None
    eligible = frame[
        frame.injury_status.fillna("").eq("")
        & frame.hours_to_tip.between(*window)
        & frame.ticker.astype(str).str.startswith(("KXNFLRECYDS-", "KXNFLANYTD-"))
        & frame.tip_utc.notna()
    ]
    if eligible.empty:
        return None
    orders = candidate_orders(eligible, "no_seller_bookline", window=window)
    if orders.empty:
        return None
    orders = orders[orders.side.eq("no")].sort_values("edge", ascending=False)
    if orders.empty:
        return None
    return orders.iloc[0]


def make_order(candidate, now):
    price = float(candidate.price)
    cents = round(price * 100)
    if not math.isfinite(price) or abs(price * 100 - cents) > 1e-6:
        raise TradingError("Non-cent order price refused")
    if not (1 <= cents <= 99):
        raise TradingError("Invalid price")
    count = int(MAX_ORDER // price)
    if count < 1:
        raise TradingError("Not enough order budget")
    cost = round(count * price, 2)
    # Total spending reserve includes conservative 10% fee allowance.
    if cost * 1.10 > MAX_OPEN or cost * 1.10 > MAX_EXPERIMENT:
        raise TradingError("Production pilot exposure cap")
    expiration = int(candidate.tip_utc.timestamp())
    if expiration <= int(now.timestamp()) + 29 * 60:
        raise TradingError("Too near kickoff: order refused")
    return Order(
        ticker=str(candidate.ticker),
        side="no",
        count=count,
        price_cents=cents,
        expiration_ts=expiration,
        post_only=True,
    ), cost


def no_existing_exposure(client):
    """Strict first pilot: unrelated production exposure requires manual review."""
    if client.orders("resting"):
        raise TradingError("Production already has resting orders; do not trade")
    positions = client.positions()
    if positions:
        raise TradingError("Production has existing positions; do not trade")


def execute_once(*, live, env, client, frame, now, journal):
    if live:
        assert_live_safety(env)
        if not client.can_sign or client.env != "prod" or client.dry_run:
            raise TradingError("Requires signed production execution client")
        if any(x.get("event") == "intent" for x in read_events(journal)):
            raise TradingError("Prior production attempt found; manual review required")
        no_existing_exposure(client)
        balance = client.balance()["balance"]
        if balance < MAX_EXPERIMENT:
            raise TradingError("At least $25 free balance required for pilot")
    candidate = choose_market(frame, now)
    if candidate is None:
        print("NO ELIGIBLE NFL MARKET (no order)")
        return False
    order, cost = make_order(candidate, now)
    details = {
        "ticker": order.ticker,
        "side": order.side,
        "count": order.count,
        "price_cents": order.price_cents,
        "cost": cost,
        "tip_utc": candidate.tip_utc.isoformat(),
        "edge": round(float(candidate.edge), 4),
    }
    if not live:
        print("DRY ONLY " + json.dumps(details, sort_keys=True))
        return False

    # Write-ahead intent means even a timeout/crash CANNOT cause the same
    # runner to retry a possibly accepted live order. Persist before network.
    append_event(
        journal,
        {
            "event": "intent",
            "utc": now.isoformat(),
            "client_order_id": order.client_order_id,
            **details,
        },
    )
    try:
        result = client.place(order)
    except Exception as err:
        append_event(
            journal,
            {
                "event": "uncertain_result",
                "utc": datetime.now(UTC).isoformat(),
                "error_type": type(err).__name__,
            },
        )
        raise TradingError(
            "Order submission uncertain. Inspect production orders manually; "
            "never retry automatically."
        ) from err
    append_event(
        journal,
        {
            "event": "accepted",
            "utc": datetime.now(UTC).isoformat(),
            "order_id": result["order_id"],
            "client_order_id": order.client_order_id,
        },
    )
    print("PRODUCTION ORDER ACCEPTED; verify fills in Kalshi and do not rerun live.")
    print(
        json.dumps(
            {
                "ticker": order.ticker,
                "cost": cost,
                "order_id": result["order_id"],
                "immediate_fill_count": result.get("fill_count", "unknown"),
            },
            sort_keys=True,
        )
    )
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--inspect", action="store_true")
    args = parser.parse_args()
    if sum([args.dry_run, args.live, args.inspect]) != 1:
        parser.error("Choose one of --dry-run, --live, --inspect")
    if args.live:
        assert_live_safety(os.environ)
    else:
        if os.getenv("KALSHI_ENV") != "prod":
            raise TradingError("Pilot diagnostics must use production market data")

    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE_DIR.chmod(0o700)
    lock_path = STATE_DIR / "pilot.lock"
    journal = STATE_DIR / "orders.jsonl"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.inspect:
            entries = read_events(journal)
            print("Pilot journal events:", len(entries))
            for e in entries:
                print(
                    json.dumps({k: v for k, v in e.items() if k != "client_order_id"})
                )
            return
        client = TradingClient(dry_run=not args.live, env="prod")
        now = datetime.now(UTC)
        # First ensure production account status before spending computation.
        if args.live:
            if not client.can_sign:
                raise TradingError("Missing production API credentials")
            if any(x.get("event") == "intent" for x in read_events(journal)):
                raise TradingError("Prior attempt; one-shot pilot locked")
        from live.nfl_trade import candidates as nfl_candidates

        frame = nfl_candidates(now)
        execute_once(
            live=args.live,
            env=os.environ,
            client=client,
            frame=frame,
            now=now,
            journal=journal,
        )


if __name__ == "__main__":
    main()
