"""Offline regression tests: rejected orders must remain in cumulative budgets."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from kalshi.trading import TradingError
from live import prod_nba_auto as nba
from live import shared_account_risk as shared
from live.reconciled_attempts import rejected_client_ids
from tools.reconcile_rejected_nba import verify

NOW = datetime(2026, 10, 20, 15, 30, tzinfo=UTC)
CID = "smm-test-rejected"
TICKER = "KXNBAPTS-TEST-NO"


def events(reconciled=False):
    e = [
        {
            "event": "intent",
            "utc": (NOW - timedelta(hours=2)).isoformat(),
            "ticker": TICKER,
            "client_order_id": CID,
            "cost": 2.0,
            "count": 4,
            "game_id": "g",
            "team": "NY",
            "tip_utc": (NOW + timedelta(hours=5)).isoformat(),
            "expiration_ts": int((NOW + timedelta(hours=1)).timestamp()),
        },
        {"event": "unknown_outcome", "client_order_id": CID, "type": "TradingError"},
    ]
    if reconciled:
        e.append(
            {
                "event": "reconciled_rejected",
                "utc": NOW.isoformat(),
                "client_order_id": CID,
                "evidence": "signed_get_no_order_fill_position_and_owner_ui",
                "submission_http_status": 404,
            }
        )
    return e


def test_unresolved_submission_still_halts_both_cohorts():
    with pytest.raises(TradingError, match="Uncertain"):
        nba.records(events())
    with pytest.raises(TradingError, match="Ambiguous"):
        shared.ownership({"nba": events(), "nfl": []})


def test_append_only_reconciliation_is_accepted_but_its_cost_is_not_recycled():
    e = events(reconciled=True)
    rejected = rejected_client_ids(e)
    assert rejected == {CID}
    attempts, accepted = nba.records(e)
    assert len(attempts) == 1 and not accepted
    owner = shared.ownership({"nba": e, "nfl": []})
    assert len(owner["attempts"]) == 1
    assert owner["rejected_by_sport"]["nba"] == {CID}
    assert shared.room(owner, set(), 2.0, NOW)["shared_lifetime"]
    assert shared.room(owner, set(), 99.0, NOW)["shared_lifetime"] is False
    state = {
        "resting": [],
        "held": [],
        "settled": set(),
        "rejected_client_ids": rejected,
    }
    active, released = nba.reconcile_expired_unfilled(
        attempts, accepted, state, [], NOW
    )
    assert active == [] and released == 0


def test_rejection_marker_cannot_mask_accepted_or_unrelated_attempt():
    with pytest.raises(TradingError, match="Invalid"):
        rejected_client_ids(
            events(reconciled=True)
            + [{"event": "accepted", "client_order_id": CID, "order_id": "found"}]
        )
    with pytest.raises(TradingError, match="Invalid"):
        rejected_client_ids(events(reconciled=True) + events(reconciled=True)[-1:])


def test_reconciled_ticker_with_any_position_blocks_new_orders():
    owner = shared.ownership({"nba": events(reconciled=True), "nfl": []})
    with pytest.raises(TradingError, match="reconciled rejected"):
        shared.classify([], [{"market_ticker": TICKER, "position_fp": "-1"}], owner)


def test_manual_rejection_verification_rejects_any_exchange_evidence():
    raw = events()
    assert verify(raw, [], [], [], NOW) == CID
    with pytest.raises(TradingError, match="Matching exchange order"):
        verify(raw, [{"ticker": TICKER, "client_order_id": "other"}], [], [], NOW)
    with pytest.raises(TradingError, match="Possible exchange fill"):
        verify(raw, [], [{"ticker": TICKER}], [], NOW)
    with pytest.raises(TradingError, match="Possible open position"):
        verify(raw, [], [], [{"ticker": TICKER, "position_fp": "-1"}], NOW)


def test_rejected_submissions_do_not_use_nba_game_slots_but_remain_charged():
    """Two verified 404 rejects cannot consume both live-order slots."""
    row = SimpleNamespace(game_id="g", team="NY")
    prior = [
        {
            "event": "intent",
            "utc": NOW.isoformat(),
            "client_order_id": "reject-one",
            "ticker": "KXNBA-REJECT-A",
            "cost": 1.3,
            "game_id": "g",
            "team": "NY",
        },
        {
            "event": "intent",
            "utc": NOW.isoformat(),
            "client_order_id": "reject-two",
            "ticker": "KXNBA-REJECT-B",
            "cost": 1.35,
            "game_id": "g",
            "team": "NY",
        },
    ]
    rejected = {"reject-one", "reject-two"}
    assert not nba.room_for(prior, [], row, 0.8, NOW)
    assert nba.room_for(prior, [], row, 0.8, NOW, rejected=rejected)
    assert not nba.room_for(prior, [], row, 49.0, NOW, rejected=rejected)
    # An accepted trade remains subject to game/team exposure limits.
    assert nba.room_for(prior, [], row, 0.8, NOW, rejected={"reject-one"})
    with_one_large_acceptance = [prior[0], {**prior[1], "cost": 2.5}]
    assert not nba.room_for(
        with_one_large_acceptance, [], row, 0.8, NOW, rejected={"reject-one"}
    )
