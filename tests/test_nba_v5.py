"""NBA v5: one contract, 0c edge floor, 5-95c, up to three orders per scan."""

import json
from datetime import timedelta

import pandas as pd
import pytest

from kalshi.trading import TradingError
from live import prod_nba_auto as nba
from tests.test_prod_nba_auto import ARMED, NOW, priced


@pytest.fixture(autouse=True)
def offline_shard(monkeypatch):
    monkeypatch.setattr(nba, "require_funded_shard", lambda *args: 3)


class Client:
    env, dry_run, can_sign = "prod", False, True

    def __init__(self, balance=100.0):
        self.posts = []
        self.cash = balance

    def orders(self, *args):
        return []

    def positions(self):
        return []

    def settlements(self):
        return []

    def fills(self, **kwargs):
        return []

    def balance(self):
        return {"balance": self.cash}

    def queue_position(self, oid):
        return 5.0

    def place(self, order):
        assert order.post_only and order.count == 1
        self.posts.append(order)
        return {"order_id": f"oid-{len(self.posts)}"}


def several(n):
    """n distinct markets for one player in one game, all passing every filter."""
    base = priced().iloc[0]
    rows = []
    for i in range(n):
        row = base.copy()
        row["ticker"] = f"KXNBAPTS-26OCT20LALGSW-LALSPLAYER-{30 + i}"
        rows.append(row)
    return pd.DataFrame(rows).reset_index(drop=True)


@pytest.fixture
def no_fees(monkeypatch):
    import kalshi.fees as fees

    monkeypatch.setattr(nba, "verify_quote", lambda *args: None)
    monkeypatch.setattr(
        fees,
        "live_maker_fee_bound",
        lambda *args: (0.0, {"fee_type": "quadratic", "fee_multiplier": 1}),
    )


def test_one_scan_places_at_most_three_orders(tmp_path, no_fees):
    client = Client()
    journal = tmp_path / "journal.jsonl"
    assert nba.pass_once(client, ARMED, several(5), NOW, journal)
    assert len(client.posts) == nba.MAX_NEW_ORDERS_PER_PASS == 3
    events = nba.load_journal(journal)
    intents = [e for e in events if e["event"] == "intent"]
    accepted = [e for e in events if e["event"] == "accepted"]
    assert len(intents) == len(accepted) == 3
    assert {e["strategy_version"] for e in intents} == {nba.STRATEGY_VERSION}
    assert all(e["count"] == 1 for e in intents)
    report = json.loads((tmp_path / "last_scan.json").read_text())
    assert report["decision"] == "accepted" and report["attempts"] == 3


def test_caps_are_rechecked_after_each_order_in_the_same_scan(
    tmp_path, no_fees, monkeypatch
):
    # Each 51c order reserves $0.561; a $1.20 game cap fits two, not three.
    monkeypatch.setattr(nba, "MAX_GAME_COST", 1.20)
    client = Client()
    journal = tmp_path / "journal.jsonl"
    assert nba.pass_once(client, ARMED, several(5), NOW, journal)
    assert len(client.posts) == 2
    report = json.loads((tmp_path / "last_scan.json").read_text())
    assert report["skipped"]["risk_nba_per_game_submissions"] == 3


def test_cash_is_rechecked_after_each_order_in_the_same_scan(tmp_path, no_fees):
    client = Client(balance=1.20)  # enough reserve for two orders
    journal = tmp_path / "journal.jsonl"
    assert nba.pass_once(client, ARMED, several(5), NOW, journal)
    assert len(client.posts) == 2


def test_charging_an_order_updates_the_account_wide_caps(monkeypatch):
    import live.shared_account_risk as shared
    from tests.test_shared_account_risk import both

    owner = shared.ownership(both())
    context = {"ownership": owner, "active_client_ids": set()}
    monkeypatch.setitem(shared.LIMITS, "active", 1.0)
    assert shared.fits(context, 0.5, NOW)
    intent = {
        "event": "intent",
        "client_order_id": "new-1",
        "ticker": "KXNBA-NEW-1",
        "cost": 0.5,
        "utc": NOW.isoformat(),
        "game_id": "g",
        "team": "LAL",
    }
    state = {"active": []}
    attempts, accepted = [], {}
    nba.charge_new_order(
        intent, {"order_id": "oid-new-1"}, attempts, accepted, state, context
    )
    assert attempts == [intent] and state["active"] == [intent]
    assert "new-1" in accepted and "new-1" in context["active_client_ids"]
    assert owner["tickers"]["KXNBA-NEW-1"] == "nba"
    # $0.55 already active plus another $0.55 would pass the $1.00 cap.
    assert not shared.fits(context, 0.5, NOW)


def test_v4_resting_orders_are_left_to_expire_not_halted():
    v4 = {
        "client_order_id": "cid-v4",
        "ticker": "KXNBA-V4",
        "strategy_version": "nba-no-v4-smaller-orders-edge3-baseline",
    }
    accepted = {"cid-v4": {"order_id": "oid-v4"}}
    resting = [{"order_id": "oid-v4", "ticker": "KXNBA-V4"}]
    assert nba.legacy_resting_count([v4], accepted, resting) == 1
    unknown = {**v4, "strategy_version": "nba-no-v9-unknown"}
    with pytest.raises(TradingError, match="Unknown NBA resting order version"):
        nba.legacy_resting_count([unknown], accepted, resting)


def test_new_price_band_is_5_to_95_cents():
    row = priced().iloc[0].copy()
    row["tip_utc"] = pd.Timestamp(NOW + timedelta(hours=4))
    for price in (0.05, 0.95):
        order, _ = nba.order_from_row(row, NOW, no_price=price)
        assert order.count == 1
    for price in (0.04, 0.96):
        with pytest.raises(TradingError, match="5c–95c"):
            nba.order_from_row(row, NOW, no_price=price)


@pytest.mark.parametrize(
    "p_book, expected",
    [(0.48, None), (0.49, None), (0.50, "current_net_edge_below_minimum")],
)
def test_resting_orders_are_kept_at_zero_edge_and_cancelled_below(p_book, expected):
    row = priced().iloc[0].copy()
    row["p_book"] = p_book  # NO bought at 51c: edge +1c, 0c, -1c
    intent = {
        "ticker": row.ticker,
        "price_cents": 51,
        "count": 1,
        "probability_source": "sportsbook",
    }
    market = {"status": "active", "yes_bid_dollars": 0.40, "yes_ask_dollars": 0.50}
    assert nba.resting_cancel_reason(row, intent, market, 0.0) == expected
