"""Economic and execution invariants of the isolated completion pilot."""

import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from kalshi.trading import Order, TradingError
from live import spread_completion as p
from live import shared_account_risk as shared
from research.spread_forward_core import EvidenceError

NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)
FEES = {"fee_type": "quadratic", "fee_multiplier": 1}


def book(yes="0.40", no="0.50", depth="20"):
    return {"yes": [[yes, depth]], "no": [[no, depth]]}


def lot(side="yes", price="0.40", qty="1", age=10):
    return {
        "side": side,
        "basis": D(price),
        "left": qty,
        "at": NOW - timedelta(minutes=age),
    }


def journal_fill(side="yes", count="1", price="0.40", fee="0.01", oid="o"):
    intent = {
        "event": "intent",
        "utc": (NOW - timedelta(minutes=15)).isoformat(),
        "client_order_id": oid,
        "ticker": "M",
        "event_ticker": "E",
        "side": side,
        "price_cents": 50,
        "count": count,
        "strategy_version": p.VERSION,
        "fee_bound_per_contract": "0.03",
    }
    fill = {
        "order_id": oid,
        "fill_id": oid,
        "created_time": (NOW - timedelta(minutes=10)).isoformat(),
        "ticker": "M",
        "outcome_side": side,
        "book_side": "bid" if side == "yes" else "ask",
        "count_fp": count,
        "yes_price_dollars": price if side == "yes" else str(1 - D(price)),
        "no_price_dollars": price if side == "no" else str(1 - D(price)),
        "fee_cost": fee,
    }
    return [
        intent,
        {"event": "accepted", "client_order_id": oid, "order_id": oid},
    ], fill


def test_narrow_book_still_gets_completion_quote():
    quote, reason = p.completion_quote(
        "M", [lot()], book("0.40", "0.57"), FEES, NOW + timedelta(hours=3), NOW
    )
    assert reason == "completing"
    assert quote.side == "no" and quote.quantity == 1 and quote.purpose == "complete"
    assert quote.price == 57  # cost basis, not the old 8c entry-width filter
    assert D(1) - D("0.40") - D(quote.price) / 100 - p.fee_bound(FEES) >= p.TARGET


@pytest.mark.parametrize(
    "side,depth", [("yes", book("0.60", "0.35")), ("no", book("0.35", "0.60"))]
)
def test_take_available_net_profit_with_reduce_only_ioc(side, depth):
    quote, _ = p.completion_quote(
        "M", [lot(side)], depth, FEES, NOW + timedelta(hours=2), NOW
    )
    assert quote.immediate and quote.purpose == "take_profit"
    assert quote.side != side and quote.quantity == 1
    assert D(1) - D("0.40") - D(quote.price) / 100 - p.fee_bound(FEES, True) >= p.TARGET


def test_partial_inventory_never_rounds_up_or_changes_side():
    quote, _ = p.completion_quote(
        "M", [lot(qty="0.13")], book(), FEES, NOW + timedelta(hours=2), NOW
    )
    assert quote.quantity == D("0.13") and quote.side == "no"
    body = Order("M", "no", quote.quantity, quote.price, fractional=True).body()
    assert body["count"] == "0.13"


def test_timeout_uses_bounded_loss_and_can_fail_to_exit():
    quote, reason = p.completion_quote(
        "M", [lot(age=60)], book("0.40", "0.50"), FEES, NOW + timedelta(hours=2), NOW
    )
    assert (
        quote.immediate
        and quote.purpose == "timeout_exit"
        and reason == "inventory_timeout"
    )
    assert (
        D(1) - D("0.40") - D(quote.price) / 100 - p.fee_bound(FEES, True)
        >= -p.LOSS_ALLOWANCE
    )
    quote, reason = p.completion_quote(
        "M", [lot(age=60)], book("0.10", "0.80"), FEES, NOW + timedelta(hours=2), NOW
    )
    assert quote is None and reason == "exit_price_floor_blocked"


def test_start_cutoff_overrides_age_and_no_exit_after_event_start():
    quote, _ = p.completion_quote(
        "M", [lot(age=1)], book(), FEES, NOW + timedelta(minutes=20), NOW
    )
    assert quote.purpose == "timeout_exit"
    quote, reason = p.completion_quote("M", [lot(age=1)], book(), FEES, NOW, NOW)
    assert quote is None and reason == "event_started_unmatched"


def test_worst_lot_basis_protects_every_partial_completion():
    quote, _ = p.completion_quote(
        "M",
        [lot(price="0.40", qty="0.5"), lot(price="0.55", qty="0.5")],
        book("0.35", "0.40"),
        FEES,
        NOW + timedelta(hours=2),
        NOW,
    )
    assert quote.price <= 42 and quote.quantity == 1


