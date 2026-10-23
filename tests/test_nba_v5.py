"""NBA v5 rules, kept by v6 at three contracts an order: 0c edge floor, 5-95c,
up to three orders per scan. Caps below are sized from the bot's real order
size, so these tests hold at any MAX_CONTRACTS."""

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
        # Full size, or smaller when a cap leaves less room (never larger).
        assert order.post_only and 1 <= order.count <= nba.MAX_CONTRACTS
        self.posts.append(order)
        return {"order_id": f"oid-{len(self.posts)}"}


def two_orders():
    """Dollars that fit two of the test's full-size 51c orders and less than one
    more contract, so a third order cannot shrink to fit either."""
    full = nba.reserve(round(nba.MAX_CONTRACTS * 0.51, 2))
    return round(2 * full + 0.5 * nba.reserve(0.51), 2)


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
    assert all(e["count"] == nba.MAX_CONTRACTS for e in intents)
    report = json.loads((tmp_path / "last_scan.json").read_text())
    assert report["decision"] == "accepted" and report["attempts"] == 3


def test_caps_are_rechecked_after_each_order_in_the_same_scan(
    tmp_path, no_fees, monkeypatch
):
    # A game cap sized for two of these orders fits two, not three.
    monkeypatch.setattr(nba, "MAX_GAME_COST", two_orders())
    client = Client()
    journal = tmp_path / "journal.jsonl"
    assert nba.pass_once(client, ARMED, several(5), NOW, journal)
    assert len(client.posts) == 2
    report = json.loads((tmp_path / "last_scan.json").read_text())
    assert report["skipped"]["risk_nba_per_game_submissions"] == 3


def test_cash_is_rechecked_after_each_order_in_the_same_scan(tmp_path, no_fees):
    client = Client(balance=two_orders())  # enough reserve for two orders
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
        assert order.count == nba.MAX_CONTRACTS
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


# --- Transition, ambiguity and per-pass caps (from the independent review) ---


@pytest.fixture
def exchange_offline(monkeypatch, no_fees):
    monkeypatch.setattr(
        nba,
        "fetch_market",
        lambda t: {
            "status": "active",
            "yes_bid_dollars": 0.40,
            "yes_ask_dollars": 0.50,
        },
    )


def write_v4_order(journal, ticker="KXNBA-V4-OLD", count=2, cents=92):
    rows = [
        {
            "event": "intent",
            "utc": NOW.isoformat(),
            "client_order_id": "cid-v4",
            "ticker": ticker,
            "cost": round(count * cents / 100, 2),
            "count": count,
            "price_cents": cents,
            "game_id": "20261019",
            "team": "BOS",
            "tip_utc": NOW.isoformat(),
            "strategy_version": "nba-no-v4-smaller-orders-edge3-baseline",
            "probability_source": "sportsbook",
        },
        {"event": "accepted", "client_order_id": "cid-v4", "order_id": "oid-v4"},
    ]
    journal.write_text("".join(json.dumps(r) + "\n" for r in rows))


class Exchange(Client):
    def __init__(self, resting=(), positions=(), **kw):
        super().__init__(**kw)
        self._resting, self._positions, self.cancels = (
            list(resting),
            list(positions),
            [],
        )

    def orders(self, *args):
        return list(self._resting)

    def positions(self):
        return list(self._positions)

    def cancel(self, oid, ticker=None):
        self.cancels.append(oid)
        return {}


def test_resting_v4_order_is_left_alone_and_v5_waits(tmp_path, exchange_offline):
    journal = tmp_path / "journal.jsonl"
    write_v4_order(journal)
    client = Exchange(resting=[{"order_id": "oid-v4", "ticker": "KXNBA-V4-OLD"}])
    assert not nba.pass_once(client, ARMED, several(5), NOW, journal)
    assert client.posts == [] and client.cancels == []
    report = json.loads((tmp_path / "last_scan.json").read_text())
    assert report["decision"] == "waiting_for_prior_version_orders"


def test_filled_v4_position_does_not_block_v5(tmp_path, exchange_offline):
    journal = tmp_path / "journal.jsonl"
    write_v4_order(journal)
    client = Exchange(positions=[{"ticker": "KXNBA-V4-OLD", "position_fp": "-2"}])
    assert nba.pass_once(client, ARMED, several(5), NOW, journal)
    assert len(client.posts) == 3 and client.cancels == []


def test_ambiguous_second_order_halts_this_and_the_next_pass(tmp_path, no_fees):
    class Flaky(Client):
        def place(self, order):
            if self.posts:
                raise TimeoutError("socket")
            return super().place(order)

    journal = tmp_path / "journal.jsonl"
    with pytest.raises(TradingError, match="Ambiguous"):
        nba.pass_once(Flaky(), ARMED, several(5), NOW, journal)
    kinds = [e["event"] for e in nba.load_journal(journal) if e["event"] != "queue"]
    assert kinds == ["intent", "accepted", "intent", "unknown_outcome"]
    with pytest.raises(TradingError, match="Uncertain"):
        nba.pass_once(Client(), ARMED, several(5), NOW, journal)


