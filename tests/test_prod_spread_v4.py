"""Fake-exchange integration tests: these tests never access Kalshi."""

import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from unittest.mock import Mock

import pytest

from kalshi.trading import TradingError
from live import prod_spread_v4 as worker
from live import spread_completion as p
from research.spread_forward_core import EvidenceError


def data(now):
    return {
        "market": {"ticker": "M", "event_ticker": "KXCS2GAME-E"},
        "series": "KXCS2GAME",
        "start": now + timedelta(hours=3),
        "expires": now + timedelta(hours=6),
        "exchange_index": 0,
        "fees": {"fee_type": "quadratic", "fee_multiplier": 1},
        "book": {"yes": [["0.40", "20"]], "no": [["0.50", "20"]]},
        "book_read": time.monotonic(),
    }


def fixture(monkeypatch, tmp_path, resting=False):
    now = datetime.now(UTC)
    journal = tmp_path / "journal.jsonl"
    journal.write_text("")
    intent = {
        "client_order_id": "entry",
        "ticker": "M",
        "event_ticker": "KXCS2GAME-E",
        "side": "yes",
        "count": "1",
        "price_cents": 41,
        "purpose": "entry",
        "utc": now.isoformat(),
        "expires_utc": (now + timedelta(seconds=90)).isoformat(),
        "strategy_version": p.VERSION,
    }
    orders = {"entry": intent} if resting else {}
    state = {
        "resting": [{"order_id": "entry", "ticker": "M", "remaining_count_fp": "1"}]
        if resting
        else [],
        "fills": [],
        "settlements": [],
    }
    monkeypatch.setattr(
        worker, "snapshot", lambda *a: ([], orders, state, {}, {}, False)
    )
    snapshot_data = data(now)
    plans = [
        p.Quote("M", "yes", 42, D(1), "entry"),
        p.Quote("M", "no", 51, D(1), "entry"),
    ]
    monkeypatch.setattr(
        worker, "decision", lambda *a: (plans, snapshot_data, "quoting_entry")
    )
    client = Mock()
    client._request.return_value = {
        "balance": 10000,
        "portfolio_value": 0,
        "exchange_balances": [{"exchange_index": 0, "balance": 10000}],
    }
    monkeypatch.setattr(worker.shard_funding, "shard_balance", lambda *_: D(100))
    client.place.return_value = {"order_id": "new"}
    client.cancel.return_value = {"reduced_by": "1"}
    return now, journal, client, plans, snapshot_data, state


def test_preview_has_no_order_or_journal_side_effects(monkeypatch, tmp_path):
    now, journal, client, _, _, _ = fixture(monkeypatch, tmp_path, resting=True)
    before = journal.read_bytes()
    report = worker.run_once(client, journal, now, [])
    assert report["cancel_count"] == 1 and report["submitted"] == 0
    assert journal.read_bytes() == before
    client.place.assert_not_called()
    client.cancel.assert_not_called()


@pytest.mark.parametrize("reduced", ["0", "0.25", "1", None])
def test_every_cancel_waits_for_fresh_account_before_replacing(
    monkeypatch, tmp_path, reduced
):
    now, journal, client, _, _, _ = fixture(monkeypatch, tmp_path, resting=True)
    client.cancel.return_value = {"reduced_by": reduced}
    report = worker.run_once(
        client, journal, now, [], live=True, authorize=lambda: None
    )
    assert report["decision"] == "canceled_waiting_for_fresh_account"
    assert client.cancel.call_count == 1
    client.place.assert_not_called()


def test_only_one_order_then_reread_even_for_initial_pair(monkeypatch, tmp_path):
    now, journal, client, _, _, _ = fixture(monkeypatch, tmp_path)
    report = worker.run_once(
        client, journal, now, [], live=True, authorize=lambda: None
    )
    assert report["submitted"] == 1 and client.place.call_count == 1
    events = worker.legacy.load_events(journal)
    assert [e["event"] for e in events] == ["intent", "accepted"]
    assert events[0]["strategy_version"] == p.VERSION
    assert events[0]["external_book"]
    assert client.place.call_args.args[0].post_only


def test_release_guard_is_mandatory(monkeypatch, tmp_path):
    now, journal, client, _, _, _ = fixture(monkeypatch, tmp_path)
    with pytest.raises(TradingError, match="release guard"):
        worker.run_once(client, journal, now, [], live=True)
    client.place.assert_not_called()


@pytest.mark.parametrize("stop", ["stale", "deadline", "kill", "start"])
def test_stale_or_stopped_order_never_gets_journaled(monkeypatch, tmp_path, stop):
    now, journal, client, plans, snap, _ = fixture(monkeypatch, tmp_path)
    deadline = time.monotonic() + 50
    if stop == "stale":
        snap["book_read"] -= 6
    elif stop == "deadline":
        deadline -= 60
    elif stop == "kill":
        (tmp_path / "V4_KILL").touch()
    else:
        snap["start"] = now - timedelta(seconds=1)
    worker.submit(client, journal, plans[0], snap, now, deadline, lambda: None)
    assert journal.read_text() == ""
    client.place.assert_not_called()


