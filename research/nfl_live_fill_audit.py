"""Read-only audit of real NFL production fills versus public trade prints.

Run on the dedicated production VPS with its existing EnvironmentFile.
Never creates, amends, cancels or submits an order.
"""
import argparse
import json
import math
from datetime import datetime
from pathlib import Path

from kalshi.api import fetch_trades
from kalshi.trading import TradingClient

JOURNAL = Path("/home/trader/prod-nfl-auto/journal.jsonl")


def valid_num(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else 0.0
    except (TypeError, ValueError):
        return 0.0


def summarize_trades(no_price_cents, prints):
    """Public YES-taking trade flow relative to our resting YES ask."""
    yes_ask = round(1 - no_price_cents / 100, 4)
    # Only order-book taker-buy-YES prints can hit our sell-YES / buy-NO.
    taking_yes = [
        p for p in prints
        if p.get("taker_outcome_side") == "yes"
        and not p.get("is_block_trade")
        and 0 < valid_num(p.get("yes_price")) < 1
    ]
    at = sum(
        valid_num(p.get("count"))
        for p in taking_yes
        if abs(valid_num(p.get("yes_price")) - yes_ask) < 0.00001
    )
    through = sum(
        valid_num(p.get("count"))
        for p in taking_yes
        if valid_num(p.get("yes_price")) > yes_ask + 0.00001
    )
    near = sum(
        valid_num(p.get("count"))
        for p in taking_yes
        if yes_ask - 0.01001 <= valid_num(p.get("yes_price")) < yes_ask - 0.00001
    )
    total = sum(valid_num(p.get("count")) for p in taking_yes)
    return {"yes_ask_cents": round(yes_ask * 100), "yes_taker_volume": total,
            "at_price": at, "through_price": through, "one_cent_away": near}


def run(journal, client, now):
    events = [json.loads(s) for s in journal.read_text().splitlines() if s.strip()]
    attempts = [e for e in events if e.get("event") == "intent"]
    accepted = {e["client_order_id"]: e for e in events
                if e.get("event") == "accepted"}
    if not attempts:
        print("NO LIVE ORDER ATTEMPTS IN JOURNAL")
        return
    orders_by_id = {}
    for status in ("resting", "executed", "canceled"):
        for item in client.orders(status):
            oid = item.get("order_id")
            if oid:
                orders_by_id[str(oid)] = status
    start_ts = min(int(datetime.fromisoformat(a["utc"]).timestamp()) for a in attempts) - 60
    fills = client.fills(min_ts=start_ts)
    by_order = {}
    for fill in fills:
        oid = str(fill.get("order_id", ""))
        by_order.setdefault(oid, []).append(fill)
    print("KALSHI PRODUCTION | authoritative fills vs public trade flow")
    print("This is READ ONLY. Public prints do not prove a hypothetical fill.")
    print(f"Journal orders={len(attempts)}; retrieved account fills={len(fills)}")
    for a in attempts:
        known = accepted.get(a["client_order_id"])
        if known is None:
            print(f"UNCONFIRMED SUBMISSION {a['ticker']} | manual inspection required")
            continue
        oid = str(known["order_id"])
        placed = datetime.fromisoformat(known.get("utc", a["utc"]))
        tip = datetime.fromisoformat(a["tip_utc"])
        end = min(now, tip)
        t = None
        try:
            prints = fetch_trades(a["ticker"], int(placed.timestamp()),
                                  max(int(placed.timestamp()) + 1, int(end.timestamp())))
            t = summarize_trades(a["price_cents"], prints)
            public_info = (
                f"YES-taker total={t['yes_taker_volume']:.0f} contracts; "
                f"at our quote={t['at_price']:.0f}; through={t['through_price']:.0f}; "
                f"1c short={t['one_cent_away']:.0f}"
            )
        except Exception as e:
            public_info = f"public trades unavailable: {type(e).__name__}"
        f = by_order.get(oid, [])
        filled = sum(valid_num(x.get("count_fp", x.get("count"))) for x in f)
        fee = sum(valid_num(x.get("fee_cost")) for x in f)
        status = orders_by_id.get(oid, "not returned by resting/executed/canceled searches")
        print(f"MARKET {a['ticker']}")
        print(f"  Submitted buy NO @ {a['price_cents']}c | count={a['count']} "
              f"| accepted {placed.isoformat()} | order status={status}")
        print(f"  ACTUAL EXCHANGE FILLS: {filled:g}/{a['count']} contracts; "
              f"fees from fill records=${fee:.4f}")
        print(f"  PUBLIC MARKET PRINTS DURING ORDER WINDOW: {public_info}")
        if filled == 0 and t is not None and t["through_price"] > 0:
            print("  NOTE: trades crossed quote; inspect time/queue/cancel reasons.")
    print("Follow-up: compare at-price volumes and queue position before changing quotes.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", type=Path, default=JOURNAL)
    args = parser.parse_args()
    # Requires the protected production EnvironmentFile; no trading writes.
    client = TradingClient(dry_run=True, env="prod")
    if not client.can_sign:
        raise RuntimeError("Requires authenticated production READ access")
    run(args.journal, client, datetime.now().astimezone())


if __name__ == "__main__":
    main()
