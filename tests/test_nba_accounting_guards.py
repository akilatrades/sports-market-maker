"""Risk release and settlement circuit-breaker regression tests.

These tests never call the live Kalshi API. Missing/ambiguous data must
preserve active reservations or stop new orders, not increase budget.
"""

from datetime import UTC, datetime, timedelta

import pytest

from kalshi.trading import TradingError
from live import prod_nba_auto as nba

NOW = datetime(2026, 10, 20, 20, 0, tzinfo=UTC)
TICKER = "KXNBA-TEST-GAME-PLAYER"
ORDER_ID = "oid-123"
INTENT = {
    "client_order_id": "cid-123",
    "ticker": TICKER,
    "expiration_ts": int((NOW + timedelta(hours=1)).timestamp()),
    "tip_utc": (NOW + timedelta(hours=1)).isoformat(),
    "cost": 1.50,
}
ACCEPTED = {"cid-123": {"order_id": ORDER_ID}}


def state(*, resting=None, held=None):
    return {
        "resting": resting if resting is not None else [],
        "held": held if held is not None else [],
        "settled": set(),
    }


def cancel():
    return [{"event": "cancel_accepted", "order_id": ORDER_ID}]


def test_cancel_ack_without_signed_reconciliation_does_not_release():
    for waiting, fills, held in [
        ([{"order_id": ORDER_ID}], [], []),
        ([], [{"order_id": ORDER_ID, "ticker": TICKER}], []),
        ([], [], [TICKER]),
    ]:
        active, released = nba.reconcile_expired_unfilled(
            [INTENT], ACCEPTED, state(resting=waiting, held=held),
            fills, NOW, events=cancel()
        )
        assert len(active) == 1
        assert released == 0


def test_verified_zero_fill_cancel_recycles_active_not_submitted_budget():
    active, released = nba.reconcile_expired_unfilled(
        [INTENT], ACCEPTED, state(), [], NOW, events=cancel()
    )
    assert active == []
    assert released == 1
    row = type("Row", (), {"game_id": "NEXT", "team": "OTHER"})()
    prior = [{
        **INTENT,
        "utc": NOW.isoformat(),
        "game_id": "PREVIOUS",
        "team": "OTHER",
    }]
    # The cancelled submission remains charged to lifetime/daily quotas.
    assert nba.budget_blockers(prior, [], row, 74.0, NOW)


def test_missing_cancel_ack_preserves_active_until_original_expiry_buffer():
    active, released = nba.reconcile_expired_unfilled(
        [INTENT], ACCEPTED, state(), [], NOW
    )
    assert len(active) == 1 and released == 0
    later = NOW + timedelta(hours=1, minutes=11)
    active, released = nba.reconcile_expired_unfilled(
        [INTENT], ACCEPTED, state(), [], later
    )
    assert active == [] and released == 1


def settled(ticker=TICKER, pnl=-2.0, when=NOW):
    # revenue - yes_total_cost - no_total_cost - fee_cost == pnl
    return {
        "market_ticker": ticker,
        "settled_time": when.isoformat(),
        "revenue_dollars": "0.00",
        "yes_total_cost_dollars": "0.00",
        "no_total_cost_dollars": str(abs(pnl)),
        "fee_cost": "0.00",
    }


def test_realized_loss_daily_stop_and_deduplicated_snapshot():
    settlements = [
        settled("KXNBA-ONE", -7),
        settled("KXNBA-TWO", -6),
    ]
    owned = {"KXNBA-ONE", "KXNBA-TWO"}
    report = nba.nba_realized_pnl(settlements, owned, NOW)
    assert report["daily_realized_pnl_dollars"] == -13
    assert report["loss_stop"] is True
    assert report["settlement_records"] == 2
    duplicated = nba.nba_realized_pnl(settlements * 2, owned, NOW)
    assert duplicated == report


def test_realized_loss_cumulative_stop_and_ignore_nfl():
    yesterday = NOW - timedelta(days=1)
    settlements = [settled(f"KXNBA-{i}", -6, yesterday) for i in range(5)]
    settlements.append(settled("KXNFL-UNRELATED", -500))
    report = nba.nba_realized_pnl(
        settlements, {s["market_ticker"] for s in settlements[:-1]}, NOW
    )
    assert report["daily_realized_pnl_dollars"] == 0
    assert report["cumulative_realized_pnl_dollars"] == -30
    assert report["loss_stop"] is True


@pytest.mark.parametrize("change", [
    {"fee_cost": None},
    {"settled_time": ""},
    {"no_total_cost_dollars": None},
    {"settled_time": (NOW + timedelta(days=1)).isoformat()},
])
def test_incomplete_or_future_settlement_blocks_new_orders(change):
    result = {**settled(), **change}
    with pytest.raises(TradingError):
        nba.nba_realized_pnl([result], {TICKER}, NOW)


def test_conflicting_duplicate_settlements_fail_closed():
    first, second = settled(), settled(pnl=-3)
    with pytest.raises(TradingError, match="Conflicting"):
        nba.nba_realized_pnl([first, second], {TICKER}, NOW)