@pytest.mark.parametrize(
    "name, value, reason",
    [
        ("MAX_TEAM_COST", "two orders", "risk_nba_per_team_submissions"),
        ("MAX_DAILY_COST", "two orders", "risk_nba_daily_submissions"),
        ("MAX_ACTIVE_COST", "two orders", "risk_nba_active_exposure"),
        ("MAX_GROSS_COST", "two orders", "risk_nba_lifetime_submissions"),
        ("MAX_GAME_ORDERS", 2, "risk_nba_game_order_count"),
    ],
)
def test_every_nba_cap_binds_within_one_pass(
    tmp_path, no_fees, monkeypatch, name, value, reason
):
    monkeypatch.setattr(nba, name, two_orders() if value == "two orders" else value)
    client = Client()
    assert nba.pass_once(client, ARMED, several(5), NOW, tmp_path / "journal.jsonl")
    assert len(client.posts) == 2
    report = json.loads((tmp_path / "last_scan.json").read_text())
    assert report["skipped"][reason] == 3


def test_account_wide_caps_bind_within_one_pass(tmp_path, no_fees, monkeypatch):
    import live.shared_account_risk as shared

    journal = tmp_path / "journal.jsonl"

    def fake_state_for(client, sport, now):
        owner = shared.ownership({"nfl": [], "nba": nba.load_journal(journal)})
        state = {
            "resting": [],
            "held": [],
            "settled": set(),
            "settlements": [],
            "active": [],
            "rejected_client_ids": set(),
        }
        context = {"ownership": owner, "active_client_ids": set()}
        return state, {**context, "account_pnl": {"loss_stop": False}}

    monkeypatch.setattr(shared, "dual_mode", lambda env: True)
    monkeypatch.setattr(shared, "state_for", fake_state_for)
    for key in ("active", "daily", "lifetime"):
        monkeypatch.setitem(shared.LIMITS, key, two_orders())
        journal.write_text("")
        client = Client()
        assert nba.pass_once(client, ARMED, several(5), NOW, journal)
        assert len(client.posts) == 2, key
        report = json.loads((tmp_path / "last_scan.json").read_text())
        assert report["skipped"]["risk_shared_account_cap"] == 3
        monkeypatch.setitem(shared.LIMITS, key, 10_000.0)


def test_unfunded_shard_after_an_order_still_reports_it_placed(
    tmp_path, no_fees, monkeypatch
):
    calls = []

    def shard(client, ticker, amount):
        calls.append(ticker)
        if len(calls) > 1:
            raise TradingError("SHARD_UNFUNDED_3: no")
        return 3

    monkeypatch.setattr(nba, "require_funded_shard", shard)
    client = Client()
    assert nba.pass_once(client, ARMED, several(5), NOW, tmp_path / "journal.jsonl")
    report = json.loads((tmp_path / "last_scan.json").read_text())
    assert len(client.posts) == 1
    assert report["placed"] is True and report["orders_placed_this_pass"] == 1


def test_entry_edge_floor_is_zero_after_the_estimated_fee(tmp_path, no_fees):
    # NO at 51c. The candidate stage subtracts an estimated maker fee (about
    # 0.44c here) even when the live fee is zero, so the effective floor is
    # just above zero: a book probability up to 0.4856 passes, 0.486 does not.
    for p_book, expected in ((0.48, 3), (0.4856, 3), (0.486, 0)):
        frame = several(3)
        frame["p_book"] = p_book
        client = Client()
        nba.pass_once(client, ARMED, frame, NOW, tmp_path / f"j{p_book}.jsonl")
        assert len(client.posts) == expected, p_book


# --- Keeping each pass inside the systemd timeout ---


def test_no_new_order_starts_after_the_time_budget(tmp_path, no_fees, monkeypatch):
    monkeypatch.setattr(nba, "elapsed_seconds", lambda: 151.0)
    client = Client()
    assert not nba.pass_once(client, ARMED, several(5), NOW, tmp_path / "j.jsonl")
    assert client.posts == []
    report = json.loads((tmp_path / "last_scan.json").read_text())
    assert report["skipped"]["pass_time_budget"] == 1


def test_time_budget_is_checked_again_just_before_each_order(
    tmp_path, no_fees, monkeypatch
):
    # Within budget at the top of the loop, over it by the check made just
    # before the journal intent: nothing is journaled or sent.
    clock = iter([10.0, 160.0] + [160.0] * 20)
    monkeypatch.setattr(nba, "elapsed_seconds", lambda: next(clock))
    client = Client()
    journal = tmp_path / "j.jsonl"
    assert not nba.pass_once(client, ARMED, several(5), NOW, journal)
    assert client.posts == []
    assert not journal.exists() or not [
        e for e in nba.load_journal(journal) if e["event"] == "intent"
    ]
    report = json.loads((tmp_path / "last_scan.json").read_text())
    assert report["skipped"]["pass_time_budget"] == 1


