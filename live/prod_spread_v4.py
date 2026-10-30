"""Isolated v4 worker. Default is signed-read preview; --live needs a release gate.

One new order per pass. Every cancellation is followed by a separate fresh
account pass before replacement. The shared journal retains ownership across
versions; v3 events are excluded and its deployment/study files are not edited.
"""

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from kalshi import shard_funding
from kalshi.trading import Order, TradingClient, TradingError
from live import prod_spread_auto as legacy
from live import production_lock, shared_account_risk as shared, spread_policy as caps
from live import spread_completion as policy
from research.spread_entry_quality import game_key
from research.spread_forward_core import (
    EvidenceError,
    amount,
    external_book,
    instant,
    normalized_orders,
)

STATE = Path("/home/trader/prod-spread-auto")
GATE = Path("/etc/market-maker-spread-v4.json")
PRODUCTION = Path("/home/trader/sports-market-maker-prod-auto")
FROZEN_REVISION = "fe7a5e7a8cfff8eeb5018d5d047f549f8a7f7cbd"
STUDY = Path("/home/trader/spread-forward-study/manifest.json")


def source_digest(root):
    digest = hashlib.sha256()
    for name in ("live", "kalshi", "research"):
        for path in sorted((root / name).rglob("*.py")):
            digest.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def isolation_check():
    """Read-only checks; never stop a worker or remove a kill marker here."""
    for sport in ("spread", "nba", "nfl"):
        if not os.path.lexists(shared.ROOT / f"prod-{sport}-auto/KILL"):
            raise TradingError("Legacy funded workers must remain paused")
    unit = "market-maker-prod-spread-auto"
    for suffix in ("timer", "service"):
        result = subprocess.run(
            ["systemctl", "show", f"{unit}.{suffix}", "-p", "ActiveState", "-p", "UnitFileState"],
            text=True, capture_output=True, check=True,
        )
        values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if values.get("ActiveState") != "inactive" or (
            suffix == "timer" and values.get("UnitFileState") not in ("disabled", "masked")
        ):
            raise TradingError("Legacy spread timer/service must be inactive")
    revision = subprocess.check_output(
        ["git", "-C", str(PRODUCTION), "rev-parse", "HEAD"], text=True
    ).strip()
    manifest = json.loads(STUDY.read_text())
    if revision != FROZEN_REVISION or manifest.get("production_revision") != revision:
        raise TradingError("Frozen production identity changed")
    subprocess.run(["git", "-C", str(PRODUCTION), "diff", "--quiet", "HEAD", "--", "live", "kalshi"], check=True)
    if manifest.get("start") != "2026-10-25T21:47:54.024216+00:00" or manifest.get("end") != "2026-11-24T21:47:54.024216+00:00":
        raise TradingError("Frozen study window changed")


def guard(client, env, root):
    if client.dry_run or client.env != "prod" or not client.can_sign:
        raise TradingError("Signed live production client required")
    if env.get("ALLOW_PRODUCTION_TRADING") != "YES" or env.get("SPREAD_V4_ARM") != "YES":
        raise TradingError("V4 is not armed")
    if not shared.dual_mode(env):
        raise TradingError("Shared account mode required")
    isolation_check()
    stat = GATE.stat()
    if GATE.is_symlink() or stat.st_uid != 0 or stat.st_mode & 0o022:
        raise TradingError("Release gate must be root-owned and not writable by trader")
    gate = json.loads(GATE.read_text())
    if gate.get("version") != policy.VERSION or gate.get("source_sha256") != source_digest(root):
        raise TradingError("Release gate does not match this code")
    # A short explicit pilot authorization, not a permanent switch.
    now = datetime.now(UTC)
    if not instant(gate["approved_at"]) <= now < instant(gate["expires_at"]) <= instant(gate["approved_at"]) + timedelta(days=1):
        raise TradingError("Release gate expired or invalid")


