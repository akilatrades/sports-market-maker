"""Exchange order status, partial fills, and missed-flow audits never invent fills."""

from datetime import UTC, datetime, timedelta

import pytest

from kalshi.trading import TradingError
from live.order_opportunity_audit import (
    audit_cohort,
    backfill_owned_orders,
    contra_volume,
)

NOW = datetime(2026, 10, 20, 1, 0, tzinfo=UTC)


def journal(count=4):
    return [
        {
            "event": "intent",
            "client_order_id": "c1",
            "ticker": "KXNFLRECYDS-TEST",
            "player": "Player",
            "count": count,
            "cost": 2.4,
            "price_cents": 60,
            "utc": (NOW - timedelta(hours=2)).isoformat(),
            "tip_utc": (NOW - timedelta(minutes=30)).isoformat(),
        },
        {
            "event": "accepted",
            "client_order_id": "c1",
            "order_id": "o1",
            "utc": (NOW - timedelta(hours=2)).isoformat(),
        },
        {"event": "queue", "order_id": "o1", "ahead": 15},
        {"event": "queue", "order_id": "o1", "ahead": 3},
    ]


def test_confirmed_unfilled_requires_exchange_zero_count():
    orders = [{"order_id": "o1", "status": "canceled", "fill_count_fp": "0"}]
    report = audit_cohort(journal(), orders, [], sport="nfl", now=NOW)
    assert report["confirmed_unfilled"] == 1
    assert report["fully_filled"] == 0
    order = report["orders"][0]
    assert order["queue_ahead_initial"] == 15
    assert order["queue_ahead_latest"] == 3
    assert order["exchange_status"] == "canceled"


def test_unknown_order_is_not_claimed_as_zero_fill():
    report = audit_cohort(journal(), [], [], sport="nfl", now=NOW)
    assert report["confirmed_unfilled"] == 0
    assert report["unknown_or_unreconciled"] == 1
    assert report["orders"][0]["state"] == "exchange_order_unavailable"


def test_canceled_without_exchange_fill_field_remains_uncertain():
    orders = [{"order_id": "o1", "status": "canceled"}]
    report = audit_cohort(journal(), orders, [], sport="nfl", now=NOW)
    assert report["confirmed_unfilled"] == 0
    assert report["unconfirmed_unfilled"] == 1


def test_partial_fill_not_called_unfilled():
    orders = [{"order_id": "o1", "status": "canceled", "fill_count_fp": "2"}]
    fills = [
        {"order_id": "o1", "fill_id": "f1", "count_fp": "2"},
        {"order_id": "o1", "fill_id": "f1", "count_fp": "2"},  # duplicate
    ]
    report = audit_cohort(journal(), orders, fills, sport="nfl", now=NOW)
    assert report["partially_filled"] == 1
    assert report["orders"][0]["filled_contracts"] == 2
    assert report["confirmed_unfilled"] == 0


def test_resting_and_complete_fills():
    orders = [{"order_id": "o1", "status": "resting", "fill_count_fp": "0"}]
    report = audit_cohort(journal(), orders, [], sport="nfl", now=NOW)
    assert report["resting_no_fill"] == 1
    filled = [{"order_id": "o1", "fill_id": "f1", "count_fp": "4"}]
    orders[0].update(status="executed", fill_count_fp="4")
    done = audit_cohort(journal(), orders, filled, sport="nfl", now=NOW)
    assert done["fully_filled"] == 1


def test_fill_count_disagreement_stops_false_confirmation():
    orders = [{"order_id": "o1", "status": "canceled", "fill_count_fp": "1"}]
    report = audit_cohort(journal(), orders, [], sport="nfl", now=NOW)
    assert report["orders"][0]["state"] == "unreconciled_fill_count"


def test_public_prints_are_only_opportunity_evidence():
    started = NOW - timedelta(hours=2)
    trades = [
        {
            "created_time": (NOW - timedelta(hours=1)).isoformat(),
            "taker_outcome_side": "yes",
            "yes_price_dollars": ".41",
            "count_fp": "3",
        },
        {
            "created_time": (NOW - timedelta(hours=1)).isoformat(),
            "taker_outcome_side": "no",
            "yes_price_dollars": ".80",
            "count_fp": "5",
        },
    ]
    assert contra_volume(trades, 0.60, started, NOW) == 3
    assert contra_volume(trades, 0.60, started, NOW - timedelta(minutes=90)) == 0
    assert contra_volume([{"created_time": None}], 0.60, started, NOW) is None


def test_unknown_fill_identity_refuses_incomplete_history():
    with pytest.raises(TradingError, match="fill ID"):
        audit_cohort(
            journal(),
            [{"order_id": "o1", "status": "canceled"}],
            [{"order_id": "o1", "count_fp": "1"}],
            sport="nfl",
            now=NOW,
        )