def test_queue_position_is_observed_at_most_every_ten_minutes():
    def observed(minutes_ago):
        utc = (NOW - timedelta(minutes=minutes_ago)).isoformat()
        return nba.last_queue_times([{"event": "queue", "order_id": "o1", "utc": utc}])

    assert nba.queue_observation_due({}, "o1", NOW)
    assert not nba.queue_observation_due(observed(3), "o1", NOW)
    assert nba.queue_observation_due(observed(11), "o1", NOW)
    assert nba.queue_observation_due(observed(3), "other", NOW)


def test_fee_metadata_is_fetched_once_per_series_and_event(monkeypatch):
    import kalshi.fees as fees

    calls = []

    def get_json(path, params, retries=1):
        calls.append(path)
        if path.startswith("/series/"):
            ticker = path.rsplit("/", 1)[1]
            return {
                "series": {
                    "ticker": ticker,
                    "fee_type": "quadratic",
                    "fee_multiplier": 1,
                }
            }
        ticker = path.rsplit("/", 1)[1]
        return {"event": {"event_ticker": ticker}}

    monkeypatch.setattr(fees, "get_json", get_json)
    cache = {}
    for line in (20, 25, 30):
        fees.live_maker_fee_bound(f"KXNBAPTS-26OCT21ATLORL-ORLX-{line}", 0.5, 1, cache)
    assert len(calls) == 2  # one series and one event request, then reused
    fees.live_maker_fee_bound("KXNBAPTS-26OCT21ATLORL-ORLX-35", 0.5, 1)
    assert len(calls) == 4  # without a cache, fetched fresh as before


def test_failed_fee_metadata_is_never_cached(monkeypatch):
    import kalshi.fees as fees

    responses = iter([None, {"event": {"event_ticker": "KXNBAPTS-26OCT21ATLORL"}}])
    monkeypatch.setattr(fees, "get_json", lambda *args, **kwargs: next(responses))
    cache = {}
    with pytest.raises(TradingError, match="fee_metadata_unavailable"):
        fees.live_maker_fee_bound("KXNBAPTS-26OCT21ATLORL-ORLX-20", 0.5, 1, cache)
    assert cache == {}


def v5_resting_journal(journal, ticker, queue_minutes_ago):
    rows = [
        {
            "event": "intent",
            "utc": (NOW - timedelta(hours=1)).isoformat(),
            "client_order_id": "cid-v5",
            "ticker": ticker,
            "cost": 0.51,
            "count": 1,
            "price_cents": 51,
            "game_id": "20261020",
            "team": "LAL",
            "tip_utc": (NOW + timedelta(hours=4)).isoformat(),
            "strategy_version": nba.STRATEGY_VERSION,
            "probability_source": "sportsbook",
        },
        {"event": "accepted", "client_order_id": "cid-v5", "order_id": "oid-v5"},
        {
            "event": "queue",
            "utc": (NOW - timedelta(minutes=queue_minutes_ago)).isoformat(),
            "order_id": "oid-v5",
            "ahead": 3,
            "issue": None,
        },
    ]
    journal.write_text("".join(json.dumps(r) + "\n" for r in rows))


@pytest.mark.parametrize("minutes_ago, resting_reads", [(3, 0), (11, 1)])
def test_scan_skips_recently_observed_resting_queue(
    tmp_path, exchange_offline, minutes_ago, resting_reads
):
    frame = several(5)
    ticker = str(frame.ticker.iloc[0])
    journal = tmp_path / "journal.jsonl"
    v5_resting_journal(journal, ticker, minutes_ago)

    class Counting(Exchange):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.queue_reads = []

        def queue_position(self, oid):
            self.queue_reads.append(str(oid))
            return 5.0

    client = Counting(resting=[{"order_id": "oid-v5", "ticker": ticker}])
    assert nba.pass_once(client, ARMED, frame, NOW, journal)
    assert client.cancels == [] and len(client.posts) == 3
    assert client.queue_reads.count("oid-v5") == resting_reads


def test_an_order_shrinks_to_the_room_a_cap_leaves(tmp_path, no_fees, monkeypatch):
    # Room for two full orders plus one contract: the third order goes out at
    # one contract, the fourth finds no room.
    full = nba.reserve(round(nba.MAX_CONTRACTS * 0.51, 2))
    monkeypatch.setattr(nba, "MAX_DAILY_COST", round(2 * full + nba.reserve(0.51), 2))
    monkeypatch.setattr(nba, "MAX_NEW_ORDERS_PER_PASS", 5)
    client = Client()
    assert nba.pass_once(client, ARMED, several(5), NOW, tmp_path / "journal.jsonl")
    assert [o.count for o in client.posts] == [nba.MAX_CONTRACTS] * 2 + [1]