def snapshot(client, journal, now):
    events = legacy.load_events(journal)
    intents, accepted, _ = legacy.records(events)
    state, context = shared.state_for(client, "spread", now)
    ledger = state["ledger"]
    if ledger.get("unavailable"):
        raise TradingError("Spread accounting unavailable")
    orders = {oid: intents[cid] for cid, oid in accepted.items()}
    for order in state["resting"]:
        intent = orders.get(str(order.get("order_id")))
        if intent is None or intent.get("strategy_version") != policy.VERSION:
            raise TradingError("Legacy or unowned spread order is still resting")
    lots = policy.inventory(events, state["fills"], state["positions"], state["settled"], now)
    own_cids = {i["client_order_id"] for i in orders.values() if i.get("strategy_version") == policy.VERSION}
    own_tickers = {i["ticker"] for i in orders.values() if i.get("strategy_version") == policy.VERSION}
    own_events = [e for e in events if e.get("client_order_id") in own_cids or (e.get("event") == "settlement" and e.get("ticker") in own_tickers)]
    pilot_pnl = shared.spread_ledger(own_events, state["fills"], state["settlements"], now)
    if len(lots) > 1 or any(
        sum((amount(x["left"]) for x in queue), Decimal(0)) > policy.SIZE
        for queue in lots.values()
    ):
        raise TradingError("V4 pilot inventory cap exceeded")
    stopped = (
        ledger["daily"] <= -caps.DAILY_LOSS_STOP
        or ledger["cumulative"] <= -caps.CUMULATIVE_LOSS_STOP
        or shared.account_loss_stop(context)
        or pilot_pnl["daily"] <= -float(policy.DAILY_LOSS)
        or pilot_pnl["cumulative"] <= -float(policy.TOTAL_LOSS)
    )
    return events, orders, state, context, lots, stopped


def market_data(client, ticker, resting, recorded=()):
    """Fresh signed identity, fees, start and external depth. No cached books."""
    market = client._request("GET", f"/markets/{quote(ticker, safe='')}")["market"]
    if market.get("ticker") != ticker or market.get("status") not in ("active", "open"):
        raise EvidenceError("market_not_open")
    if market.get("market_type") != "binary" or market.get("mve_collection_ticker"):
        raise EvidenceError("unsupported_contract")
    if amount(market.get("notional_value_dollars"), True) != 1:
        raise EvidenceError("unsupported_notional")
    event = market["event_ticker"]
    series = ticker.split("-", 1)[0]
    if series not in caps.SERIES or series in caps.NO_START_SERIES:
        raise EvidenceError("series_not_allowed")
    # This first pilot requires a timestamp in the event ticker. It never
    # guesses start time from an expiration offset.
    start = legacy.ticker_start(event)
    if start is None:
        raise EvidenceError("verified_start_missing")
    expires = instant(market["expected_expiration_time"])
    milestones = client._request("GET", "/milestones", {"related_event_ticker": event, "limit": 100})
    if not isinstance(milestones.get("milestones"), list):
        raise EvidenceError("milestones_unavailable")
    earlier = legacy.milestone_start(event, expires, lambda _: milestones)
    prior = [instant(i["event_start_utc"]) for i in recorded if i.get("event_ticker") == event and i.get("event_start_utc")]
    start = min([start, *prior, *([earlier] if earlier else [])])
    fees = client._request("GET", f"/series/{quote(series, safe='')}")["series"]
    if fees.get("ticker") != series:
        raise EvidenceError("series_identity_mismatch")
    policy.fee_bound(fees, True)
    began = time.monotonic()
    book = client._request("GET", f"/markets/{quote(ticker, safe='')}/orderbook")
    if time.monotonic() - began > policy.MAX_BOOK_SECONDS:
        raise EvidenceError("slow_book_read")
    own = normalized_orders([o for o in resting if o.get("ticker") == ticker])
    depth = external_book(book, ticker, own)
    return {
        "market": market, "start": start, "expires": expires, "fees": fees,
        "book": depth, "book_read": time.monotonic(), "series": series,
        "exchange_index": shard_funding.verify_market_shard({"market": market}),
    }


def decision(client, events, orders, state, context, lots, now, series, deadline):
    recorded = list(orders.values())
    if lots:
        ticker = next(iter(lots))
        data = market_data(client, ticker, state["resting"], recorded)
        planned, reason = policy.completion_quote(
            ticker, lots[ticker], data["book"], data["fees"], data["start"], now
        )
        return ([planned] if planned else []), data, reason
    filled = {
        str(f.get("order_id")) for f in state["fills"]
        if str(f.get("order_id")) in orders
    }
    banned = {
        game_key(i["event_ticker"])
        for oid, i in orders.items()
        if i.get("strategy_version") != policy.VERSION or oid in filled
    }
    for attempt in context["ownership"]["attempts"]:
        if attempt.get("_cohort") != "spread" and attempt.get("event_ticker"):
            banned.add(game_key(attempt["event_ticker"]))
    active = {o["ticker"] for o in state["resting"]}
    if len(active) > 1:
        raise EvidenceError("multiple_active_pilot_markets")
    candidates = []
    if active:
        candidates = list(active)
    else:
        others = {t for t, owner in context["ownership"]["tickers"].items() if owner != "spread"}
        for name in series:
            if time.monotonic() >= deadline:
                break
            rows = client._pages("/markets", "markets", {"series_ticker": name, "status": "open", "limit": 200})
            eligible = legacy.eligible_markets(rows, name, now, others)
            candidates.extend(m["ticker"] for m in eligible if m["postable"] and game_key(m["event_ticker"]) not in banned)
    for ticker in candidates:
        if time.monotonic() >= deadline:
            break
        data = market_data(client, ticker, state["resting"], recorded)
        if game_key(data["market"]["event_ticker"]) in banned:
            continue
        hours = (data["expires"] - now).total_seconds() / 3600
        if not caps.WINDOW_HOURS[0] <= hours <= caps.WINDOW_HOURS[1]:
            continue
        plans = policy.entry_quotes(data["market"], data["book"], data["fees"], data["start"], now)
        if plans:
            return plans, data, "quoting_entry"
    return [], None, "no_entry"


