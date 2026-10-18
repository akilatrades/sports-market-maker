from datetime import datetime, timedelta, timezone
import pandas as pd
import pytest
from kalshi.trading import TradingError
from live.prod_nfl_pilot import (
    assert_live_safety,
    choose_market,
    execute_once,
    make_order,
    read_events,
)

NOW = datetime.now(timezone.utc)
ARMED = {
    "KALSHI_ENV": "prod",
    "TRADE_MODE": "live",
    "ALLOW_PRODUCTION_TRADING": "YES",
    "PROD_PILOT_ARM": "YES",
    "TRADE_MARKET": "nfl",
}


def frame(hours=1.0, bid=0.4, ask=0.5, p_book=0.3, injury=""):
    return pd.DataFrame(
        [
            {
                "ticker": "KXNFLRECYDS-26OCT18DALGB-PLAYER-40",
                "event_ticker": "KXNFLRECYDS-26OCT18DALGB",
                "player": "Player Test",
                "stat": "receiving_yards",
                "line": 39.5,
                "game_id": "26OCT18DALGB",
                "player_id": -1,
                "team": "DAL",
                "injury_status": injury,
                "yes_bid_dollars": bid,
                "yes_ask_dollars": ask,
                "p_model": 0.3,
                "p_book": p_book,
                "book_n": 2,
                "hours_to_tip": hours,
                "tip_utc": pd.Timestamp(NOW + timedelta(hours=hours)),
            }
        ]
    )


class FakeClient:
    can_sign = True
    env = "prod"
    dry_run = False

    def __init__(self, fail=False, existing=False):
        self.fail, self.existing, self.placed = fail, existing, []

    def orders(self, status="resting"):
        return [{"order_id": "unrelated"}] if self.existing else []

    def positions(self):
        return []

    def balance(self):
        return {"balance": 25.0}

    def place(self, order):
        self.placed.append(order)
        if self.fail:
            raise RuntimeError("timeout after submission")
        return {"order_id": "first", "fill_count": "0.00"}


def test_arm_guards():
    for field in (
        "KALSHI_ENV",
        "TRADE_MODE",
        "ALLOW_PRODUCTION_TRADING",
        "PROD_PILOT_ARM",
    ):
        state = dict(ARMED)
        state.pop(field)
        with pytest.raises(TradingError):
            assert_live_safety(state)
    with pytest.raises(TradingError):
        assert_live_safety({**ARMED, "DEMO_PILOT": "1"})


def test_late_window_and_book_veto():
    found = choose_market(frame(), NOW)
    assert found is not None and found.side == "no"
    assert abs(float(found.price) - 0.51) < 1e-6
    for kwargs in (
        {"hours": 3},
        {"hours": 0.25},
        {"injury": "OUT"},
        {"bid": 0, "ask": 0},
        {"p_book": 0.8},
    ):
        assert choose_market(frame(**kwargs), NOW) is None


def test_post_only_capped():
    order, cost = make_order(choose_market(frame(), NOW), NOW)
    assert order.post_only and order.side == "no" and cost <= 2.0
    assert order.body()["post_only"] is True


def test_dry_does_not_write(tmp_path):
    journal = tmp_path / "order.jsonl"
    client = FakeClient()
    assert not execute_once(
        live=False, env={}, client=client, frame=frame(), now=NOW, journal=journal
    )
    assert not journal.exists() and not client.placed


def test_one_attempt_only(tmp_path):
    journal = tmp_path / "order.jsonl"
    client = FakeClient()
    assert execute_once(
        live=True, env=ARMED, client=client, frame=frame(), now=NOW, journal=journal
    )
    assert [e["event"] for e in read_events(journal)] == ["intent", "accepted"]
    with pytest.raises(TradingError, match="Prior production attempt"):
        execute_once(
            live=True, env=ARMED, client=client, frame=frame(), now=NOW, journal=journal
        )
    assert len(client.placed) == 1


def test_timeout_cannot_retry(tmp_path):
    journal = tmp_path / "order.jsonl"
    client = FakeClient(fail=True)
    with pytest.raises(TradingError, match="uncertain"):
        execute_once(
            live=True, env=ARMED, client=client, frame=frame(), now=NOW, journal=journal
        )
    assert [e["event"] for e in read_events(journal)] == ["intent", "uncertain_result"]
    with pytest.raises(TradingError, match="Prior production attempt"):
        execute_once(
            live=True,
            env=ARMED,
            client=FakeClient(),
            frame=frame(),
            now=NOW,
            journal=journal,
        )


def test_existing_production_order_blocks(tmp_path):
    journal = tmp_path / "order.jsonl"
    with pytest.raises(TradingError, match="resting orders"):
        execute_once(
            live=True,
            env=ARMED,
            client=FakeClient(existing=True),
            frame=frame(),
            now=NOW,
            journal=journal,
        )
    assert not journal.exists()
