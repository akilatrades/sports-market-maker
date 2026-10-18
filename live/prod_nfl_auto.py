"""Bounded unattended NFL production experiment. NOT the general-purpose trader.

This worker is isolated from the Demo service and has a lifetime *gross-cost*
budget below $50 including a fee buffer. One new post-only order max per pass,
no automatic re-arming, and durable journal before each network write. Fail
closed on inconsistent balances, orders, positions, fills or model data.
"""

import argparse
import fcntl
import json
import math
import os
import resource
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from kalshi.api import fetch_market
from kalshi.paper_props import candidate_orders
from kalshi.trading import Order, TradingClient, TradingError
from live.nfl_policy import (
    FEE_RESERVE,
    MAX_ACTIVE_COST,
    MAX_CONTRACTS,
    MAX_DAILY_COST,
    MAX_GAME_COST,
    MAX_GAME_ORDERS,
    MAX_GROSS_COST,
    MAX_ORDER_COST,
    MAX_TEAM_COST,
    MIN_RESERVED_EDGE,
    STATE,
    STRATEGY_VERSION,
    money,
    reserve,
    settlement_accounting,
)

WINDOW = (1 / 6, 2.0)  # latest entry: 10 minutes before kickoff
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


def reconcile_expired_unfilled(attempts, accepted, state, fills, now):
    """Release *active* capacity only on robust evidence of zero execution.

    Full historical attempt cost still counts toward the lifetime and daily
    gross-spend caps. Never release recent, partially filled, resting, or
    unaccounted orders. Check the exchange again on every subsequent pass.
    """
    still_active = []
    resting_ids = {str(o.get("order_id")) for o in state["resting"]}
    held_tickers = set(state["held"])
    filled_ids = {str(f.get("order_id")) for f in fills if f.get("order_id")}
    filled_tickers = {
        str(f.get("ticker") or f.get("market_ticker"))
        for f in fills
        if f.get("ticker") or f.get("market_ticker")
    }
    from datetime import timedelta

    released = 0
    for attempt in attempts:
        ticker = attempt["ticker"]
        if ticker in state["settled"]:
            continue
        match = accepted.get(attempt["client_order_id"])
        if not match:
            raise TradingError("Unaccepted attempt: HALT")
        oid = str(match["order_id"])
        tip = pd.Timestamp(attempt["tip_utc"])
        # Require 10 extra minutes after nominal expiration to tolerate late
        # exchange events. No history, no balance release.
        can_release = (
            pd.notna(tip)
            and now >= tip.to_pydatetime() + timedelta(minutes=10)
            and oid not in resting_ids
            and oid not in filled_ids
            and ticker not in filled_tickers
            and ticker not in held_tickers
        )
        if can_release:
            released += 1
        else:
            still_active.append(attempt)
    return still_active, released


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
    seen_results = {
        e.get("ticker"): e for e in events if e.get("event") == "settlement"
    }
    for fill in fills:
        oid = fill.get("order_id")
        fid = fill.get("fill_id") or fill.get("trade_id")
        if not fid or fid in seen_fills or oid not in known_orders:
            continue
        write_event(
            journal,
            {
                "event": "fill",
                "fill_id": str(fid),
                "utc": str(fill.get("created_time", "")),
                "ticker": str(fill.get("ticker") or fill.get("market_ticker") or ""),
                "order_id": str(oid),
                "count": str(fill.get("count_fp", "")),
                "yes_price": str(fill.get("yes_price_dollars", "")),
                "no_price": str(fill.get("no_price_dollars", "")),
                "fee": str(fill.get("fee_cost", "")),
                "is_taker": fill.get("is_taker"),
            },
        )
        seen_fills.add(fid)
    for result in settlements:
        ticker = result.get("market_ticker") or result.get("ticker")
        if ticker not in tickers:
            continue
        record = {
            "event": "settlement",
            "ticker": ticker,
            "utc": str(result.get("settled_time", "")),
            **settlement_accounting(result),
        }
        # Append a correction for older/incomplete records; never rewrite history.
        if record != seen_results.get(ticker):
            write_event(journal, record)
            seen_results[ticker] = record


def record_queue_observation(client, journal, order_id, now):
    """Read an owned order's queue without allowing a telemetry error to trade."""
    try:
        queue = client.queue_position(str(order_id))
        if queue is not None and (not math.isfinite(queue) or queue < 0):
            queue = None
        issue = None if queue is not None else "missing_or_invalid_queue_field"
    except Exception as error:
        import re

        match = re.search(r"-> HTTP ([0-9]{3})", str(error))
        queue = None
        issue = f"HTTP_{match.group(1)}" if match else type(error).__name__
    write_event(
        journal,
        {
            "event": "queue",
            "utc": now.isoformat(),
            "order_id": str(order_id),
            "ahead": queue,
            "issue": issue,
        },
    )


