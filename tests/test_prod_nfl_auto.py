from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from kalshi.trading import TradingError
from live import prod_nfl_auto as auto

NOW = datetime.now(timezone.utc)
ARMED = {
    "KALSHI_ENV": "prod",
    "TRADE_MODE": "live",
    "PROD_AUTO_ARM": "YES",
    "ALLOW_PRODUCTION_TRADING": "YES",
}


def frame(ticker="KXNFLRECYDS-26OCT18CARPHI-PHIXPLAYER-30", injury=""):
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "event_ticker": "KXNFLRECYDS-26OCT18CARPHI",
                "player": "Player Test",
                "stat": "receiving_yards",
                "line": 29.5,
                "game_id": "26OCT18CARPHI",
                "player_id": -1,
                "team": "PHI",
                "injury_status": injury,
                "yes_bid_dollars": 0.40,
                "yes_ask_dollars": 0.50,
                "p_model": 0.35,
                "p_book": 0.40,
                "book_n": 2,
                "hours_to_tip": 1.0,
                "tip_utc": pd.Timestamp(NOW + timedelta(hours=1)),
            }
        ]
    )


class Client:
    env = "prod"
    dry_run = False
    can_sign = True

    def __init__(self):
        self.placed = []
        self.resting = []
        self.held = []
        self.settled = []
        self.broken = False
        self.cancelled = []

    def orders(self, status="resting"):
        return self.resting

    def positions(self):
        return self.held

    def settlements(self):
        return self.settled

    def fills(self, min_ts=None):
        return []

    def balance(self):
        return {"balance": 250.0}

    def place(self, order):
        self.placed.append(order)
        if self.broken:
            raise TimeoutError("Timeout may have placed order")
        reply = {"order_id": f"o{len(self.placed)}", "fill_count": "0.00"}
        self.resting.append({"ticker": order.ticker, "order_id": reply["order_id"]})
        return reply

    def queue_position(self, order_id):
        return 4.0

    def cancel(self, order_id, ticker=None):
        self.cancelled.append((order_id, ticker))
        self.resting = [o for o in self.resting if o["order_id"] != order_id]


@pytest.fixture
def quotes(monkeypatch):
    monkeypatch.setattr(
        auto,
        "fetch_market",
        lambda ticker: {
            "ticker": ticker,
            "status": "active",
            "yes_bid_dollars": "0.4000",
            "yes_ask_dollars": "0.5000",
        },
    )


def test_all_arm_flags_required():
    client = Client()
    for key in ARMED:
        settings = ARMED.copy()
        del settings[key]
        with pytest.raises(TradingError):
            auto.guard(settings, client)
    with pytest.raises(TradingError):
        auto.guard({**ARMED, "DEMO_PILOT": "1"}, client)


def test_order_has_strict_post_only_price_and_size(quotes):
    row = auto.select_candidates(frame(), [], {"active": []}, NOW)[0]
    order, cost = auto.order_from_row(row, NOW)
    assert cost <= auto.MAX_ORDER_COST
    assert order.post_only is True
    assert order.side == "no"
    assert order.count <= auto.MAX_CONTRACTS
    assert order.price_cents == 51
    assert order.body()["post_only"] is True
    auto.verify_quote(row)


def test_one_order_then_no_repeat(quotes, tmp_path):
    client = Client()
    journal = tmp_path / "ledger.jsonl"
    assert auto.pass_once(client, ARMED, frame(), NOW, journal)
    assert len(client.placed) == 1
    assert not auto.pass_once(client, ARMED, frame(), NOW, journal)
    assert len(client.placed) == 1
    attempts, accepted = auto.records(auto.load_journal(journal))
    assert len(attempts) == len(accepted) == 1


def test_unknown_timeout_halts_automation(quotes, tmp_path):
    client = Client()
    client.broken = True
    journal = tmp_path / "ledger.jsonl"
    with pytest.raises(TradingError, match="Ambiguous"):
        auto.pass_once(client, ARMED, frame(), NOW, journal)
    client.broken = False
    with pytest.raises(TradingError, match="Uncertain"):
        auto.pass_once(client, ARMED, frame(), NOW, journal)
    assert len(client.placed) == 1


def test_foreign_order_halts_before_new_trade(quotes, tmp_path):
    client = Client()
    client.resting = [{"ticker": "FOREIGN", "order_id": "other"}]
    with pytest.raises(TradingError, match="Foreign"):
        auto.pass_once(client, ARMED, frame(), NOW, tmp_path / "ledger.jsonl")
    assert not client.placed


def test_foreign_position_halts(quotes, tmp_path):
    client = Client()
    client.held = [{"market_ticker": "FOREIGN", "position": -1}]
    with pytest.raises(TradingError, match="Foreign"):
        auto.pass_once(client, ARMED, frame(), NOW, tmp_path / "ledger.jsonl")
    assert not client.placed