def cancellations(resting, orders, fills, plans, now):
    wanted = {(q.ticker, q.side): q for q in plans}
    kept, cancel = set(), []
    for order in resting:
        intent = orders[str(order["order_id"])]
        key = (intent["ticker"], intent["side"])
        plan = wanted.get(key)
        left = legacy.remaining_count(order, intent, fills)
        expires = instant(intent["expires_utc"]) if intent.get("expires_utc") else now
        if (
            plan is not None and not plan.immediate and key not in kept
            and intent["price_cents"] == plan.price
            and Decimal(str(left)) <= plan.quantity and left > 0
            and expires > now + timedelta(seconds=30)
            and intent.get("purpose") == plan.purpose
        ):
            kept.add(key)
        else:
            cancel.append((order, left))
    return kept, cancel


def submit(client, journal, plan, data, now, deadline, authorize):
    """Durable intent before POST; never retry an ambiguous submission."""
    cost = plan.quantity * (Decimal(plan.price) / 100 + policy.fee_bound(data["fees"], plan.immediate))
    balances = client._request("GET", "/portfolio/balance")
    if shard_funding.shard_balance(balances, data["exchange_index"]) < cost:
        raise TradingError("V4 shard is unfunded")
    if time.monotonic() >= deadline or time.monotonic() - data["book_read"] > policy.MAX_BOOK_SECONDS:
        return "stale_before_submit"
    if datetime.now(UTC) >= data["start"] or os.path.lexists(journal.parent / "V4_KILL"):
        return "stopped_before_submit"
    authorize()
    if time.monotonic() - data["book_read"] > policy.MAX_BOOK_SECONDS:
        return "stale_before_submit"
    expires = min(now + policy.QUOTE_LIFE, data["start"] - policy.CUTOFF)
    order = Order(
        ticker=plan.ticker, side=plan.side, count=plan.quantity,
        price_cents=plan.price, fractional=True,
        expiration_ts=None if plan.immediate else int(expires.timestamp()),
        post_only=not plan.immediate, reduce_only=plan.immediate,
        time_in_force="immediate_or_cancel" if plan.immediate else "good_till_canceled",
        client_order_id=f"smm-spread-v4-{uuid.uuid4()}", exchange_index=data["exchange_index"],
    )
    order.validate()
    stamp = datetime.now(UTC).isoformat()
    legacy.write_event(journal, {
        "event": "intent", "utc": stamp, "client_order_id": order.client_order_id,
        "ticker": plan.ticker, "event_ticker": data["market"]["event_ticker"],
        "event_start_utc": data["start"].isoformat(), "series": data["series"],
        "side": plan.side, "price_cents": plan.price, "count": str(plan.quantity),
        "cost": float(cost), "strategy_version": policy.VERSION, "purpose": plan.purpose,
        "expires_utc": None if plan.immediate else expires.isoformat(),
        "reduce_only": plan.immediate, "fee_bound_per_contract": str(policy.fee_bound(data["fees"], plan.immediate)),
        "external_book": data["book"], "fee_type": data["fees"]["fee_type"],
        "fee_multiplier": data["fees"]["fee_multiplier"],
    })
    try:
        result = client.place(order)
        if not isinstance(result, dict) or not result.get("order_id"):
            raise TradingError("Order response has no identity")
    except Exception as error:
        legacy.write_event(journal, {
            "event": "unknown_outcome", "utc": datetime.now(UTC).isoformat(),
            "client_order_id": order.client_order_id, "type": type(error).__name__,
        })
        # Even a 4xx waits for the existing signed reconciliation tool.
        raise TradingError("V4 order outcome unknown; signed reconciliation required") from error
    legacy.write_event(journal, {
        "event": "accepted", "utc": datetime.now(UTC).isoformat(),
        "client_order_id": order.client_order_id, "order_id": str(result["order_id"]),
    })
    return "submitted"