# Guardrail for the small pilot. No change to maker/taker status or risk caps.
# Only improve a quote by a second tick in a spread wide enough to stay passive.
EXTRA_MAKER_TICK = 0.01
MIN_EDGE_AFTER_IMPROVEMENT = 0.03


def execution_quote(candidate):
    """Choose a better maker quote only if the existing book/model edge covers it.

    candidate.edge already includes estimated maker fees, and where available
    uses sportsbook probability rather than model-only probability. Preserve
    at least three percentage points of that estimated edge after improving.
    """
    base = float(candidate.price)
    original_edge = float(candidate.edge)
    bid, ask = float(candidate.yes_bid), float(candidate.yes_ask)
    if not all(math.isfinite(v) for v in (base, original_edge, bid, ask)):
        raise TradingError("Nonfinite execution quote")
    if not 0 < bid < ask < 1:
        raise TradingError("Invalid execution market spread")
    spread_cents = round((ask - bid) * 100)
    if abs(spread_cents - (ask - bid) * 100) > 0.0001:
        raise TradingError("Non-cent price spread in maker experiment")
    # Baseline is already inside 2c+ spreads by one tick.
    # A second tick must never reach/cross the opposing YES bid.
    proposed = round(base + EXTRA_MAKER_TICK, 2)
    remaining_edge = round(original_edge - EXTRA_MAKER_TICK, 5)
    take_second_tick = (
        spread_cents >= 3
        and remaining_edge >= MIN_EDGE_AFTER_IMPROVEMENT
        and proposed <= 0.90
        and round(1 - proposed, 2) > round(bid, 2)
    )
    return (
        proposed if take_second_tick else base,
        remaining_edge if take_second_tick else original_edge,
        int(take_second_tick),
    )


def verify_quote(candidate, proposed_no_price=None):
    """Re-read production quote and ensure selected maker price is still passive."""
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
    price = (
        float(candidate.price)
        if proposed_no_price is None
        else float(proposed_no_price)
    )
    if price < expected - 0.001 or price > expected + EXTRA_MAKER_TICK + 0.001:
        raise TradingError("Proposed NO price does not match verified snapshot")
    # A buy NO is a sell YES ask at 1 - price. Resting order must be priced
    # strictly above the YES bid to stay maker-only.
    if round(1 - price, 2) <= round(bid, 2):
        raise TradingError("Proposed maker quote would cross the YES bid")


def select_candidates(frame, events, state, now, diagnostics=None):
    attempts, _ = records(events)
    counts = diagnostics if diagnostics is not None else {}
    counts["open_markets"] = len(frame)
    if frame.empty:
        return []
    verified = frame[frame.injury_status.fillna("").eq("") & frame.tip_utc.notna()]
    counts["verified_availability_and_time"] = len(verified)
    in_window = verified[verified.hours_to_tip.between(*WINDOW)]
    counts["in_entry_window"] = len(in_window)
    eligible = in_window[
        in_window.ticker.astype(str).str.startswith(("KXNFLRECYDS-", "KXNFLANYTD-"))
    ]
    counts["eligible_series"] = len(eligible)
    if eligible.empty:
        return []
    found = candidate_orders(eligible, "no_seller_bookline", window=WINDOW)
    counts["passed_book_or_model_and_spread"] = len(found)
    if found.empty:
        return []
    found = found[found.side.eq("no")].copy()
    found["edge"] = pd.to_numeric(found.edge, errors="coerce")
    # Extremely large modeled edges are suspicious: wrong player, mismatched
    # line, or stale sportsbook feed. Such markets need human review.
    found = found[found.edge.between(0, 0.15)]
    counts["passed_outlier_check"] = len(found)
    already = {a["ticker"] for a in attempts}
    found = found[~found.ticker.isin(already)]
    counts["not_previously_attempted"] = len(found)
    if found.empty:
        return []
    return list(found.sort_values("edge", ascending=False).itertuples())