def test_budget_reserves_fees_and_never_renews():
    attempts = [
        {
            "cost": 2.0,
            "game_id": f"g{i}",
            "team": f"t{i}",
            "utc": (NOW - timedelta(days=i + 1)).isoformat(),
        }
        for i in range(23)
    ]
    candidate = SimpleNamespace(game_id="fresh", team="fresh")
    assert not auto.room_for(attempts, [], candidate, 2.0, NOW)
    assert auto.reserve(2.0) == 2.2


def test_simultaneous_cap_and_game_cap():
    a = {"cost": 2.0, "game_id": "g1", "team": "PHI", "utc": NOW.isoformat()}
    b = {"cost": 2.0, "game_id": "g2", "team": "CAR", "utc": NOW.isoformat()}
    row = SimpleNamespace(game_id="g3", team="NYG")
    assert auto.room_for([a, b], [a, b], row, 2.0, NOW)
    more = [
        {
            "cost": 2.0,
            "game_id": f"other{i}",
            "team": f"other{i}",
            "utc": NOW.isoformat(),
        }
        for i in range(5)
    ]
    assert not auto.room_for([a, b] + more, [a, b] + more, row, 2.0, NOW)
    row_same = SimpleNamespace(game_id="g1", team="PHI")
    assert not auto.room_for([a], [a], row_same, 2.0, NOW)


def test_unverified_player_cancels_existing_resting(quotes, tmp_path):
    client = Client()
    journal = tmp_path / "ledger.jsonl"
    assert auto.pass_once(client, ARMED, frame(), NOW, journal)
    assert not auto.pass_once(
        client,
        ARMED,
        frame(injury="UNVERIFIED"),
        NOW + timedelta(minutes=1),
        journal,
    )
    assert len(client.cancelled) == 1
    assert not client.resting


def test_dry_run_never_places_or_writes_journal(quotes, tmp_path):
    journal = tmp_path / "dry.jsonl"
    client = Client()
    assert not auto.pass_once(client, {}, frame(), NOW, journal, dry=True)
    assert not client.placed
    assert not journal.exists()


def test_stale_quote_does_not_place(monkeypatch, tmp_path):
    client = Client()
    monkeypatch.setattr(
        auto,
        "fetch_market",
        lambda ticker: {
            "status": "active",
            "yes_bid_dollars": ".20",
            "yes_ask_dollars": ".25",
        },
    )
    assert not auto.pass_once(
        client,
        ARMED,
        frame(),
        NOW,
        tmp_path / "ledger.jsonl",
    )
    assert not client.placed


def test_outlier_edge_is_not_automatically_traded():
    f = frame()
    f["p_book"] = 0.01
    assert auto.select_candidates(f, [], {"active": []}, NOW) == []


def test_emergency_stop_cancels_only_pilot_resting(quotes, tmp_path):
    client = Client()
    journal = tmp_path / "ledger.jsonl"
    assert auto.pass_once(client, ARMED, frame(), NOW, journal)
    client.resting.append({"ticker": "MANUAL", "order_id": "other"})
    assert auto.cancel_owned_on_kill(client, journal) == 1
    assert client.cancelled == [("o1", frame().iloc[0].ticker)]
    assert client.resting == [{"ticker": "MANUAL", "order_id": "other"}]


def test_unknown_submission_emergency_cancel_by_client_id(quotes, tmp_path):
    client = Client()
    client.broken = True
    journal = tmp_path / "ledger.jsonl"
    with pytest.raises(TradingError, match="Ambiguous"):
        auto.pass_once(client, ARMED, frame(), NOW, journal)
    intent = next(e for e in auto.load_journal(journal) if e["event"] == "intent")
    client.resting = [
        {
            "order_id": "unknown-but-accepted",
            "ticker": intent["ticker"],
            "client_order_id": intent["client_order_id"],
        }
    ]
    assert auto.cancel_owned_on_kill(client, journal) == 1
    assert not client.resting


def test_fill_and_settlement_are_recorded_once(tmp_path):
    journal = tmp_path / "ledger.jsonl"
    attempts = [{"ticker": "NFL-A"}]
    accepted = {"cid": {"order_id": "oid"}}
    fills = [
        {
            "order_id": "oid",
            "fill_id": "f1",
            "ticker": "NFL-A",
            "count_fp": "1.00",
            "no_price_dollars": ".5100",
            "fee_cost": "1",
        }
    ]
    settled = [
        {
            "market_ticker": "NFL-A",
            "settled_time": NOW.isoformat(),
            "revenue": 100,
            "no_total_cost": 51,
            "yes_total_cost": 0,
            "fee_cost": 1,
        }
    ]
    auto.record_execution(journal, [], attempts, accepted, fills, settled)
    events = auto.load_journal(journal)
    assert [e["event"] for e in events] == ["fill", "settlement"]
    auto.record_execution(journal, events, attempts, accepted, fills, settled)
    assert len(auto.load_journal(journal)) == 2
    assert events[1]["fee_cents"] == 1