def run_once(client, journal, now, series, live=False, stop=False, authorize=None):
    if live:
        if authorize is None:
            raise TradingError("Live execution requires the release guard")
        authorize()
    deadline = time.monotonic() + caps.PASS_DEADLINE_SECONDS
    events, orders, state, context, lots, stopped = snapshot(client, journal, now)
    if live:
        legacy.record_execution(journal, events, set(orders), state["fills"], state["settlements"], {i["ticker"] for i in orders.values()})
    if stopped or stop:
        plans, data, reason = [], None, "risk_stop" if stopped else "kill"
    else:
        plans, data, reason = decision(client, events, orders, state, context, lots, now, series, deadline)
    keep, cancel = cancellations(state["resting"], orders, state["fills"], plans, now)
    report = {
        "version": policy.VERSION, "at": now.isoformat(), "mode": "live" if live else "preview",
        "decision": reason, "held_markets": len(lots), "cancel_count": len(cancel),
        "orders_planned": len(plans), "submitted": 0,
        "entries_blocked_by_inventory": bool(lots),
    }
    if not live:
        return report
    if cancel:
        for order, left in cancel:
            legacy.cancel_order(client, journal, order["order_id"], order["ticker"], "v4_reconcile_barrier", now, expected=left)
        report["decision"] = "canceled_waiting_for_fresh_account"
        return report
    for plan in plans:
        if (plan.ticker, plan.side) in keep:
            continue
        today = now.astimezone(legacy.NY).date()
        attempts = [e for e in events if e.get("event") == "intent"]
        if sum(instant(e["utc"]).astimezone(legacy.NY).date() == today for e in attempts) >= caps.MAX_SUBMISSIONS_PER_DAY:
            report["decision"] = "daily_submission_cap"
            break
        resting_cost = sum(
            Decimal(str(legacy.remaining_count(o, orders[str(o["order_id"])], state["fills"])))
            * (Decimal(orders[str(o["order_id"])] ["price_cents"]) / 100 + policy.fee_bound(data["fees"]))
            for o in state["resting"]
        )
        held_cost = sum((amount(x["left"]) * x["basis"] for queue in lots.values() for x in queue), Decimal(0))
        reserved = plan.quantity * (Decimal(plan.price) / 100 + policy.fee_bound(data["fees"], plan.immediate))
        if held_cost + resting_cost + reserved > min(policy.ACTIVE_CAP, Decimal(str(caps.MAX_ACTIVE_COST))):
            report["decision"] = "active_cost_cap"
            break
        report["decision"] = submit(client, journal, plan, data, now, deadline, authorize)
        report["submitted"] = int(report["decision"] == "submitted")
        break  # reread account before another order, including the second entry leg
    return report


def cancel_v4_on_halt(client, journal, now):
    """Only the v4 namespace, even when the shared ledger cannot be read."""
    emergency = journal.parent / "v4_emergency.jsonl"
    for order in client.orders("resting"):
        if str(order.get("client_order_id", "")).startswith("smm-spread-v4-"):
            legacy.cancel_order(client, emergency, order["order_id"], order["ticker"], "v4_halt", now)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--digest", action="store_true")
    parser.add_argument("--series", nargs="+", choices=caps.SERIES, default=list(caps.SERIES))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.digest:
        print(source_digest(root))
        return
    os.umask(0o077)
    client = TradingClient(dry_run=not args.live, env="prod")
    if args.live:
        guard(client, os.environ, root)
    with (STATE / "lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with production_lock.account_lock():
            try:
                report = run_once(client, STATE / "journal.jsonl", datetime.now(UTC), args.series, live=args.live, stop=os.path.lexists(STATE / "V4_KILL"), authorize=lambda: guard(client, os.environ, root))
            except Exception as error:
                report = {"version": policy.VERSION, "at": datetime.now(UTC).isoformat(), "decision": "halt", "error_class": type(error).__name__}
                if args.live:
                    try:
                        cancel_v4_on_halt(client, STATE / "journal.jsonl", datetime.now(UTC))
                    except Exception:
                        report["cancellation_unconfirmed"] = True
    target = STATE / "v4_last_scan.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    temporary.replace(target)
    print(json.dumps(report, sort_keys=True))
    if report.get("decision") == "halt":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