def test_entry_requires_depth_low_exit_cost_known_fees_and_pregame():
    market = {"ticker": "M"}
    assert len(p.entry_quotes(market, book(), FEES, NOW + timedelta(hours=2), NOW)) == 2
    assert not p.entry_quotes(
        market, book(depth="9"), FEES, NOW + timedelta(hours=2), NOW
    )
    assert not p.entry_quotes(
        market, book("0.45", "0.50"), FEES, NOW + timedelta(hours=2), NOW
    )
    assert not p.entry_quotes(market, book(), FEES, NOW + timedelta(minutes=84), NOW)
    with pytest.raises(EvidenceError):
        p.entry_quotes(
            market,
            book(),
            {"fee_type": "flat", "fee_multiplier": 1},
            NOW + timedelta(hours=2),
            NOW,
        )


def test_fifo_uses_actual_improved_price_and_allocated_fees():
    events, fill = journal_fill(count="1", price="0.40", fee="0.01")
    e2, f2 = journal_fill("no", count="0.25", price="0.45", fee="0.002", oid="close")
    f2["created_time"] = (NOW - timedelta(minutes=5)).isoformat()
    lots = p.inventory(events + e2, [fill, f2, fill], {"M": 0.75}, set(), NOW)
    assert lots["M"][0]["left"] == "0.75"
    assert lots["M"][0]["basis"] == D("0.41")
    assert lots["M"][0]["at"] == NOW - timedelta(minutes=10)
    ledger = shared.spread_ledger(events + e2, [fill, f2], [], NOW)
    assert ledger["cumulative"] == pytest.approx(0.0255)  # .25*.15 - .012 fees
    assert ledger["open"]["M"][0][1] == 0.4


@pytest.mark.parametrize(
    "problem",
    [
        "fees",
        "direction",
        "future",
        "position",
        "history",
        "excess_quantity",
        "excess_fee",
    ],
)
def test_uncertain_accounting_fails_closed(problem):
    events, fill = journal_fill()
    positions = {"M": 1}
    if problem == "fees":
        del fill["fee_cost"]
    elif problem == "direction":
        fill["outcome_side"] = "no"
    elif problem == "future":
        fill["created_time"] = (NOW + timedelta(seconds=1)).isoformat()
    elif problem == "position":
        positions["M"] = 0.5
    elif problem == "history":
        events.append({"event": "fill", "order_id": "o", "fill_id": "missing"})
    elif problem == "excess_quantity":
        fill["count_fp"] = "2"
    else:
        fill["fee_cost"] = "0.10"
    with pytest.raises(EvidenceError):
        p.inventory(events, [fill], positions, set(), NOW)


def test_legacy_position_is_not_silently_adopted():
    events, fill = journal_fill()
    events[0]["strategy_version"] = "spread-maker-v3-24h-starts"
    with pytest.raises(EvidenceError, match="inventory"):
        p.inventory(events, [fill], {"M": 1}, set(), NOW)


def test_completion_can_take_existing_depth_in_a_one_sided_book():
    depth = {"yes": [["0.60", "1"]], "no": []}
    quote, _ = p.completion_quote(
        "M", [lot()], depth, FEES, NOW + timedelta(hours=2), NOW
    )
    assert quote.immediate and quote.purpose == "take_profit"
    assert quote.side == "no"


def test_empty_depth_is_a_blocked_timeout_not_an_invented_fill():
    quote, reason = p.completion_quote(
        "M",
        [lot(age=61)],
        {"yes": [], "no": []},
        FEES,
        NOW + timedelta(hours=2),
        NOW,
    )
    assert quote is None and reason == "exit_price_floor_blocked"


def test_shared_ledger_keeps_legacy_validation_and_checks_v4_limits():
    events, fill = journal_fill()
    bad = copy.deepcopy(events)
    bad[0]["strategy_version"] = "spread-maker-v3-24h-starts"
    with pytest.raises(TradingError, match="price"):
        shared.spread_ledger(bad, [fill], [], NOW)
    events[0]["price_cents"] = 39
    with pytest.raises(TradingError, match="Unverifiable"):
        shared.spread_ledger(events, [fill], [], NOW)


def test_ioc_wire_contract_and_no_passive_reduce_only():
    body = Order(
        "M",
        "no",
        D("0.25"),
        55,
        fractional=True,
        post_only=False,
        reduce_only=True,
        time_in_force="immediate_or_cancel",
    ).body()
    assert body["side"] == "ask" and body["price"] == "0.4500"
    assert body["count"] == "0.25" and body["reduce_only"] is True
    assert "expiration_time" not in body
    with pytest.raises(TradingError):
        Order("M", "yes", 1, 40, reduce_only=True).body()
    with pytest.raises(TradingError):
        Order("M", "yes", 1, 40, time_in_force="immediate_or_cancel").body()
    with pytest.raises(TradingError):
        Order("M", "yes", D("0.001"), 40, fractional=True).body()