def test_archived_past_fill_detail_contains_real_execution_economics():
    now = NOW
    orders = [{"order_id": "o1", "status": "executed", "fill_count_fp": "4"}]
    fills = [
        {
            "order_id": "o1",
            "fill_id": "f1",
            "count_fp": "2",
            "no_price_dollars": "0.6000",
            "fee_cost": "0.0100",
            "is_taker": False,
            "created_time": (NOW - timedelta(minutes=95)).isoformat(),
        },
        {
            "order_id": "o1",
            "fill_id": "f2",
            "count_fp": "2",
            "no_price_dollars": "0.6200",
            "fee_cost": "0.0200",
            "is_taker": False,
            "created_time": (NOW - timedelta(minutes=85)).isoformat(),
        },
    ]
    audit = audit_cohort(journal(), orders, fills, sport="nfl", now=now)
    assert audit["fully_filled"] == 1
    assert audit["fill_records"] == 2
    assert audit["filled_contracts"] == 4
    order = audit["orders"][0]
    assert order["vwap_no_price_dollars"] == 0.61
    assert order["fill_fees_dollars"] == 0.03
    assert order["maker_filled_contracts"] == 4
    assert order["first_fill_utc"] != order["last_fill_utc"]


def test_missing_fee_and_maker_metadata_remain_unknown():
    fills = [
        {"order_id": "o1", "fill_id": "f1", "count_fp": "4", "no_price_dollars": "0.6"}
    ]
    orders = [{"order_id": "o1", "status": "executed", "fill_count_fp": "4"}]
    row = audit_cohort(journal(), orders, fills, sport="nba", now=NOW)["orders"][0]
    assert row["state"] == "fully_filled"
    assert row["fill_fees_dollars"] is None
    assert row["maker_filled_contracts"] is None


def test_individual_order_signed_backfill_recovers_old_closed_order(monkeypatch):
    from live import order_opportunity_audit as module

    module._CLOSED_ORDER_CACHE.clear()

    class SignedReads:
        def __init__(self):
            self.calls = []

        def _request(self, method, path):
            self.calls.append((method, path))
            assert method == "GET"
            return {
                "order": {"order_id": "o1", "status": "canceled", "fill_count_fp": "0"}
            }

    client = SignedReads()
    result = backfill_owned_orders(client, {"nfl": journal(), "nba": []}, [])
    assert result[0]["order_id"] == "o1"
    assert client.calls == [("GET", "/portfolio/orders/o1")]
    result = backfill_owned_orders(client, {"nfl": journal()}, [])
    assert len(result) == 1
    assert len(client.calls) == 1
    module._CLOSED_ORDER_CACHE.clear()


def test_signed_exchange_expiry_can_confirm_tip_independently_of_journal():
    events = journal()
    tip = NOW - timedelta(minutes=30)
    events[0]["expiration_ts"] = int((tip - timedelta(hours=2)).timestamp())
    signed_order = {
        "order_id": "o1",
        "status": "executed",
        "fill_count_fp": "4",
        "expiration_time": tip.isoformat(),
    }
    signed_fills = [{"order_id": "o1", "fill_id": "f1", "count_fp": "4"}]
    row = audit_cohort(events, [signed_order], signed_fills, sport="nba", now=NOW)[
        "orders"
    ][0]
    assert row["signed_exchange_expiry_matches_tip"] is True
    assert row["signed_exchange_expiry_matches_intent"] is False
    assert row["expiration_utc"] != row["signed_exchange_expiration_utc"]


def test_exchange_expiry_absence_cannot_prove_tipoff():
    signed = {"order_id": "o1", "status": "canceled", "fill_count_fp": "0"}
    row = audit_cohort(journal(), [signed], [], sport="nba", now=NOW)["orders"][0]
    assert row["signed_exchange_expiration_utc"] is None
    assert row["signed_exchange_expiry_matches_tip"] is None
    assert row["signed_exchange_expiry_matches_intent"] is None


def test_signed_exchange_unix_expiry_and_corrupt_time():
    from live.order_opportunity_audit import exchange_expiration

    tip = NOW - timedelta(minutes=30)
    assert exchange_expiration({"expiration_time": int(tip.timestamp())}) == tip
    assert exchange_expiration({"expiration_ts": str(int(tip.timestamp()))}) == tip
    assert exchange_expiration({"expiration_time": "malformed"}) is None
    assert exchange_expiration({"expiration_time": 999999999999999}) is None
    assert exchange_expiration({"expiration_time": True}) is None