def test_ambiguous_post_is_not_retried_and_blocks_next_pass(monkeypatch, tmp_path):
    now, journal, client, plans, snap, _ = fixture(monkeypatch, tmp_path)
    client.place.side_effect = OSError("lost response")
    with pytest.raises(TradingError, match="outcome unknown"):
        worker.submit(
            client, journal, plans[0], snap, now, time.monotonic() + 30, lambda: None
        )
    assert client.place.call_count == 1
    events = worker.legacy.load_events(journal)
    assert [e["event"] for e in events] == ["intent", "unknown_outcome"]
    with pytest.raises(TradingError):
        worker.legacy.records(events)


def test_completion_runs_before_universe_scan(monkeypatch):
    now = datetime.now(UTC)
    snap = data(now)
    monkeypatch.setattr(worker, "market_data", lambda *a: snap)
    client = Mock()
    client._pages.side_effect = AssertionError("Inventory must not wait for discovery")
    lots = {
        "M": [
            {
                "side": "yes",
                "left": "0.37",
                "basis": D("0.41"),
                "at": now - timedelta(minutes=20),
            }
        ]
    }
    plans, _, _ = worker.decision(
        client,
        [],
        {},
        {"resting": [], "fills": []},
        {},
        lots,
        now,
        [],
        time.monotonic() + 30,
    )
    assert plans[0].side == "no" and plans[0].quantity == D("0.37")
    client._pages.assert_not_called()


def test_frozen_event_is_excluded_even_from_another_market(monkeypatch):
    now = datetime.now(UTC)
    snap = data(now)
    monkeypatch.setattr(worker, "market_data", lambda *a: snap)
    old = {
        "event_ticker": "KXCS2GAME-E",
        "strategy_version": "spread-maker-v3-24h-starts",
    }
    context = {"ownership": {"attempts": [], "tickers": {}}}
    state = {"resting": [{"ticker": "M"}], "fills": []}
    plans, _, _ = worker.decision(
        Mock(), [], {"old": old}, state, context, {}, now, [], time.monotonic() + 30
    )
    assert plans == []


def test_halt_cancellation_cannot_touch_other_versions(monkeypatch, tmp_path):
    client = Mock()
    client.orders.return_value = [
        {"order_id": "v4", "ticker": "M", "client_order_id": "smm-spread-v4-abc"},
        {"order_id": "v3", "ticker": "N", "client_order_id": "smm-spread-abc"},
        {"order_id": "nba", "ticker": "O", "client_order_id": "smm-abc"},
    ]
    client.cancel.return_value = {"reduced_by": "1"}
    worker.cancel_v4_on_halt(client, tmp_path / "journal.jsonl", datetime.now(UTC))
    client.cancel.assert_called_once_with("v4", ticker="M")


def test_unknown_fee_schedule_blocks_market_snapshot(monkeypatch):
    now = datetime.now(UTC)
    ticker = "KXCS2GAME-26OCT302000AB-A"
    market = {
        "ticker": ticker,
        "event_ticker": "KXCS2GAME-26OCT302000AB",
        "status": "active",
        "market_type": "binary",
        "notional_value_dollars": "1",
        "expected_expiration_time": (now + timedelta(hours=8)).isoformat(),
    }
    client = Mock()
    client._request.side_effect = [
        {"market": market},
        {"milestones": []},
        {"series": {"ticker": "KXCS2GAME", "fee_type": "flat", "fee_multiplier": 1}},
    ]
    with pytest.raises(EvidenceError, match="fee_schedule"):
        worker.market_data(client, ticker, [])


def test_gate_is_bound_to_code_and_expires(monkeypatch, tmp_path):
    now = datetime.now(UTC)
    gate = tmp_path / "gate.json"
    gate.write_text(
        json.dumps(
            {
                "version": p.VERSION,
                "source_sha256": "code",
                "approved_at": (now - timedelta(days=2)).isoformat(),
                "expires_at": (now - timedelta(days=1)).isoformat(),
            }
        )
    )
    monkeypatch.setattr(worker, "GATE", gate)
    monkeypatch.setattr(worker, "source_digest", lambda _: "code")
    monkeypatch.setattr(worker, "isolation_check", lambda: None)
    monkeypatch.setattr(worker.shared, "dual_mode", lambda _: True)
    client = Mock(dry_run=False, env="prod", can_sign=True)
    with pytest.raises(TradingError):
        worker.guard(
            client,
            {"ALLOW_PRODUCTION_TRADING": "YES", "SPREAD_V4_ARM": "YES"},
            tmp_path,
        )