def test_entries_12_minutes_before_kickoff_are_eligible(quotes):
    f = frame()
    f["hours_to_tip"] = 12 / 60
    f["tip_utc"] = pd.Timestamp(NOW + timedelta(minutes=12))
    rows = auto.select_candidates(f, [], {"active": []}, NOW)
    assert len(rows) == 1
    order, cost = auto.order_from_row(rows[0], NOW)
    assert order.post_only
    assert cost <= auto.MAX_ORDER_COST


def test_entries_9_minutes_before_kickoff_are_rejected(quotes):
    f = frame()
    f["hours_to_tip"] = 9 / 60
    f["tip_utc"] = pd.Timestamp(NOW + timedelta(minutes=9))
    assert auto.select_candidates(f, [], {"active": []}, NOW) == []
    candidate = auto.select_candidates(frame(), [], {"active": []}, NOW)[0]
    # Order guard operates independently of the candidate/window filter.
    row = candidate._replace(tip_utc=pd.Timestamp(NOW + timedelta(minutes=9)))
    with pytest.raises(TradingError, match="Too close"):
        auto.order_from_row(row, NOW)


def test_expired_unfilled_releases_active_only_after_ten_minutes():
    old = (NOW - timedelta(minutes=20)).isoformat()
    attempt = {
        "client_order_id": "cid",
        "ticker": "NFL-OLD",
        "tip_utc": old,
        "cost": 2.0,
        "game_id": "past",
        "team": "OLD",
        "utc": (NOW - timedelta(hours=1)).isoformat(),
    }
    accepted = {"cid": {"order_id": "oid"}}
    state = {"resting": [], "held": [], "settled": set()}
    active, freed = auto.reconcile_expired_unfilled([attempt], accepted, state, [], NOW)
    assert freed == 1 and active == []
    # The expired attempt still consumes cumulative and daily gross costs.
    row = SimpleNamespace(game_id="fresh", team="OTHER")
    assert auto.room_for([attempt], [], row, 2.0, NOW)
    assert auto.reserve(attempt["cost"]) == 2.2


def test_expired_with_fill_or_resting_or_position_never_releases():
    attempt = {
        "client_order_id": "cid",
        "ticker": "NFL-OLD",
        "tip_utc": (NOW - timedelta(minutes=20)).isoformat(),
    }
    accepted = {"cid": {"order_id": "oid"}}
    base = {"resting": [], "held": [], "settled": set()}
    for state, fills in [
        ({**base, "resting": [{"order_id": "oid"}]}, []),
        (base, [{"order_id": "oid", "ticker": "NFL-OLD"}]),
        ({**base, "held": ["NFL-OLD"]}, []),
    ]:
        active, freed = auto.reconcile_expired_unfilled(
            [attempt], accepted, state, fills, NOW
        )
        assert freed == 0 and active == [attempt]


def test_recent_expired_unfilled_still_reserved():
    attempt = {
        "client_order_id": "cid",
        "ticker": "NFL-OLD",
        "tip_utc": (NOW - timedelta(minutes=5)).isoformat(),
    }
    active, freed = auto.reconcile_expired_unfilled(
        [attempt],
        {"cid": {"order_id": "oid"}},
        {"resting": [], "held": [], "settled": set()},
        [],
        NOW,
    )
    assert freed == 0 and active == [attempt]


def test_expanded_authorized_budget():
    assert auto.MAX_ORDER_COST == 3.0
    assert auto.MAX_ACTIVE_COST == 15.0
    assert auto.MAX_DAILY_COST == 30.0
    assert auto.MAX_GROSS_COST == 50.0


def test_pre_submit_guard_checks_live_clock_not_scan_start():
    from datetime import timedelta

    scan_started = NOW - timedelta(minutes=6)
    kickoff = NOW + timedelta(minutes=9)
    assert auto.pre_submit_kickoff_ok(kickoff, scan_started)
    assert not auto.pre_submit_kickoff_ok(kickoff, NOW)
    assert not auto.pre_submit_kickoff_ok(NOW + timedelta(minutes=10, seconds=20), NOW)
    assert auto.pre_submit_kickoff_ok(NOW + timedelta(minutes=11), NOW)


def test_real_money_order_not_submitted_when_wall_clock_cutoff_failed(
    quotes, tmp_path, monkeypatch
):
    client = Client()
    journal = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(auto, "pre_submit_kickoff_ok", lambda tip, now: False)
    assert not auto.pass_once(client, ARMED, frame(), NOW, journal)
    assert client.placed == []
    assert not journal.exists()