def order_from_row(row, now, no_price=None):
    price = float(row.price) if no_price is None else float(no_price)
    cents = round(price * 100)
    if not math.isfinite(price) or abs(cents - price * 100) > 1e-6:
        raise TradingError("Order price not a whole cent")
    if not 10 <= cents <= 90:
        raise TradingError("Order price outside safe 10c–90c range")
    count = min(int((MAX_ORDER_COST + 1e-8) // price), MAX_CONTRACTS)
    if count <= 0:
        raise TradingError("Zero affordable contracts")
    tip = pd.Timestamp(row.tip_utc)
    if pd.isna(tip) or int(tip.timestamp()) < int(now.timestamp()) + 10 * 60:
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


def pre_submit_kickoff_ok(tip_utc, now):
    """Fail closed on the wall clock, not the earlier two-minute scan start.

    A 30-second submission buffer prevents slow API calls from pushing
    accepted orders past the intended ten-minute pre-kickoff cutoff.
    """
    from datetime import timedelta

    tip = pd.Timestamp(tip_utc)
    if pd.isna(tip):
        return False
    try:
        return tip.to_pydatetime() > now + timedelta(minutes=10, seconds=30)
    except (TypeError, ValueError):
        return False


def budget_blockers(attempts, active, row, cost, now):
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
    checks = {
        "lifetime_submission_budget": total + r <= MAX_GROSS_COST + 1e-9,
        "active_exposure": open_now + r <= MAX_ACTIVE_COST + 1e-9,
        "game_budget": game_cost + r <= MAX_GAME_COST + 1e-9,
        "team_budget": team_cost + r <= MAX_TEAM_COST + 1e-9,
        "daily_submission_budget": day_cost + r <= MAX_DAILY_COST + 1e-9,
        "game_order_count": game_orders < MAX_GAME_ORDERS,
    }
    return [name for name, fits in checks.items() if not fits]


def room_for(attempts, active, row, cost, now):
    return not budget_blockers(attempts, active, row, cost, now)


def fit_order_to_budget(order, attempts, active, row, now):
    """Reduce quantity until cost plus reserve fits every existing cap."""
    for count in range(order.count, 0, -1):
        cost = round(count * order.price_cents / 100, 2)
        if room_for(attempts, active, row, cost, now):
            order.count = count
            return cost
    return None


def entry_evidence(row, order, cost):
    """Require 3c of modeled advantage AFTER the existing full fee buffer.

    This is a conservative admission rule, not a claim about true probabilities
    or the actual exchange fee. Do not optimize it against a single NFL game.
    """
    from markets.nfl.paper import MAX_MODEL_AGE_HOURS

    stamp = pd.to_datetime(
        getattr(row, "model_made_utc", None), utc=True, errors="coerce"
    )
    if stamp is None or pd.isna(stamp):
        raise TradingError("model_timestamp_missing_or_stale")
    age = (pd.Timestamp(datetime.now(UTC)) - stamp).total_seconds() / 3600
    if not 0 <= age <= MAX_MODEL_AGE_HOURS:
        raise TradingError("model_timestamp_missing_or_stale")
    model = float(row.p_model)
    book = getattr(row, "p_book", None)
    covered = book is not None and pd.notna(book)
    probability = float(book) if covered else model
    if not all(math.isfinite(p) and 0 <= p <= 1 for p in (model, probability)):
        raise TradingError("invalid_probability")
    net = 1 - probability - reserve(cost) / order.count
    if net < MIN_RESERVED_EDGE - 1e-9:
        raise TradingError("insufficient_edge_after_fee_buffer")
    return {
        "strategy_version": STRATEGY_VERSION,
        "probability_source": "sportsbook" if covered else "model",
        "p_yes_used": probability,
        "p_model_yes": model,
        "model_made_utc": stamp.isoformat(),
        "edge_after_fee_buffer": round(net, 6),
        "fee_buffer_dollars": round(reserve(cost) - cost, 2),
    }


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
    diagnostics = {}
    candidates = select_candidates(frame, events, state, now, diagnostics)
    skipped = Counter()

    def finish(decision, *, placed=False, **details):
        report = {
            "run_utc": datetime.now(UTC).isoformat(),
            "env": "prod",
            "mode": "dry" if dry else "live",
            "strategy_version": STRATEGY_VERSION,
            "min_edge_after_fee_buffer": MIN_RESERVED_EDGE,
            "decision": decision,
            "filters": diagnostics,
            "skip_reasons": dict(skipped),
            **details,
        }
        print("NFL SCAN", json.dumps(report, sort_keys=True))
        if not dry:
            target = journal.with_name("last_scan.json")
            temporary = target.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(report, indent=2) + "\n")
            temporary.chmod(0o600)
            temporary.replace(target)
        return placed

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
        active, released = reconcile_expired_unfilled(
            attempts, accepted, state, fills, now
        )
        state["active"] = active
        if released:
            print(
                f"PROD AUTO: {released} verified unfilled expired orders freed from active capacity"
            )
        record_execution(
            journal,
            load_journal(journal),
            attempts,
            accepted,
            fills,
            state["settlements"],
        )
        canceled = cancel_invalid_resting(client, journal, state, frame, now)
        if canceled:
            print(f"PROD AUTO: canceled {canceled} unsafe resting orders")
            # Require another reconciliation pass after cancellation.
            return finish("availability_cancellation", canceled=canceled)
        for resting in state["resting"]:
            record_queue_observation(client, journal, resting["order_id"], now)
        print(
            f"PROD AUTO: attempts={len(attempts)}, resting={len(state['resting'])}, "
            f"held={len(state['held'])}, settled_tickers={len(state['settled'])}, "
            f"fills={len(fills)}, gross_reserved=${sum(reserve(a['cost']) for a in attempts):.2f}/${MAX_GROSS_COST:.0f}"
        )
    if not candidates:
        print("No eligible late-window NFL opportunities")
        return finish("no_eligible_candidates")
    for row in candidates:
        try:
            quoted, execution_edge, extra_ticks = execution_quote(row)
            order, cost = order_from_row(row, now, no_price=quoted)
        except TradingError:
            skipped["invalid_order_or_price"] += 1
            continue
        cost = fit_order_to_budget(order, attempts, state["active"], row, now)
        if cost is None:
            skipped.update(
                budget_blockers(
                    attempts, state["active"], row, order.price_cents / 100, now
                )
            )
            continue
        try:
            evidence = entry_evidence(row, order, cost)
        except TradingError as error:
            # If the optional second tick consumes the remaining edge, retain
            # the baseline passive quote instead of chasing a fill.
            if extra_ticks and str(error) == "insufficient_edge_after_fee_buffer":
                quoted, extra_ticks = float(row.price), 0
                execution_edge = float(row.edge)
                order, cost = order_from_row(row, now, no_price=quoted)
                cost = fit_order_to_budget(order, attempts, state["active"], row, now)
                if cost is None:
                    skipped["baseline_budget"] += 1
                    continue
                try:
                    evidence = entry_evidence(row, order, cost)
                except TradingError as baseline_error:
                    skipped[str(baseline_error)] += 1
                    continue
            else:
                skipped[str(error)] += 1
                continue
        try:
            verify_quote(row, quoted)
        except TradingError:
            skipped["fresh_quote_check"] += 1
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
                        "extra_maker_ticks": extra_ticks,
                        "edge_after_quote": round(execution_edge, 4),
                    },
                    sort_keys=True,
                ),
            )
            return finish("public_candidate_only")

        # The candidate scan can take minutes. Check the actual wall clock
        # immediately before the irreversible order intent and network POST,
        # rather than the start of the scan, or late entries can slip through.
        if not pre_submit_kickoff_ok(row.tip_utc, datetime.now(UTC)):
            skipped["kickoff_cutoff"] += 1
            print(
                f"Skipped {order.ticker}: too close to verified kickoff at submission"
            )
            continue

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
                "edge": round(execution_edge, 4),
                "baseline_edge": round(float(row.edge), 4),
                "extra_maker_ticks": extra_ticks,
                "player": str(getattr(row, "player", "")),
                **evidence,
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
        record_queue_observation(client, journal, result["order_id"], datetime.now(UTC))
        return finish(
            "exchange_accepted",
            placed=True,
            ticker=order.ticker,
            contracts=order.count,
            cost_dollars=cost,
            reserved_dollars=reserve(cost),
        )
    print("No opportunities fit remaining production risk budget or fresh quotes")
    return finish("all_candidates_blocked")


def main():
    from contextlib import nullcontext
    from live.production_lock import account_lock

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
    with (account_lock() if args.live else nullcontext()), (directory / "lock").open("a+") as lock:
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
            last_scan = directory / "last_scan.json"
            if last_scan.exists():
                print("Last completed scan (check run_utc for freshness):")
                print(last_scan.read_text())
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
        now = datetime.now(UTC)
        print(f"NFL WORKER: started {now.isoformat()}", flush=True)
        from live.nfl_trade import candidates

        frame = candidates(now)
        peak_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        print(f"NFL WORKER: inputs ready; peak RSS {peak_mib:.1f} MiB", flush=True)
        pass_once(client, os.environ, frame, now, journal, dry=args.dry_run)
        print("NFL WORKER: completed", flush=True)


if __name__ == "__main__":
    main()
