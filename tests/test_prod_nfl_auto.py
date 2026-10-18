from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from kalshi.trading import TradingError
from live import prod_nfl_auto as auto

NOW = datetime(2026, 10, 18, 15, 22, tzinfo=timezone.utc)
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
    assert cost <= 2.0
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
        for i in range(11)
    ]
    candidate = SimpleNamespace(game_id="fresh", team="fresh")
    assert not auto.room_for(attempts, [], candidate, 2.0, NOW)
    assert auto.reserve(2.0) == 2.2


def test_simultaneous_cap_and_game_cap():
    a = {"cost": 2.0, "game_id": "g1", "team": "PHI", "utc": NOW.isoformat()}
    b = {"cost": 2.0, "game_id": "g2", "team": "CAR", "utc": NOW.isoformat()}
    row = SimpleNamespace(game_id="g3", team="NYG")
    assert not auto.room_for([a, b], [a, b], row, 2.0, NOW)
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
