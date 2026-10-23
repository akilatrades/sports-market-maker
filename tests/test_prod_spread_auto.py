"""Offline tests for the spread maker (live/prod_spread_auto.py). No network."""

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kalshi.trading import TradingError
from live import prod_spread_auto as bot
from live import shared_account_risk as shared
from live import spread_policy as P

NOW = datetime(2026, 10, 22, 18, 0, tzinfo=UTC)
# Starts 18:00 New York time (22:00 UTC), four hours after NOW.
TICKER = "KXDOTA2GAME-26OCT221800AB-A"


# Tests that check the live limits themselves, rather than logic at a size.
REAL_LIMIT_TESTS = {
    "test_pilot_limits_are_the_owner_approved_ones",
    "test_v3_quotes_two_contracts_a_side_and_caps_net_at_two",
}


@pytest.fixture(autouse=True)
def logic_sized_at_five(request, monkeypatch):
    """Most tests exercise inventory, pairing and partial-fill logic with v2's
    5-contract orders; that logic does not depend on size. The live v3 values
    (2 and 2) are pinned in REAL_LIMIT_TESTS."""
    if request.node.originalname not in REAL_LIMIT_TESTS:
        monkeypatch.setattr(P, "CONTRACTS", 5)
        monkeypatch.setattr(P, "MAX_NET_PER_MARKET", 5)


def market(ticker=TICKER, bid=0.40, ask=0.52, hours=5.0, status="active"):
    return {
        "ticker": ticker,
        "event_ticker": ticker.rsplit("-", 1)[0],
        "status": status,
        "yes_bid_dollars": f"{bid:.2f}",
        "yes_ask_dollars": f"{ask:.2f}",
        "expected_expiration_time": (NOW + timedelta(hours=hours)).isoformat(),
    }


# ----------------------------------------------------------- pure parts


def test_quote_prices_one_cent_inside_wide_spreads_only():
    # YES bid 41c and NO bid 49c (the same as a YES offer at 51c).
    assert bot.quote_prices(40, 52) == (41, 49)
    assert bot.quote_prices(40, 48) == (41, 53)  # exactly 8c is enough
    assert bot.quote_prices(40, 47) is None  # 7c spread
    assert bot.quote_prices(0, 10) is None  # no YES bid: one-sided book
    assert bot.quote_prices(90, 100) is None  # no YES offer: one-sided book
    assert bot.quote_prices(52, 40) is None  # crossed book
    assert bot.quote_prices(None, 50) is None
    assert bot.quote_prices(1, 30) == (2, 71)  # extremes stay inside 2-98c
    assert bot.quote_prices(90, 99) == (91, 2)


def test_eligible_markets_filters_window_series_and_other_bots():
    rows = bot.eligible_markets(
        [
            market(),
            market("KXDOTA2GAME-26OCT221800XY-B", hours=3.0),
            market("KXDOTA2GAME-26OCT221800XY-C", hours=P.WINDOW_HOURS[1] + 1),
            market("KXDOTA2GAME-26OCT221800XY-D", ask=0.45),
            market("KXDOTA2GAME-26OCT221800XY-E", status="closed"),
            market("KXDOTA2GAME-26OCT221800XY-F"),
            market("KXNBAPTS-26OCT22AB-P10"),
        ],
        "KXDOTA2GAME",
        NOW,
        other_tickers={"KXDOTA2GAME-26OCT221800XY-F"},
    )
    assert [r["ticker"] for r in rows] == [TICKER]
    assert rows[0]["yes_price"] == 41 and rows[0]["no_price"] == 49
    assert bot.eligible_markets([market()], "KXCPIYOY", NOW) == []  # maker fee


def test_contracts_through_follows_the_backtest_fill_rule():
    t0, t1 = NOW, NOW + timedelta(hours=1)
    at = (NOW + timedelta(minutes=10)).isoformat()
    trades = [
        {"created_time": at, "yes_price": 0.40, "count": 3, "taker_outcome_side": "no"},
        {"created_time": at, "yes_price": 0.41, "count": 2, "taker_outcome_side": "no"},
        {"created_time": at, "yes_price": 0.42, "count": 7, "taker_outcome_side": "no"},
        {
            "created_time": at,
            "yes_price": 0.52,
            "count": 4,
            "taker_outcome_side": "yes",
        },
        {
            "created_time": at,
            "yes_price": 0.51,
            "count": 1,
            "taker_outcome_side": "yes",
        },
        {
            "created_time": at,
            "yes_price": 0.50,
            "count": 9,
            "taker_outcome_side": "yes",
        },
        {
            "created_time": at,
            "yes_price": 0.30,
            "count": 50,
            "taker_outcome_side": "no",
            "is_block_trade": True,
        },
        {
            "created_time": (t1 + timedelta(minutes=1)).isoformat(),
            "yes_price": 0.30,
            "count": 50,
            "taker_outcome_side": "no",
        },
    ]
    assert bot.contracts_through(trades, "yes", 41, t0, t1) == 5
    assert bot.contracts_through(trades, "no", 49, t0, t1) == 5


def test_shadow_posts_hourly_scores_and_settles():
    rows = bot.eligible_markets([market()], "KXDOTA2GAME", NOW)
    first = bot.shadow_post([], rows, NOW)
    assert {(e["side"], e["price_cents"]) for e in first} == {("yes", 41), ("no", 49)}
    assert bot.shadow_post(first, rows, NOW + timedelta(minutes=30)) == []
    assert len(bot.shadow_post(first, rows, NOW + timedelta(minutes=61))) == 2
    at = (NOW + timedelta(minutes=5)).isoformat()

    def trades(ticker, start, end):
        return [
            {
                "created_time": at,
                "yes_price": 0.40,
                "count": 2,
                "taker_outcome_side": "no",
            }
        ]

    assert bot.shadow_score(first, NOW + timedelta(minutes=30), trades) == []
    fills = bot.shadow_score(first, NOW + timedelta(minutes=61), trades)
    assert sorted(f["through"] for f in fills) == [0.0, 2.0]
    results = bot.shadow_settle(first + fills, lambda t: {"result": "yes"})
    assert results == [{"event": "shadow_result", "ticker": TICKER, "result": "yes"}]
    summary = bot.shadow_summary(first + fills + results)
    assert summary["filled"] == 1 and summary["cents_per_contract"] == pytest.approx(59)


def test_inventory_cap_and_held_cost():
    rows = bot.eligible_markets([market()], "KXDOTA2GAME", NOW)
    yes, no = (TICKER, "yes"), (TICKER, "no")
    assert bot.desired_quotes(rows, {}) == {yes: (41, 5), no: (49, 5)}
    # Holding 2 YES: a YES order may add only 3 more; NO may buy all 5.
    assert bot.desired_quotes(rows, {TICKER: 2.0}) == {yes: (41, 3), no: (49, 5)}
    assert bot.desired_quotes(rows, {TICKER: 5.0}) == {no: (49, 5)}
    assert bot.desired_quotes(rows, {TICKER: -4.0}) == {yes: (41, 5), no: (49, 1)}
    lots = {TICKER: [("yes", 0.41, 1.0)]}
    assert bot.held_cost({TICKER: 1.0}, lots) == pytest.approx(0.41)
    # Exchange and ledger disagree (a fill not listed yet): $1 a contract.
    assert bot.held_cost({TICKER: -1.0}, lots) == pytest.approx(1.0)
    assert bot.held_cost({"KXOTHER": -2.0}, lots) == pytest.approx(2.0)


# ------------------------------------------------------------- live pass


class FakeExchange:
    env, dry_run, can_sign = "prod", False, True

    def __init__(self):
        self.resting, self.positions_, self.fills_, self.settlements_ = [], [], [], []
        self.placed, self.canceled, self.fail_place, self.fail_cancel = (
            [],
            [],
            None,
            None,
        )
        self.n = 0
        self.history = {"executed": [], "canceled": []}  # orders off the book

    def orders(self, status="resting", ticker=None):
        rows = self.resting if status == "resting" else self.history[status]
        return [o for o in rows if ticker is None or o["ticker"] == ticker]

    def positions(self):
        return self.positions_

    def fills(self, min_ts=None):
        return self.fills_

    def settlements(self):
        return self.settlements_

    def place(self, order):
        if self.fail_place:
            raise self.fail_place
        self.n += 1
        oid = f"oid-{self.n}"
        self.placed.append(order)
        self.resting.append(
            {
                "order_id": oid,
                "ticker": order.ticker,
                "client_order_id": order.client_order_id,
                "side": order.side,
                "price_cents": order.price_cents,
                "remaining_count_fp": f"{order.count:.2f}",
            }
        )
        return {"order_id": oid}

    def cancel(self, order_id, ticker=None):
        if self.fail_cancel:
            error, self.fail_cancel = self.fail_cancel, None
            self.resting = [o for o in self.resting if o["order_id"] != order_id]
            raise error
        self.canceled.append(order_id)
        gone = [o for o in self.resting if o["order_id"] == order_id]
        self.history["canceled"] += gone
        self.resting = [o for o in self.resting if o["order_id"] != order_id]
        # Kalshi V2 answers with the contracts it cancelled (fixed-point).
        left = sum(float(o.get("remaining_count_fp", 0)) for o in gone)
        return {"order_id": order_id, "reduced_by": f"{left:.2f}"}


ENV = {
    "KALSHI_ENV": "prod",
    "ALLOW_PRODUCTION_TRADING": "YES",
    "SPREAD_AUTO_ARM": "YES",
    "SMM_DUAL_MARKET": "YES",
}


@pytest.fixture
def world(monkeypatch, tmp_path):
    for name in ("nfl", "nba", "spread"):
        folder = tmp_path / f"prod-{name}-auto"
        folder.mkdir()
        (folder / "journal.jsonl").write_text("")
    marker = tmp_path / "spread.enabled"
    marker.write_text("")
    # Each live run is a fresh process; its deadlines count from import. In a
    # long test session that clock would already be minutes old.
    monkeypatch.setattr(bot, "PROCESS_START", time.monotonic())
    monkeypatch.setattr(shared, "ROOT", tmp_path)
    monkeypatch.setattr(shared, "dual_mode", lambda env: True)
    monkeypatch.setattr(P, "ARM_MARKER", marker)
    monkeypatch.setattr(P, "SERIES", ("KXDOTA2GAME",))
    quotes = {TICKER: market()}  # other traders' best bid and offer
    exchange = FakeExchange()

    def book(ticker):
        """Order book as the public sees it: other traders plus our quotes."""
        m = quotes[ticker]
        yes = [[m["yes_bid_dollars"], "5.00"]]
        no = [[f"{1 - float(m['yes_ask_dollars']):.2f}", "5.00"]]
        for o in exchange.resting:
            if o["ticker"] == ticker and o.get("side"):
                left = o.get("remaining_count_fp", "1.00")
                level = [f"{o['price_cents'] / 100:.2f}", left]
                (yes if o["side"] == "yes" else no).append(level)
        return {"yes_dollars": sorted(yes), "no_dollars": sorted(no)}

    def listed(ticker):
        """The market listing's best bid and offer, our quotes included."""
        b = book(ticker)
        bid = max(float(p) for p, _ in b["yes_dollars"])
        ask = 1 - max(float(p) for p, _ in b["no_dollars"])
        return {
            **quotes[ticker],
            "yes_bid_dollars": f"{bid:.2f}",
            "yes_ask_dollars": f"{ask:.2f}",
        }

    public = {
        "fetch_markets": lambda series, status="open": [listed(t) for t in quotes],
        "fetch_market": lambda ticker: listed(ticker) if ticker in quotes else None,
        "fetch_orderbook": book,
        "fetch_trades": lambda ticker, a, b: [],
        "fetch_milestones": lambda event: {"milestones": []},
    }
    return {
        "dir": tmp_path / "prod-spread-auto",
        "quotes": quotes,
        "public": public,
        "exchange": exchange,
        "marker": marker,
    }


def run(world, now=NOW):
    return bot.pass_live(
        world["exchange"],
        ENV,
        now,
        world["dir"],
        world["public"],
        require_shard=lambda client, ticker, cost: 1,
    )


def journal(world):
    return bot.load_events(world["dir"] / "journal.jsonl")


def test_places_both_quotes_and_every_bot_still_owns_the_account(world):
    report, markets = run(world)
    ex = world["exchange"]
    assert report["accepted"] == 2 and len(markets) == 1
    assert {(o.side, o.price_cents, o.count, o.post_only) for o in ex.placed} == {
        ("yes", 41, 5, True),
        ("no", 49, 5, True),
    }
    assert all(
        o.expiration_ts <= (NOW + timedelta(minutes=66)).timestamp() for o in ex.placed
    )
    intents, accepted, refused = bot.records(journal(world))
    assert len(intents) == 2 and len(accepted) == 2 and not refused
    # The NBA bot reading the same account recognises the spread orders.
    state, _ = shared.state_for(ex, "nba", NOW)
    assert state["resting"] == []


def test_unchanged_book_keeps_quotes_and_moved_book_requotes(world):
    run(world)
    ex = world["exchange"]
    report, _ = run(world, NOW + timedelta(minutes=10))
    assert report["placed"] == 0 and report["resting_kept"] == 2 and not ex.canceled
    world["quotes"][TICKER] = market(bid=0.42, ask=0.52)
    report, _ = run(world, NOW + timedelta(minutes=20))
    assert len(ex.canceled) == 1  # only the YES quote moved
    assert {(o.side, o.price_cents) for o in ex.placed[-1:]} == {("yes", 43)}


def test_old_quotes_are_replaced_before_they_expire(world):
    world["quotes"][TICKER] = market(hours=6.5)
    run(world)
    report, _ = run(world, NOW + timedelta(minutes=P.ORDER_LIFETIME_MINUTES - 4))
    assert report["canceled"] == 2 and report["accepted"] == 2


def test_quotes_are_pulled_when_the_market_leaves_the_window(world):
    run(world)  # 5 hours before expiration
    report, markets = run(world, NOW + timedelta(minutes=61))  # under 4 hours
    assert markets == [] and report["canceled"] == 2 and report["placed"] == 0
    assert world["exchange"].resting == []


def test_held_side_is_not_quoted_again(world):
    run(world)
    fill_placed(world, 0, 5)  # all 5 YES fill: the market is at the cap
    report, _ = run(world, NOW + timedelta(minutes=10))
    assert report["placed"] == 0  # NO quote kept, YES not re-posted
    assert report["resting_kept"] == 1


def test_active_cap_blocks_new_quotes(world, monkeypatch):
    monkeypatch.setattr(P, "MAX_ACTIVE_COST", 2.10)  # YES 5 x 41c fits, NO does not
    report, _ = run(world)
    assert report["accepted"] == 1 and report["skip_active_cap"] == 1


def test_the_bot_never_prices_off_its_own_quotes(world):
    # Exactly 8c wide: once our quotes rest, the listing shows a 6c spread
    # with our own YES bid on top. The bot must see through that and keep
    # both quotes, not chase itself or pull them.
    world["quotes"][TICKER] = market(bid=0.40, ask=0.48)
    run(world)
    ex = world["exchange"]
    assert {(o.side, o.price_cents) for o in ex.placed} == {("yes", 41), ("no", 53)}
    listed = world["public"]["fetch_market"](TICKER)
    assert (listed["yes_bid_dollars"], listed["yes_ask_dollars"]) == ("0.41", "0.47")
    for minutes in (10, 20, 30):
        report, markets = run(world, NOW + timedelta(minutes=minutes))
        assert report["resting_kept"] == 2 and report["placed"] == 0
    assert not ex.canceled and markets[0]["spread"] == 8


def test_quote_that_moved_since_the_scan_is_skipped(world):
    calls = {"n": 0}
    original = world["public"]["fetch_orderbook"]

    def moving(ticker):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"yes_dollars": [["0.43", "5.00"]], "no_dollars": [["0.48", "5.00"]]}
        return original(ticker)

    world["public"]["fetch_orderbook"] = moving
    report, _ = run(world)
    assert report["skip_quote_moved"] == 1 and report["accepted"] == 1


def test_unreadable_book_holds_our_quotes(world):
    run(world)
    ex = world["exchange"]

    def broken(ticker):
        raise OSError("timed out")

    world["public"]["fetch_orderbook"] = broken
    report, markets = run(world, NOW + timedelta(minutes=10))
    # One failed read: keep the quotes (they expire on the exchange) and add
    # nothing in that market, instead of cancelling and re-posting.
    assert markets == [] and report["held_book_unreadable"] == 2
    assert "canceled" not in report and report["placed"] == 0 and len(ex.resting) == 2


def test_daily_submission_cap(world, monkeypatch):
    monkeypatch.setattr(P, "MAX_SUBMISSIONS_PER_DAY", 1)
    report, _ = run(world)
    assert report["accepted"] == 1 and report["skip_daily_cap"] == 1
    report, _ = run(world, NOW + timedelta(minutes=10))
    assert report["placed"] == 0 and report["skip_daily_cap"] == 1


def test_post_only_refusal_is_recorded_after_a_signed_check(world):
    ex = world["exchange"]
    ex.fail_place = TradingError(
        "POST /portfolio/events/orders -> HTTP 400: post only cross"
    )
    report, _ = run(world)
    assert report["rejected"] == 2
    intents, accepted, refused = bot.records(journal(world))
    assert len(refused) == 2 and not accepted
    shared.ownership(
        {"nfl": [], "nba": [], "spread": journal(world)}
    )  # every bot can still trade


def test_ambiguous_submission_halts_and_stays_halted(world):
    world["exchange"].fail_place = TimeoutError("read timed out")
    with pytest.raises(TradingError, match="Ambiguous spread submission"):
        run(world)
    with pytest.raises(TradingError, match="Ambiguous"):
        run(world, NOW + timedelta(minutes=10))
    with pytest.raises(TradingError, match="Ambiguous"):
        shared.state_for(world["exchange"], "nba", NOW)


def test_missing_order_id_halts(world):
    world["exchange"].place = lambda order: {}
    with pytest.raises(TradingError, match="Ambiguous spread submission"):
        run(world)
    with pytest.raises(TradingError, match="Ambiguous"):
        run(world, NOW + timedelta(minutes=10))


def test_crash_between_intent_and_reply_halts(world):
    run(world)
    path = world["dir"] / "journal.jsonl"
    events = journal(world)
    path.write_text(
        "".join(
            json.dumps(e) + "\n"
            for e in events
            if not (e["event"] == "accepted" and e["order_id"] == "oid-2")
        )
    )
    with pytest.raises(TradingError, match="Unreconciled"):
        run(world, NOW + timedelta(minutes=10))
    path.write_text(path.read_text() + '{"event": "intent"')  # torn write
    with pytest.raises(TradingError, match="Incomplete"):
        run(world, NOW + timedelta(minutes=10))


def test_cancel_refused_while_still_resting_halts(world):
    run(world)
    ex = world["exchange"]
    world["quotes"][TICKER] = market(bid=0.44, ask=0.52)

    def refuse(order_id, ticker=None):
        raise TradingError("DELETE /portfolio/events/orders/x -> HTTP 409: busy")

    ex.cancel = refuse
    with pytest.raises(TradingError, match="Cannot confirm spread cancellation"):
        run(world, NOW + timedelta(minutes=10))


def test_cancel_of_an_order_that_just_filled_is_not_a_halt(world):
    run(world)
    ex = world["exchange"]
    world["quotes"][TICKER] = market(bid=0.44, ask=0.52)
    ex.fail_cancel = TradingError(
        "DELETE /portfolio/events/orders/oid-1 -> HTTP 404: not found"
    )
    placed = len(ex.placed)
    report, _ = run(world, NOW + timedelta(minutes=10))
    assert any(e.get("event") == "cancel_moot" for e in journal(world))
    # It probably filled after the account read: no replacement YES in that
    # market until the next pass sees the new position (inventory cap).
    assert len(ex.placed) == placed and report["skip_just_filled"] == 1


def test_cancel_that_removes_nothing_is_moot(world):
    run(world)
    ex = world["exchange"]
    world["quotes"][TICKER] = market(bid=0.44, ask=0.52)
    original = ex.cancel

    def nothing_left(order_id, ticker=None):
        original(order_id, ticker)
        return {"reduced_by": "0.00"}

    ex.cancel = nothing_left
    report, _ = run(world, NOW + timedelta(minutes=10))
    assert report["skip_just_filled"] == 1 and report["placed"] == 0


def fill_of(order, minutes, fid=None, count=None):
    """An exchange fill of one of our placed orders, as Kalshi lists it."""
    yes = order.price_cents if order.side == "yes" else 100 - order.price_cents
    return {
        "fill_id": fid or f"fill-{order.client_order_id}",
        "order_id": None,  # set by the caller from the fake exchange
        "ticker": order.ticker,
        "created_time": (NOW + timedelta(minutes=minutes)).isoformat(),
        "count_fp": f"{count or order.count:.2f}",
        "yes_price_dollars": f"{yes / 100:.4f}",
        "no_price_dollars": f"{(100 - yes) / 100:.4f}",
        "outcome_side": order.side,
        "book_side": "bid" if order.side == "yes" else "ask",
        "fee_cost": "0.00",
    }


def fill_placed(world, index, minutes, count=None):
    """Fill the index-th order we placed (all of it unless ``count``); it
    leaves the book once nothing remains, and the position nets."""
    ex = world["exchange"]
    order = ex.placed[index]
    oid = f"oid-{index + 1}"
    n = count or order.count
    for o in ex.resting:
        if o["order_id"] == oid:
            o["remaining_count_fp"] = f"{float(o['remaining_count_fp']) - n:.2f}"
    ex.resting = [
        o
        for o in ex.resting
        if o["order_id"] != oid or float(o["remaining_count_fp"]) > 0
    ]
    fid = f"fill-{order.client_order_id}-{len(ex.fills_)}"
    ex.fills_.append({**fill_of(order, minutes, fid, n), "order_id": oid})
    net = {p["market_ticker"]: float(p["position_fp"]) for p in ex.positions_}
    net[order.ticker] = net.get(order.ticker, 0.0) + (n if order.side == "yes" else -n)
    ex.positions_ = [
        {"market_ticker": t, "position_fp": f"{q:.2f}"} for t, q in net.items() if q
    ]
    return order


def test_own_loss_stop_cancels_everything(world, monkeypatch):
    monkeypatch.setattr(P, "DAILY_LOSS_STOP", 2.00)
    run(world)
    ex = world["exchange"]
    fill_placed(world, 0, 5)  # the 5 YES at 41c fill
    ex.positions_ = []  # and the market settles NO: 5 x -41c
    ex.settlements_ = [
        {
            "market_ticker": TICKER,
            "settled_time": (NOW + timedelta(minutes=8)).isoformat(),
            "market_result": "no",
            "revenue_dollars": "0.00",
            "yes_total_cost_dollars": "2.05",
            "no_total_cost_dollars": "0.00",
            "fee_cost": "0.00",
        }
    ]
    report, markets = run(world, NOW + timedelta(minutes=10))
    assert report["decision"] == "spread_loss_stop" and markets is None
    assert report["daily"] == pytest.approx(-2.05)
    assert ex.resting == [] and len(ex.canceled) == 1  # the NO quote


def test_a_losing_pair_counts_at_once_without_any_settlement(world, monkeypatch):
    # The reviewer's case: YES fills at 41c, the market falls, our NO quote
    # is repriced to 74c and fills. Kalshi nets the pair to zero: no
    # settlement record will ever show the 15c loss, but the stop must.
    monkeypatch.setattr(P, "DAILY_LOSS_STOP", 0.70)
    run(world)
    ex = world["exchange"]
    fill_placed(world, 0, 5)
    world["quotes"][TICKER] = market(bid=0.15, ask=0.27)  # NO bid now 74c
    run(world, NOW + timedelta(minutes=10))
    no_74 = len(ex.placed) - 1
    assert (ex.placed[no_74].side, ex.placed[no_74].price_cents) == ("no", 74)
    fill_placed(world, no_74, 12)  # nets to zero: 5 x (1 - 41c - 74c)
    assert ex.positions_ == []
    report, markets = run(world, NOW + timedelta(minutes=20))
    assert report["decision"] == "spread_loss_stop" and report[
        "daily"
    ] == pytest.approx(-0.75)
    assert ex.resting == []


def test_account_loss_stop_from_another_bot_pulls_spread_quotes(world):
    run(world)
    nba = world["dir"].parent / "prod-nba-auto" / "journal.jsonl"
    lost = "KXNBAPTS-26OCT22AB-P25"
    events = [
        {
            "event": "intent",
            "client_order_id": "n1",
            "ticker": lost,
            "utc": NOW.isoformat(),
            "cost": 0.8,
            "count": 1,
            "side": "no",
            "tip_utc": NOW.isoformat(),
        },
        {"event": "accepted", "client_order_id": "n1", "order_id": "nba-1"},
    ]
    nba.write_text("".join(json.dumps(e) + "\n" for e in events))
    ex = world["exchange"]
    ex.settlements_ = [
        {
            "market_ticker": lost,
            "settled_time": NOW.isoformat(),
            "revenue_dollars": "0.00",
            "yes_total_cost_dollars": "0.00",
            "no_total_cost_dollars": "25.00",
            "fee_cost": "0.00",
        }
    ]
    ex.fills_ = [{"ticker": lost, "order_id": "nba-1"}]
    report, markets = run(world, NOW + timedelta(minutes=10))
    assert report["decision"] == "account_loss_stop" and markets is None
    assert ex.resting == []


def test_kill_cancels_only_this_bots_orders(world):
    run(world)
    ex = world["exchange"]
    ex.resting.append({"order_id": "manual-1", "ticker": "KXOTHER-1"})
    assert bot.cancel_owned_on_kill(ex, world["dir"] / "journal.jsonl") == 2
    assert ex.resting == [{"order_id": "manual-1", "ticker": "KXOTHER-1"}]


def test_shadow_ledger_end_to_end(world, tmp_path):
    folder = tmp_path / "shadow-only"
    folder.mkdir()
    at = (NOW + timedelta(minutes=30)).isoformat()
    world["public"]["fetch_trades"] = lambda ticker, a, b: [
        {"created_time": at, "yes_price": 0.41, "count": 3, "taker_outcome_side": "no"}
    ]
    reads = []
    world["public"]["fetch_market"] = lambda ticker: reads.append(ticker) or {
        "result": "no"
    }
    first = bot.run_shadow(folder, NOW, world["public"])
    assert first == {"quotes": 2, "scored": 0}
    later = bot.run_shadow(folder, NOW + timedelta(minutes=61), world["public"])
    # Scored, but the result is read only once the market's expected
    # expiration (NOW + 5 h) has passed.
    assert later["filled"] == 1 and later["settled_fills"] == 0 and reads == []
    later = bot.run_shadow(folder, NOW + timedelta(hours=5, minutes=1), world["public"])
    assert later["filled"] == 1 and later["settled_fills"] == 1 and reads == [TICKER]
    assert later["cents_per_contract"] == pytest.approx(-41)
    assert world["exchange"].placed == []  # shadow never touches the exchange


def test_unarmed_or_unmarked_bot_never_trades(world):
    for env in (
        {**ENV, "SPREAD_AUTO_ARM": "NO"},
        {**ENV, "ALLOW_PRODUCTION_TRADING": ""},
    ):
        with pytest.raises(TradingError, match="Unarmed"):
            bot.pass_live(world["exchange"], env, NOW, world["dir"], world["public"])
    world["marker"].unlink()
    with pytest.raises(TradingError, match="Owner has not enabled"):
        run(world)
    assert world["exchange"].placed == []


def test_other_bots_markets_are_never_quoted(world):
    nba = world["dir"].parent / "prod-nba-auto" / "journal.jsonl"
    intent = {
        "event": "intent",
        "client_order_id": "n1",
        "ticker": TICKER,
        "utc": NOW.isoformat(),
        "cost": 0.5,
        "count": 1,
        "side": "no",
        "tip_utc": (NOW + timedelta(hours=5)).isoformat(),
    }
    accepted = {"event": "accepted", "client_order_id": "n1", "order_id": "nba-1"}
    nba.write_text(json.dumps(intent) + "\n" + json.dumps(accepted) + "\n")
    world["exchange"].resting = [{"order_id": "nba-1", "ticker": TICKER}]
    report, markets = run(world)
    assert markets == [] and world["exchange"].placed == []


def test_unarmed_auto_run_is_shadow_only(world, monkeypatch, tmp_path, capsys):
    import live.production_lock as production_lock

    state = tmp_path / "state"
    monkeypatch.setattr(P, "STATE", state)
    monkeypatch.setattr(bot, "public_api", lambda: world["public"])
    monkeypatch.setattr(bot, "armed", lambda env: False)

    def no_client(*args, **kwargs):
        raise AssertionError("shadow mode must not build a trading client")

    def no_lock():
        raise AssertionError("shadow mode must not take the account lock")

    monkeypatch.setattr(bot, "TradingClient", no_client)
    monkeypatch.setattr(production_lock, "account_lock", no_lock)
    monkeypatch.setattr("sys.argv", ["prod_spread_auto", "--auto"])
    soon = datetime.now(UTC) + timedelta(hours=5)
    world["quotes"][TICKER]["expected_expiration_time"] = soon.isoformat()
    # Real clock here: TICKER's start comes from a milestone of a validated
    # type (another listed, narrow market carries a ticker time to check).
    # No series offset, which would be earlier and win.
    monkeypatch.setattr(P, "SERIES_START_OFFSET_HOURS", {})
    real_start = bot.ticker_start
    untimed = TICKER.rsplit("-", 1)[0]
    monkeypatch.setattr(
        bot, "ticker_start", lambda e: None if e == untimed else real_start(e)
    )
    check_start = (soon - timedelta(hours=2)).astimezone(bot.NY)
    check = f"KXDOTA2GAME-{check_start:%y%b%d%H%M}".upper() + "CDEF"
    world["quotes"][f"{check}-C"] = {
        **market(f"{check}-C", bid=0.40, ask=0.45),  # too narrow to quote
        "expected_expiration_time": soon.isoformat(),
    }

    def milestones(event):
        start = bot.ticker_start(event) or soon - timedelta(hours=1)
        return {
            "milestones": [
                {
                    "start_date": start.isoformat(),
                    "type": "basketball_game",
                    "primary_event_tickers": [event],
                }
            ]
        }

    world["public"]["fetch_milestones"] = milestones
    bot.main()
    report = json.loads((state / "last_scan.json").read_text())
    assert report["mode"] == "shadow" and "live" not in report
    assert report["shadow"]["quotes"] == 2
    # Live windows are scored only after a live pass has copied the fills.
    assert "live_windows_scored" not in report and "live_windows_error" not in report
    assert not (state / "journal.jsonl").exists()


def test_preflight_reads_only_and_reports_counts(world):
    ex = world["exchange"]
    ex.place = ex.cancel = None  # any order call would fail the test
    env = {**ENV, "SPREAD_AUTO_ARM": "NO"}
    result = bot.preflight(ex, env, NOW, world["dir"], world["public"])
    assert result["ready"] and result["eligible_markets_now"] == 1
    assert result["armed"] is False and result["spread_resting"] == 0
    bad = bot.preflight(
        ex, {**env, "ALLOW_PRODUCTION_TRADING": ""}, NOW, world["dir"], world["public"]
    )
    assert bad == {"ready": False, "failures": ["ALLOW_PRODUCTION_TRADING is not YES"]}


def test_deploy_units_and_owner_script():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    unit = (root / "deploy/market-maker-prod-spread-auto.service").read_text()
    for line in (
        "User=trader",
        "UMask=0077",
        "EnvironmentFile=-/etc/market-maker-spread.env",
        "ExecCondition=+/usr/bin/flock -n /run/lock/smm-production-release.lock",
    ):
        assert line in unit
    # The timer only ever runs --auto: live needs the owner's two arm steps.
    assert "-m live.prod_spread_auto --auto\n" in unit and "--live" not in unit
    timer = (root / "deploy/market-maker-prod-spread-auto.timer").read_text()
    assert "OnCalendar=*-*-* *:03/10:00 UTC" in timer
    setup = (root / "deploy/setup_spread_maker.sh").read_text()
    assert "FETCH_HEAD:deploy/" in setup  # units come from GitHub main
    for funded in ("prod-nba-auto.timer", "prod-nfl-auto", "prod-nba-auto.service"):
        assert funded not in setup
    assert "cat $" not in setup and 'cat "' not in setup  # never prints settings
    assert "printf 'SPREAD_AUTO_ARM=%s\\n'" in setup
    assert str(P.ARM_MARKER) in setup and str(P.STATE) in setup
    assert "as_trader --reconcile" in setup
    # The other preflights read under the account lock (never mid-order).
    nba = (root / "live/prod_nba_auto.py").read_text()
    assert "account_lock() if args.live or args.preflight else nullcontext()" in nba


def test_refused_order_found_filled_is_recorded_as_accepted(world):
    ex = world["exchange"]
    original = ex.place

    def refused_but_executed(order):
        original(order)  # it reached the book and filled at once
        ex.history["executed"].append(ex.resting.pop())
        raise TradingError("POST /portfolio/events/orders -> HTTP 409: conflict")

    ex.place = refused_but_executed
    report, _ = run(world)
    assert report["accepted"] == 2 and "rejected" not in report
    _, accepted, refused = bot.records(journal(world))
    assert len(accepted) == 2 and not refused


def test_failed_check_after_a_refusal_is_ambiguous_and_owner_reconciles(world):
    ex = world["exchange"]
    ex.fail_place = TradingError("POST /portfolio/events/orders -> HTTP 429: slow down")
    real_orders = ex.orders

    def broken(status="resting", ticker=None):
        if ticker is not None:
            raise OSError("timed out")
        return real_orders(status, ticker)

    ex.orders = broken
    with pytest.raises(TradingError, match="Ambiguous spread submission"):
        run(world)
    assert [e["event"] for e in journal(world)][-1] == "unknown_outcome"
    with pytest.raises(TradingError, match="Ambiguous"):
        shared.state_for(ex, "nba", NOW)  # every bot is blocked
    ex.orders = real_orders
    path = world["dir"] / "journal.jsonl"
    # Too soon after the intent: nothing can be concluded yet.
    soon = bot.reconcile(ex, path, NOW + timedelta(minutes=2))
    assert soon["too_recent_try_again_later"] == 1 and soon["bots_can_trade"] is False
    later = bot.reconcile(ex, path, NOW + timedelta(minutes=11))
    assert later == {"never_placed": 1, "bots_can_trade": True}
    shared.state_for(ex, "nba", NOW)  # unblocked
    ex.fail_place = None
    report, _ = run(world, NOW + timedelta(minutes=10))
    assert report["accepted"] == 2


def test_reconcile_finds_an_order_that_did_reach_the_book(world):
    ex = world["exchange"]
    original = ex.place

    def timed_out_after_sending(order):
        original(order)
        raise TimeoutError("read timed out")

    ex.place = timed_out_after_sending
    with pytest.raises(TradingError, match="Ambiguous"):
        run(world)
    path = world["dir"] / "journal.jsonl"
    result = bot.reconcile(ex, path, NOW + timedelta(minutes=2))
    assert result == {"found_on_exchange": 1, "bots_can_trade": True}
    state, _ = shared.state_for(ex, "spread", NOW)
    assert len(state["resting"]) == 0  # the halt cancelled it; it is still owned
    assert any(e.get("reconciled") for e in bot.load_events(path))


def test_a_halt_cancels_our_quotes_first(world):
    run(world)
    ex = world["exchange"]
    ex.resting.append({"order_id": "manual-1", "ticker": "KXOTHER-1"})  # unowned
    with pytest.raises(TradingError, match="Unowned resting"):
        run(world, NOW + timedelta(minutes=10))
    assert ex.resting == [{"order_id": "manual-1", "ticker": "KXOTHER-1"}]


def test_no_new_orders_after_the_pass_deadline(world):
    report, _ = bot.pass_live(
        world["exchange"],
        ENV,
        NOW,
        world["dir"],
        world["public"],
        require_shard=lambda client, ticker, cost: 1,
        deadline=0.0,  # long past
    )
    assert report["placed"] == 0 and report["skip_out_of_time"] == 1
    bot.STOP["requested"] = True
    try:
        report, _ = run(world, NOW + timedelta(minutes=1))
        assert report["placed"] == 0  # SIGTERM: finish, place nothing more
    finally:
        bot.STOP["requested"] = False


def test_a_broken_link_named_kill_still_halts(world, monkeypatch, tmp_path):
    import contextlib

    import live.production_lock as production_lock

    run(world)
    monkeypatch.setattr(P, "STATE", world["dir"])
    (world["dir"] / "KILL").symlink_to(tmp_path / "missing")
    monkeypatch.setattr(bot, "TradingClient", lambda **kwargs: world["exchange"])
    monkeypatch.setattr(production_lock, "account_lock", contextlib.nullcontext)
    monkeypatch.setattr("sys.argv", ["prod_spread_auto", "--auto"])
    bot.main()
    assert world["exchange"].resting == [] and len(world["exchange"].canceled) == 2


def test_status_reports_live_and_shadow_apart(world, capsys, monkeypatch):
    run(world)
    fill_placed(world, 0, 5)  # YES 41c
    fill_placed(world, 1, 6)  # NO 49c: five locked pairs, 5 x 10c
    run(world, NOW + timedelta(minutes=10))

    class Clock(datetime):
        """status() reads the real clock; "today" must be the fills' day."""

        @classmethod
        def now(cls, tz=None):
            return NOW + timedelta(minutes=20)

    monkeypatch.setattr(bot, "datetime", Clock)
    bot.status(world["dir"])
    out = capsys.readouterr().out
    assert "LIVE realized P&L (from fills): today $+0.50" in out
    assert "SHADOW (simulated" in out


def test_a_brief_read_failure_keeps_our_quotes(world):
    run(world)
    ex = world["exchange"]

    def throttled():
        raise TradingError("GET /portfolio/positions -> HTTP 429: too many requests")

    ex.positions = throttled
    with pytest.raises(TradingError, match="429"):
        run(world, NOW + timedelta(minutes=10))
    assert len(ex.resting) == 2 and not ex.canceled  # they expire on their own


def test_a_failed_shard_check_stops_placing_without_a_halt(world):
    calls = {"n": 0}

    def flaky(client, ticker, cost):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("timed out")
        return 1

    report, _ = bot.pass_live(
        world["exchange"], ENV, NOW, world["dir"], world["public"], require_shard=flaky
    )
    assert report["accepted"] == 1 and report["shard_check_failed"] == 1
    bot.records(journal(world))  # nothing ambiguous: the second order was never sent


def test_deadline_is_checked_again_just_before_the_order(world, monkeypatch):
    checks = iter([False, True])
    monkeypatch.setattr(bot, "out_of_time", lambda deadline: next(checks, True))
    report, _ = run(world)
    assert report["out_of_time"] == 1 and report["placed"] == 0
    assert [e for e in journal(world) if e["event"] == "intent"] == []


def test_kill_works_even_with_a_torn_journal(world):
    run(world)
    ex = world["exchange"]
    ex.resting.append(
        {"order_id": "nba-1", "ticker": "KXNBAPTS-X", "client_order_id": "smm-0a1b"}
    )
    path = world["dir"] / "journal.jsonl"
    path.write_text(path.read_text() + '{"event": "intent", "client')  # torn
    before = path.read_text()
    assert bot.cancel_owned_on_kill(ex, path) == 2
    assert [o["order_id"] for o in ex.resting] == ["nba-1"]  # NBA's order stays
    assert path.read_text() == before  # nothing appended to the damaged journal


def test_ledger_keeps_fills_the_exchange_no_longer_lists(world, monkeypatch):
    monkeypatch.setattr(P, "DAILY_LOSS_STOP", 0.70)
    run(world)
    ex = world["exchange"]
    fill_placed(world, 0, 5)
    world["quotes"][TICKER] = market(bid=0.15, ask=0.27)
    run(world, NOW + timedelta(minutes=10))  # journals the YES fill
    fill_placed(world, len(ex.placed) - 1, 12)  # the NO at 74c
    ex.fills_ = ex.fills_[1:]  # the old YES fill has aged out of the listing
    report, _ = run(world, NOW + timedelta(minutes=20))
    assert report["decision"] == "spread_loss_stop"
    assert report["daily"] == pytest.approx(-0.75)


def test_reconcile_never_calls_a_found_order_absent(world):
    ex = world["exchange"]
    original = ex.place

    def lost_reply(order):
        original(order)
        ex.history["executed"].append({**ex.resting.pop(), "order_id": None})
        raise TimeoutError("read timed out")

    ex.place = lost_reply
    with pytest.raises(TradingError, match="Ambiguous"):
        run(world)
    result = bot.reconcile(ex, world["dir"] / "journal.jsonl", NOW + timedelta(hours=1))
    assert result["found_without_order_id_check_by_hand"] == 1
    assert result["bots_can_trade"] is False


def test_partly_filled_quote_keeps_its_place_and_the_cap_holds(world):
    run(world)
    ex = world["exchange"]
    fill_placed(world, 0, 5, count=2)  # 2 of 5 YES fill; 3 still rest
    report, _ = run(world, NOW + timedelta(minutes=10))
    # Room for 3 more YES: the 3 resting fit, so it keeps its queue place.
    assert report["resting_kept"] == 2 and report["placed"] == 0 and not ex.canceled
    # Exposure: 3 resting YES + 5 resting NO + 2 held YES, all at cost.
    assert report["exposure_dollars"] == pytest.approx(3 * 0.41 + 5 * 0.49 + 2 * 0.41)
    fill_placed(world, 0, 15, count=3)  # the rest fill: 5 YES held
    report, _ = run(world, NOW + timedelta(minutes=20))
    assert report["placed"] == 0  # at the cap: no YES order at all


def test_a_partly_filled_order_is_not_mistaken_for_someone_else(world):
    run(world)
    ex = world["exchange"]
    fill_placed(world, 0, 5, count=2)  # our YES at 41c: 3 left in the book
    # Another trader joins at 41c with 2. The book shows 5 at 41c: 3 ours.
    original = world["public"]["fetch_orderbook"]

    def joined(ticker):
        book = original(ticker)
        book["yes_dollars"] = sorted(book["yes_dollars"] + [["0.41", "2.00"]])
        return book

    world["public"]["fetch_orderbook"] = joined
    report, _ = run(world, NOW + timedelta(minutes=10))
    # Their 41c is now the best other bid: we move to 42c with the 3 we
    # still have room for (holding 2).
    assert (ex.placed[-1].side, ex.placed[-1].price_cents, ex.placed[-1].count) == (
        "yes",
        42,
        3,
    )


def test_a_resting_order_bigger_than_the_room_is_replaced(world):
    run(world)
    ex = world["exchange"]
    ex.positions_ = [{"market_ticker": TICKER, "position_fp": "4.00"}]  # 4 YES held
    report, _ = run(world, NOW + timedelta(minutes=10))
    # The 5-contract YES quote would take net YES to 9: cancelled and
    # replaced by a 1-contract quote.
    assert report["canceled"] == 1
    assert (ex.placed[-1].side, ex.placed[-1].count) == ("yes", 1)


def test_missing_remaining_count_falls_back_to_fills(world):
    run(world)
    ex = world["exchange"]
    fill_placed(world, 0, 5, count=2)
    for o in ex.resting:
        o.pop("remaining_count_fp")  # an order listing without the field
    report, _ = run(world, NOW + timedelta(minutes=10))
    assert report["resting_kept"] == 2 and report["placed"] == 0
    for o in ex.resting:
        o["remaining_count_fp"] = "9.00"  # more than we ever ordered
    with pytest.raises(TradingError, match="resting count"):
        run(world, NOW + timedelta(minutes=20))


def test_shadow_scores_five_contracts():
    assert bot.expected_fill(2, 0.25, 5) == pytest.approx(0.5)  # E[Bin(2, .25)]
    assert bot.expected_fill(1000, 0.25, 5) == pytest.approx(5.0)
    assert bot.expected_fill(3, 1.0, 5) == 3.0 and bot.expected_fill(0, 0.25, 5) == 0
    assert bot.expected_fill(20, 0.25, 5) == pytest.approx(
        sum(
            min(k, 5) * __import__("math").comb(20, k) * 0.25**k * 0.75 ** (20 - k)
            for k in range(21)
        )
    )


def test_pilot_limits_are_the_owner_approved_ones():
    # RESEARCH_LOG.md, 2026-10-22, "5 contracts per order" (old: 1, 1, $25,
    # $5, $15), then "Spread maker v3" (2026-10-23; v2: 5 and 5, 4-7 hours,
    # 30 reads, 300 submissions a day) and its "changes after review" (first
    # draft: one_off_milestone trusted, 35 median offsets). Change these only
    # through a new, recorded amendment.
    assert P.STRATEGY_VERSION == "spread-maker-v3-24h-starts"
    assert (P.CONTRACTS, P.MAX_NET_PER_MARKET) == (2, 2)
    assert P.MAX_START_LOOKUPS_PER_PASS == 60
    assert P.TRUSTED_MILESTONE_TYPES == {
        "baseball_game",
        "basketball_game",
        "cricket_match",
        "hockey_tournament",
    }
    assert "esports_match" in P.NEVER_TRUSTED_MILESTONE_TYPES
    assert not P.TRUSTED_MILESTONE_TYPES & P.NEVER_TRUSTED_MILESTONE_TYPES
    assert P.START_OFFSET_MARGIN_MINUTES == 30
    # The 99th-percentile gaps of the final replay, exactly.
    final = json.loads(
        (
            Path(__file__).parents[1] / "outputs/research/spread_v3_final.json"
        ).read_text()
    )
    assert P.SERIES_START_OFFSET_HOURS == final["series_gap_hours"]
    assert len(P.SERIES_START_OFFSET_HOURS) == 31
    assert set(P.SERIES_START_OFFSET_HOURS) <= set(P.SERIES)
    assert P.SERIES_START_OFFSET_HOURS["KXNBAPTSLEADER"] == 6.0
    assert P.SERIES_START_OFFSET_HOURS["KXRLGAME"] == 5.75
    assert P.NO_START_SERIES == {"KXBRENTD", "KXINXDUD", "KXTNOTED"}
    assert not P.NO_START_SERIES & set(P.SERIES_START_OFFSET_HOURS)
    assert (P.MAX_ACTIVE_COST, P.DAILY_LOSS_STOP, P.CUMULATIVE_LOSS_STOP) == (
        60,
        10,
        40,
    )
    assert (P.MAX_ORDERS_PER_PASS, P.MAX_SUBMISSIONS_PER_DAY) == (20, 1500)
    assert P.MIN_SPREAD_CENTS == 8 and P.WINDOW_HOURS == (4.0, 24.0)
    # Account-wide total stop -$60 -> -$100 on 2026-10-23 ("NBA rules v6");
    # the spread maker's own limits above are unchanged, 8c spreads included.
    assert shared.ACCOUNT_LOSS_STOPS == {"daily": 20.0, "cumulative": 100.0}


def test_a_partial_fill_just_before_a_requote_cancel_never_breaks_the_cap(world):
    run(world)
    ex = world["exchange"]
    world["quotes"][TICKER] = market(bid=0.44, ask=0.52)  # YES moves to 45c
    original = ex.cancel

    def filled_four_first(order_id, ticker=None):
        if order_id == "oid-1":  # 4 of the 5 YES fill just before the cancel
            fill_placed(world, 0, 9, count=4)
        return original(order_id, ticker)

    ex.cancel = filled_four_first
    report, _ = run(world, NOW + timedelta(minutes=10))
    # Only 1 was cancelled: 4 filled after the account read. No new YES in
    # that market this pass, and the 4 count toward open exposure.
    assert report["skip_just_filled"] >= 1 and report["placed"] == 0
    assert report["exposure_dollars"] >= 5 * 0.41 + 5 * 0.49 - 1e-9
    report, _ = run(world, NOW + timedelta(minutes=20))
    yes = [o for o in ex.placed[2:] if o.side == "yes"]
    assert [o.count for o in yes] == [1]  # holding 4: room for 1


def test_journal_fill_copies_without_count_fp_do_not_halt(world):
    run(world)
    ex = world["exchange"]
    fill_placed(world, 0, 5)
    ex.fills_[0].pop("count_fp")
    ex.fills_[0]["count"] = 5  # an older fill shape: count only
    run(world, NOW + timedelta(minutes=10))
    run(world, NOW + timedelta(minutes=20))  # now the journal copy is merged
    copies = [e for e in journal(world) if e["event"] == "fill"]
    assert copies and all(v is not None for e in copies for v in e.values())
    state, context = shared.state_for(ex, "nba", NOW)
    assert "unavailable" not in context["account_pnl"]


def test_kill_keeps_going_after_one_order_already_filled(world):
    run(world)
    ex = world["exchange"]
    original = ex.cancel

    def first_is_gone(order_id, ticker=None):
        if order_id == "oid-1":
            ex.resting = [o for o in ex.resting if o["order_id"] != order_id]
            raise TradingError(
                "DELETE /portfolio/events/orders/oid-1 -> HTTP 404: gone"
            )
        return original(order_id, ticker)

    ex.cancel = first_is_gone
    path = world["dir"] / "journal.jsonl"
    path.write_text(path.read_text() + '{"torn')  # unreadable: prefix fallback
    bot.cancel_owned_on_kill(ex, path)
    assert ex.resting == []  # the second order was still cancelled


def test_one_balance_read_per_pass_and_orders_reserve_from_it():
    class Reads:
        env, dry_run, can_sign = "prod", False, True

        def __init__(self):
            self.calls = []

        def _request(self, method, path, params=None, body=None):
            assert method == "GET"
            self.calls.append(path)
            if path == "/portfolio/balance":
                return {"balance_breakdown": [{"exchange_index": 3, "balance": "5.00"}]}
            ticker = path.rsplit("/", 1)[1]
            return {"market": {"ticker": ticker, "exchange_index": 3}}

    client, funding = Reads(), bot.PassShardFunding()
    assert funding(client, "KXA-1", 2.05) == 3
    assert funding(client, "KXA-2", 2.45) == 3
    with pytest.raises(TradingError, match="SHARD_UNFUNDED_3"):
        funding(client, "KXA-3", 0.60)  # $5.00 - $4.50 reserved < $0.60
    assert client.calls.count("/portfolio/balance") == 1
    with pytest.raises(TradingError, match="Invalid market ticker"):
        funding(client, "NBA-1", 1.0)


def test_fill_share_scores_finished_windows_from_public_prints(world):
    run(world)  # YES 5 @ 41c and NO 5 @ 49c rest from NOW
    fill_placed(world, 0, 5, count=2)  # 2 of the YES fill
    run(world, NOW + timedelta(minutes=10))  # copies the fill into the journal
    at = (NOW + timedelta(minutes=30)).isoformat()
    calls = []

    def trades(ticker, start, end):
        calls.append(ticker)
        return [
            # 8 contracts sold at 40c went through our 41c YES bid ...
            {
                "created_time": at,
                "yes_price": 0.40,
                "count": 8,
                "taker_outcome_side": "no",
            },
            # ... nothing reached our NO bid (a YES offer at 51c).
            {
                "created_time": at,
                "yes_price": 0.50,
                "count": 3,
                "taker_outcome_side": "yes",
            },
        ]

    state = world["dir"]
    # Windows still open (or too fresh) are not scored yet.
    assert bot.score_live_windows(state, NOW + timedelta(minutes=60), trades) == 0
    assert bot.score_live_windows(state, NOW + timedelta(minutes=71), trades) == 2
    assert (
        bot.score_live_windows(state, NOW + timedelta(minutes=90), trades) == 0
    )  # once
    assert calls == [TICKER]
    share = bot.fill_share(journal(world), bot.load_events(state / "shadow.jsonl"))
    # Up to 5 of the 8 were ours to take first in line; we got 2.
    assert share["first_in_line_contracts"] == 5 and share["filled_contracts"] == 2
    assert share["fill_share"] == 0.4 and share["orders_traded_through"] == 1


def test_fill_share_reports_the_cautious_replay_on_the_same_windows():
    v2 = P.STRATEGY_VERSION
    events = [
        {"event": "intent", "client_order_id": "a", "strategy_version": v2},
        {"event": "intent", "client_order_id": "b", "strategy_version": v2},
        # A v1 order's window is not part of v2's measurement.
        {
            "event": "intent",
            "client_order_id": "old",
            "strategy_version": "spread-maker-v1",
        },
        {"event": "accepted", "client_order_id": "a", "order_id": "1"},
        {"event": "accepted", "client_order_id": "b", "order_id": "2"},
        {"event": "fill", "fill_id": "f1", "order_id": "1", "count_fp": "0.49"},
        {"event": "fill", "fill_id": "f1", "order_id": "1", "count_fp": "0.49"},
    ]
    windows = [
        {"event": "live_window", "client_order_id": "a", "size": 5, "through": 86},
        {"event": "live_window", "client_order_id": "a", "size": 5, "through": 86},
        {"event": "live_window", "client_order_id": "b", "size": 5, "through": 0.4},
        {"event": "live_window", "client_order_id": "old", "size": 5, "through": 50},
    ]
    share = bot.fill_share(events, windows)
    # One row per order and per fill; a fractional print still counts as
    # traded through.
    assert share["orders_scored"] == 2 and share["orders_traded_through"] == 2
    assert share["filled_contracts"] == 0.49 and share["first_in_line_contracts"] == 5.4
    # With 86 contracts through, a 25% flow share would almost surely have
    # filled all 5: the cautious benchmark is far above 0.25.
    assert share["cautious_replay_share"] > 0.9
    assert share["fill_share"] == round(0.49 / 5.4, 3)


def test_prints_without_a_usable_size_count_for_nothing():
    at = (NOW + timedelta(minutes=1)).isoformat()
    trades = [
        {
            "created_time": at,
            "yes_price": 0.40,
            "count": float("nan"),
            "taker_outcome_side": "no",
        },
        {
            "created_time": at,
            "yes_price": 0.40,
            "count": None,
            "taker_outcome_side": "no",
        },
        {"created_time": at, "yes_price": 0.40, "count": 2, "taker_outcome_side": "no"},
    ]
    through = bot.contracts_through(trades, "yes", 41, NOW, NOW + timedelta(hours=1))
    assert through == 2
    # An older record with an unusable count is skipped, not a crash.
    share = bot.fill_share(
        [],
        [
            {
                "event": "live_window",
                "client_order_id": "x",
                "size": 5,
                "through": float("nan"),
            }
        ],
    )
    assert share["orders_scored"] == 0 and share["fill_share"] is None


def test_scoring_stops_at_its_deadline(world):
    run(world)
    calls = []
    late = bot.score_live_windows(
        world["dir"],
        NOW + timedelta(minutes=80),
        lambda *a: calls.append(a) or [],
        deadline=time.monotonic() - 1,
    )
    assert late == 0 and calls == []


def test_window_times_use_the_exchange_replies_of_the_same_pass():
    sent = NOW
    events = [
        {
            "event": "intent",
            "strategy_version": P.STRATEGY_VERSION,
            "client_order_id": "a",
            "utc": sent.isoformat(),
            "ticker": TICKER,
            "side": "yes",
            "price_cents": 41,
            "count": 5,
        },
        {
            "event": "accepted",
            "client_order_id": "a",
            "order_id": "1",
            "utc": (sent + timedelta(seconds=40)).isoformat(),
        },
        {
            "event": "cancel_intent",
            "order_id": "1",
            "utc": (sent + timedelta(minutes=10)).isoformat(),
        },
        {
            "event": "cancel_accepted",
            "order_id": "1",
            "utc": (sent + timedelta(minutes=11)).isoformat(),
        },
        # Accepted by the owner's reconcile much later: its time is not used.
        {
            "event": "intent",
            "strategy_version": P.STRATEGY_VERSION,
            "client_order_id": "b",
            "utc": sent.isoformat(),
            "ticker": TICKER,
            "side": "no",
            "price_cents": 49,
            "count": 5,
        },
        {
            "event": "accepted",
            "client_order_id": "b",
            "order_id": "2",
            "utc": (sent + timedelta(hours=3)).isoformat(),
            "reconciled": "owner_signed_lookup",
        },
    ]
    windows = {
        w["client_order_id"]: w
        for w in bot.live_windows(events, set(), NOW + timedelta(hours=5))
    }
    assert windows["a"]["start"] == sent + timedelta(seconds=40)
    assert windows["a"]["end"] == sent + timedelta(minutes=11)
    assert windows["b"]["start"] == sent
    assert windows["b"]["end"] == sent + timedelta(minutes=65)


def test_a_cancelled_order_is_scored_only_up_to_its_cancel(world):
    run(world)
    world["quotes"][TICKER] = market(bid=0.42, ask=0.52)
    run(world, NOW + timedelta(minutes=10))  # YES @ 41c cancelled, re-posted at 43c
    windows = bot.live_windows(journal(world), set(), NOW + timedelta(minutes=200))
    first_yes = next(w for w in windows if w["price_cents"] == 41)
    assert first_yes["end"] == NOW + timedelta(minutes=10)
    assert {w["price_cents"] for w in windows} == {41, 43, 49}


# ------------------------------------------------- v2: pregame only


START = NOW + timedelta(hours=4)  # TICKER's start written in the ticker


def test_start_times_come_from_the_ticker_in_new_york_time():
    assert bot.ticker_start(TICKER.rsplit("-", 1)[0]) == START
    assert bot.ticker_start("KXR6GAME-26OCT222000L5FAZE") == datetime(
        2026, 10, 23, 0, 0, tzinfo=UTC
    )
    assert bot.ticker_start("KXAHLGAME-26JAN171900LEHCHA") == datetime(
        2026, 1, 18, 0, 0, tzinfo=UTC
    )  # winter: five hours behind UTC
    for untimed in (
        "KXCS2GAME-26MAR20ISGATRIX",
        "KXINXDUD-26AUG10H1600",
        "KXBRENTD-26JUL0117",
        "KXNCAAFSPREAD-26OCT22LIBKENN",
        "KXR6GAME-26OCT222560AB",  # not a time
        "",
        None,
    ):
        assert bot.ticker_start(untimed) is None


def test_milestone_start_takes_the_game_not_the_tournament():
    expires = NOW + timedelta(hours=6)
    event = "KXCS2GAME-26OCT22ABCD"
    payload = {
        "milestones": [
            # A tournament that began days ago is not this game's start.
            {"start_date": "2026-10-19T12:00:00Z", "related_event_tickers": [event]},
            {
                "start_date": (NOW + timedelta(hours=3)).isoformat(),
                "primary_event_tickers": [event],
            },
            {
                "start_date": (NOW + timedelta(hours=2)).isoformat(),
                "related_event_tickers": [event],
            },
            {
                "start_date": (NOW + timedelta(hours=1)).isoformat(),
                "primary_event_tickers": ["OTHER"],
            },
            {"start_date": "not a date", "primary_event_tickers": [event]},
        ]
    }
    got = bot.milestone_start(event, expires, lambda e: payload)
    assert got == NOW + timedelta(hours=2)
    assert bot.milestone_start(event, expires, lambda e: None) is None
    # Ticker and milestone both known: the earlier one counts.
    timed = TICKER.rsplit("-", 1)[0]
    assert bot.event_start(timed, {timed: START - timedelta(minutes=30)}) == (
        START - timedelta(minutes=30)
    )


def test_markets_are_quoted_only_well_before_the_start():
    assert P.MIN_LEAD_MINUTES == P.ORDER_LIFETIME_MINUTES + P.CANCEL_LEAD_MINUTES
    reasons = bot.Counter()
    untimed = market("KXCS2GAME-26OCT22ABCD-A")
    rows = bot.eligible_markets(
        [market(), untimed], "KXDOTA2GAME", NOW, reasons=reasons
    )
    assert [r["ticker"] for r in rows] == [TICKER] and rows[0]["postable"]
    assert rows[0]["event_start_utc"] == START.isoformat()
    assert reasons["no_event_start"] == 1  # no start known: never quoted
    late = market(hours=9.0)  # expires five hours after the start
    soon = START - timedelta(minutes=60)  # 60 minutes ahead: keep, add nothing
    row = bot.eligible_markets([late], "KXDOTA2GAME", soon)
    assert len(row) == 1 and not row[0]["postable"]
    reasons = bot.Counter()
    assert (
        bot.eligible_markets(
            [late], "KXDOTA2GAME", START - timedelta(minutes=5), reasons=reasons
        )
        == []
    )
    assert reasons["event_starting"] == 1


def test_orders_expire_before_the_start_and_record_it(world):
    run(world)
    intents = [e for e in journal(world) if e["event"] == "intent"]
    assert {i["event_start_utc"] for i in intents} == {START.isoformat()}
    for order in world["exchange"].placed:
        assert order.expiration_ts <= int(
            (START - timedelta(minutes=P.CANCEL_LEAD_MINUTES)).timestamp()
        )
    # 65 minutes is the normal life; a start moved earlier caps it.
    early = {"event_start_utc": (NOW + timedelta(minutes=40)).isoformat()}
    assert bot.quote_expiry(NOW, early) == NOW + timedelta(minutes=20)
    assert bot.quote_expiry(NOW, {}) == NOW + timedelta(minutes=65)


def test_resting_quotes_are_cancelled_before_the_start(world):
    world["quotes"][TICKER]["expected_expiration_time"] = (
        START + timedelta(hours=5)
    ).isoformat()
    first = START - timedelta(hours=2)
    run(world, first)
    ex = world["exchange"]
    assert len(ex.resting) == 2
    # 70 minutes before the start: the quotes stay, nothing new is placed.
    report, _ = run(world, START - timedelta(minutes=70))
    assert report.get("canceled", 0) == 0 and len(ex.placed) == 2
    assert report.get("skip_near_start", 0) == 0  # both sides still resting
    # 8 minutes before: cancelled even though the order book cannot be read.
    world["public"]["fetch_orderbook"] = lambda ticker: None
    report, _ = run(world, START - timedelta(minutes=8))
    assert report["canceled_event_start"] == 2 and ex.resting == []
    assert {e["reason"] for e in journal(world) if e["event"] == "cancel_intent"} == {
        "event_start"
    }


def test_a_start_moved_earlier_cancels_at_the_new_start(world):
    run(world)
    timed = TICKER.rsplit("-", 1)[0]
    world["public"]["event_starts"] = {timed: NOW + timedelta(minutes=30)}
    report, _ = run(world, NOW + timedelta(minutes=25))
    assert report["canceled_event_start"] == 2


def test_v1_orders_without_a_recorded_start_are_cancelled(world):
    run(world)
    path = world["dir"] / "journal.jsonl"
    lines = []
    for line in path.read_text().splitlines():
        e = json.loads(line)
        if e.get("event") == "intent":
            e.pop("event_start_utc")
            e["event_ticker"] = "KXDOTA2GAME-26OCT22AB"  # v1: no time known
        lines.append(json.dumps(e, sort_keys=True))
    path.write_text("\n".join(lines) + "\n")
    report, _ = run(world, NOW + timedelta(minutes=10))
    assert report["canceled_event_start"] == 2


def test_shadow_quotes_only_markets_open_for_new_orders(world):
    world["quotes"][TICKER]["expected_expiration_time"] = (
        START + timedelta(hours=5)
    ).isoformat()
    soon = START - timedelta(minutes=60)
    summary = bot.run_shadow(world["dir"], soon, world["public"])
    assert summary["quotes"] == 0
    summary = bot.run_shadow(world["dir"], START - timedelta(hours=2), world["public"])
    assert summary["quotes"] == 2


def _milestones(calls, shift=timedelta(0), kind="basketball_game"):
    """Milestones that give the ticker's own start (plus ``shift``), or two
    hours from NOW for events without a time."""

    def fetch(event):
        calls.append(event)
        start = bot.ticker_start(event)
        start = NOW + timedelta(hours=2) if start is None else start + shift
        return {
            "milestones": [
                {
                    "start_date": start.isoformat(),
                    "type": kind,
                    "primary_event_tickers": [event],
                }
            ]
        }

    return fetch


def _listing(event, hours=5.0):
    return {
        "event_ticker": event,
        "expected_expiration_time": (NOW + timedelta(hours=hours)).isoformat(),
    }


def test_milestone_starts_are_cached_and_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "MAX_START_LOOKUPS_PER_PASS", 4)
    listings = {
        # KXTESTGAME has no ticker times and no usual-gap entry: milestones only.
        "KXTESTGAME": [_listing(f"KXTESTGAME-26OCT22E{i}") for i in range(3)],
        # Two series whose tickers carry the start: the checks.
        "KXDOTA2GAME": [market()],
        "KXR6GAME": [_listing("KXR6GAME-26OCT221900ABCD")],
    }
    calls = []
    starts, counts = bot.prefetch_starts(listings, NOW, tmp_path, _milestones(calls))
    # Validated types are trusted without live matches; two checks, two reads.
    assert "basketball_game" in counts["milestone_types_trusted"]
    assert len(calls) == 4 and counts["with_milestone_start"] == 2
    assert counts["events_without_ticker_time"] == 3
    assert counts["with_series_offset_start"] == 0
    assert oct((tmp_path / "event_starts.json").stat().st_mode & 0o777) == "0o600"
    # Next pass: checks and two answers come from the cache; one read.
    starts, counts = bot.prefetch_starts(
        listings, NOW + timedelta(minutes=10), tmp_path, _milestones(calls)
    )
    assert len(calls) == 5 and len(starts) == 3
    # After its deadline a pass reads nothing new.
    later = NOW + timedelta(hours=1)
    _, counts = bot.prefetch_starts(
        listings, later, tmp_path, _milestones(calls), deadline=time.monotonic() - 1
    )
    assert counts["milestone_reads"] == 0


def test_preflight_compares_milestones_with_ticker_times(world):
    public = bot.prefetch(world["public"])
    public["fetch_milestones"] = _milestones([], shift=timedelta(minutes=5))
    check = bot.milestone_check(public, NOW)
    assert check["events_compared"] == 1 and check["later_than_ticker"] == 1
    assert check["largest_late_minutes"] == 5.0 and check["matched"] == 0
    public["fetch_milestones"] = _milestones([])
    check = bot.milestone_check(public, NOW)
    assert check["matched"] == 1 and check["milestone_types"] == {"basketball_game": 1}


def test_no_new_quote_within_85_minutes_of_the_start(world):
    world["quotes"][TICKER]["expected_expiration_time"] = (
        START + timedelta(hours=5)
    ).isoformat()
    run(world, START - timedelta(hours=2))
    # The book moves 70 minutes before the start: the old quotes go and no
    # new ones replace them (they could still be resting at the start).
    world["quotes"][TICKER] = {
        **world["quotes"][TICKER],
        "yes_bid_dollars": "0.42",
        "yes_ask_dollars": "0.54",
    }
    report, _ = run(world, START - timedelta(minutes=70))
    assert report["canceled"] == 2 and report["skip_near_start"] == 2
    assert len(world["exchange"].placed) == 2 and world["exchange"].resting == []


def test_milestones_later_than_ticker_times_are_not_used(tmp_path):
    listings = {
        "KXDOTA2GAME": [market()],
        "KXR6GAME": [_listing("KXR6GAME-26OCT221900ABCD")],
        "KXTESTGAME": [_listing("KXTESTGAME-26OCT22E0")],
    }
    # A validated type seen 5 minutes late on a ticker-timed event is revoked.
    late = _milestones([], shift=timedelta(minutes=5))
    starts, counts = bot.prefetch_starts(listings, NOW, tmp_path, late)
    assert "basketball_game" not in counts["milestone_types_trusted"] and starts == {}
    assert counts["milestone_types_late"] == ["basketball_game"]
    # Even once they match again, a late type stays distrusted for days.
    good = _milestones([])
    starts, counts = bot.prefetch_starts(
        listings, NOW + timedelta(hours=1), tmp_path, good
    )
    assert "basketball_game" not in counts["milestone_types_trusted"] and starts == {}


def test_only_validated_types_count_and_esports_match_never(tmp_path):
    listings = {
        "KXDOTA2GAME": [market()],
        "KXR6GAME": [_listing("KXR6GAME-26OCT221900ABCD")],
        "KXTESTGAME": [_listing("KXTESTGAME-26OCT22E0")],
    }
    for kind in ("esports_game", "esports_match", "football_game"):
        folder = tmp_path / kind
        folder.mkdir()
        # Matching ticker times on every check does not make a type trusted.
        for minutes in (0, 60, 120):
            starts, counts = bot.prefetch_starts(
                listings,
                NOW + timedelta(minutes=minutes),
                folder,
                _milestones([], kind=kind),
            )
            assert kind not in counts["milestone_types_trusted"] and starts == {}


def test_trust_is_per_milestone_type(tmp_path):
    listings = {
        "KXDOTA2GAME": [market()],
        "KXR6GAME": [_listing("KXR6GAME-26OCT221900ABCD")],
        "KXNCAAFSPREAD": [_listing("KXNCAAFSPREAD-26OCT22LIBKENN")],
        "KXTESTGAME": [_listing("KXTESTGAME-26OCT22E0")],
    }

    def fetch(event):
        timed = bot.ticker_start(event)
        kind = "football_game" if event.startswith("KXNCAAF") else "basketball_game"
        start = timed or NOW + timedelta(hours=2)
        return {
            "milestones": [
                {
                    "start_date": start.isoformat(),
                    "type": kind,
                    "primary_event_tickers": [event],
                }
            ]
        }

    starts, counts = bot.prefetch_starts(listings, NOW, tmp_path, fetch)
    # Basketball milestones are validated; football ones never were.
    assert starts["KXTESTGAME-26OCT22E0"] == NOW + timedelta(hours=2)
    assert "KXNCAAFSPREAD-26OCT22LIBKENN" not in starts


def test_an_earlier_milestone_moves_a_ticker_start_earlier(tmp_path):
    listings = {"KXDOTA2GAME": [market()]}
    early = _milestones([], shift=timedelta(minutes=-40))
    starts, counts = bot.prefetch_starts(listings, NOW, tmp_path, early)
    event = TICKER.rsplit("-", 1)[0]
    assert starts[event] == START - timedelta(minutes=40)
    assert bot.event_start(event, starts) == START - timedelta(minutes=40)
    assert counts["earlier_than_ticker"] == 1


def test_clock_change_times_take_the_earlier_instant():
    # 02:30 does not exist in New York on 14 March 2027.
    assert bot.ticker_start("KXR6GAME-27MAR140230ABCD") == datetime(
        2027, 3, 14, 6, 30, tzinfo=UTC
    )
    # 01:30 happens twice on 7 November 2027: the first one.
    assert bot.ticker_start("KXR6GAME-27NOV070130ABCD") == datetime(
        2027, 11, 7, 5, 30, tzinfo=UTC
    )


def test_checks_pick_events_still_to_start_and_resting_ones_first():
    timed = {
        "KXAHLGAME-26OCT221200AAABBB": NOW,  # 16:00 UTC: already started
        "KXAHLGAME-26OCT221700CCCDDD": NOW,  # 21:00 UTC: the next to start
        "KXAHLGAME-26OCT221900EEEFFF": NOW,
        "KXR6GAME-26OCT221900ABCD": NOW,
    }
    first, picks = bot._check_order(timed, NOW, active={"KXAHLGAME-26OCT221900EEEFFF"})
    assert first == [("KXAHLGAME-26OCT221900EEEFFF", NOW)]
    assert {e for e, _ in picks} == {
        "KXAHLGAME-26OCT221700CCCDDD",
        "KXR6GAME-26OCT221900ABCD",
    }


def test_a_damaged_cache_is_ignored_and_rewritten(tmp_path):
    listings = {
        "KXDOTA2GAME": [market()],
        "KXR6GAME": [_listing("KXR6GAME-26OCT221900ABCD")],
        "KXTESTGAME": [_listing("KXTESTGAME-26OCT22E0")],
    }
    event = TICKER.rsplit("-", 1)[0]
    bad = {
        "types": {"basketball_game": ["not", "a", "dict"], "": {"matched": {"x": "y"}}},
        event: {
            "milestones": [["not a date", "basketball_game"]],
            "checked": NOW.isoformat(),
        },
        "KXR6GAME-26OCT221900ABCD": {
            "milestones": [],
            "checked": (NOW + timedelta(days=30)).isoformat(),  # from the future
        },
        "KXTESTGAME-26OCT22E0": "garbage",
    }
    path = tmp_path / "event_starts.json"
    path.write_text(json.dumps(bad))
    calls = []
    starts, counts = bot.prefetch_starts(listings, NOW, tmp_path, _milestones(calls))
    # Every damaged entry was read again; trust records come from fresh reads.
    assert sorted(calls) == sorted(
        [event, "KXR6GAME-26OCT221900ABCD", "KXTESTGAME-26OCT22E0"]
    )
    assert "basketball_game" in counts["milestone_types_trusted"]
    assert "KXTESTGAME-26OCT22E0" in starts
    saved = json.loads(path.read_text())
    assert set(saved["types"]) == {"basketball_game"}


def test_milestones_without_a_type_are_never_trusted(tmp_path):
    listings = {
        "KXDOTA2GAME": [market()],
        "KXR6GAME": [_listing("KXR6GAME-26OCT221900ABCD")],
        "KXTESTGAME": [_listing("KXTESTGAME-26OCT22E0")],
    }
    starts, counts = bot.prefetch_starts(
        listings, NOW, tmp_path, _milestones([], kind="")
    )
    assert starts == {}


def test_series_offset_start_when_no_ticker_time_or_trusted_milestone(tmp_path):
    expires = NOW + timedelta(hours=10)
    offset = expires - timedelta(hours=3, minutes=30)  # KXNCAAWBGAME: 3 h + 30 min
    listings = {
        # CS2 without a ticker time and only an (untrusted) esports_match
        # milestone: start = expiry - 4 h - 30 min.
        "KXCS2GAME": [_listing("KXCS2GAME-26OCT22E0", hours=10.0)],
        # NCAA women's basketball with a trusted milestone: the earlier of
        # the milestone and the offset counts.
        "KXNCAAWBGAME": [
            _listing("KXNCAAWBGAME-26OCT22AB", hours=10.0),  # milestone later
            _listing("KXNCAAWBGAME-26OCT22CD", hours=10.0),  # milestone earlier
        ],
    }
    milestone = {
        "KXCS2GAME-26OCT22E0": NOW + timedelta(hours=7),
        "KXNCAAWBGAME-26OCT22AB": offset + timedelta(minutes=30),
        "KXNCAAWBGAME-26OCT22CD": offset - timedelta(minutes=30),
    }

    def fetch(event):
        kind = "esports_match" if event.startswith("KXCS2") else "basketball_game"
        return {
            "milestones": [
                {
                    "start_date": milestone[event].isoformat(),
                    "type": kind,
                    "primary_event_tickers": [event],
                }
            ]
        }

    starts, counts = bot.prefetch_starts(listings, NOW, tmp_path, fetch)
    assert starts["KXCS2GAME-26OCT22E0"] == expires - timedelta(hours=4, minutes=30)
    assert starts["KXNCAAWBGAME-26OCT22AB"] == offset  # a late milestone loses
    assert starts["KXNCAAWBGAME-26OCT22CD"] == offset - timedelta(minutes=30)
    assert counts["with_series_offset_start"] == 2
    assert counts["with_milestone_start"] == 1


def test_recent_events_are_those_with_orders_that_may_rest(world):
    run(world)
    event = TICKER.rsplit("-", 1)[0]
    assert bot.recent_events(world["dir"], NOW + timedelta(minutes=30)) == {event}
    assert bot.recent_events(world["dir"], NOW + timedelta(minutes=70)) == set()


# ------------------------------------------- standing and markouts (measurement)


def _listing_at(bid, ask):
    return {"KXDOTA2GAME": [{**market(), "yes_bid_dollars": f"{bid:.2f}",
                             "yes_ask_dollars": f"{ask:.2f}"}]}  # fmt: skip


def _measures(state):
    return bot.load_measurements(state / bot.MEASURE_FILE)


def _summary(state):
    return bot.summarize_measurements(
        bot.load_events(state / "journal.jsonl"),
        bot.iter_measurements(state / bot.MEASURE_FILE),
    )


def test_markouts_of_a_one_sided_fill(world):
    run(world)  # YES 5 @ 41c and NO 5 @ 49c in a 40-52c market (spread 12)
    order = fill_placed(world, 0, 5)  # the YES fills at NOW + 5 min
    world["exchange"].fills_[-1]["fee_cost"] = "0.0500"  # 1c a contract
    run(world, NOW + timedelta(minutes=10))  # copies the fill into the journal
    assert order.side == "yes"
    state = world["dir"]
    listing = _listing_at(0.44, 0.52)  # YES midpoint now 48c
    assert bot.record_markouts(state, NOW + timedelta(minutes=14), listing) == 0
    assert bot.record_markouts(state, NOW + timedelta(minutes=20), listing) == 1
    m = next(e for e in _measures(state) if e["event"] == "markout")
    # Posted at 41 when the YES midpoint was 46: +2 since; paid 41 and 1c fee.
    assert m["adverse_move_cents"] == 2 and m["realized_spread_cents"] == 6
    assert m["exit_move_cents"] == 3 and not m["exit_is_own_quote"]
    assert m["contracts"] == 5 and m["minutes_before_start"] > 0
    # Each horizon once; a late pass records the miss instead of a price.
    assert bot.record_markouts(state, NOW + timedelta(minutes=20), listing) == 0
    assert bot.record_markouts(state, NOW + timedelta(minutes=40), {}) == 1
    assert bot.record_markouts(state, NOW + timedelta(minutes=80), listing) == 1
    issues = {
        e["horizon_minutes"]: e["issue"]
        for e in _measures(state)
        if e["event"] == "markout"
    }
    assert issues == {
        10: None,
        30: "quote_unavailable",
        60: "missed_observation_window",
    }
    ten = _summary(state)["markouts"]["10m"]
    assert ten["one_sided_fills"] == 1 and ten["one_sided_adverse_move_cents"] == 2.0
    assert ten["one_sided_realized_spread_cents"] == 6.0 and ten["all_fills"] == 1
    assert _summary(state)["markouts"]["30m"]["not_used"] == {"quote_unavailable": 1}


def test_pairing_looks_only_backwards(world):
    run(world)
    fill_placed(world, 0, 5)  # YES at NOW + 5
    fill_placed(world, 1, 30, count=2)  # 2 of the NO at NOW + 30: the rest rests
    run(world, NOW + timedelta(minutes=35))
    state = world["dir"]
    bot.record_markouts(state, NOW + timedelta(minutes=40), _listing_at(0.44, 0.51))
    marks = _summary(state)["markouts"]
    # The YES filled first: one-sided (its 30-minute reading). The NO came
    # after it: paired (its 10-minute reading).
    assert marks["30m"]["one_sided_fills"] == 1 and marks["30m"]["all_fills"] == 1
    assert marks["10m"]["one_sided_fills"] == 0 and marks["10m"]["all_fills"] == 1
    # The NO's best bid was our own resting 49c: its exit price says nothing.
    no = next(e for e in _measures(state) if e.get("side") == "no")
    assert no["exit_is_own_quote"] and no["exit_move_cents"] is None


def test_readings_after_the_start_are_not_used():
    journal = [
        {"event": "intent", "client_order_id": "a", "strategy_version": P.STRATEGY_VERSION,
         "ticker": TICKER, "side": "yes", "price_cents": 41, "count": 5},
        {"event": "accepted", "client_order_id": "a", "order_id": "1"},
        {"event": "fill", "fill_id": "f", "order_id": "1", "count_fp": "5.00",
         "utc": NOW.isoformat()},
    ]  # fmt: skip
    marks = [
        {"event": "markout", "client_order_id": "a", "fill_id": "f", "horizon_minutes": 60,
         "minutes_before_start": -5, "adverse_move_cents": -9, "realized_spread_cents": -3,
         "contracts": 5, "issue": None},
    ]  # fmt: skip
    sixty = bot.summarize_measurements(journal, marks)["markouts"]["60m"]
    assert sixty["one_sided_fills"] == 0 and sixty["all_fills"] == 0
    assert sixty["not_used"] == {"observed_after_start": 1}


def test_standing_is_checked_before_requotes(world):
    run(world)  # YES 41 and NO 49 rest
    state = world["dir"]
    # Someone bids 42 for YES (ahead of us) and joins our NO at 49.
    world["quotes"][TICKER] = {**world["quotes"][TICKER], "yes_bid_dollars": "0.42",
                               "yes_ask_dollars": "0.51"}  # fmt: skip
    report, _ = run(world, NOW + timedelta(minutes=10))
    assert report["standing_orders_checked"] == 2
    assert report["standing_outbid"] == 1 and report["standing_joined"] == 1
    (event,) = [e for e in _measures(state) if e["event"] == "standing"]
    assert event["outbid"] == 1 and event["joined"] == 1
    summary = _summary(state)
    assert summary["standing_checks"] == 2 and summary["outbid_share"] == 0.5


def test_a_torn_measurement_file_does_not_stop_measuring(world):
    run(world)
    fill_placed(world, 0, 5)
    run(world, NOW + timedelta(minutes=10))
    state = world["dir"]
    (state / bot.MEASURE_FILE).write_text(
        '{"event": "standing", "orders_checked": 2}\n{"eve'
    )
    assert (
        bot.record_markouts(state, NOW + timedelta(minutes=20), _listing_at(0.44, 0.52))
        == 1
    )
    assert [e["event"] for e in _measures(state)] == ["standing", "markout"]
    summary = bot.write_measure_summary(state)
    assert summary["markouts"]["10m"]["one_sided_fills"] == 1
    assert json.loads((state / bot.MEASURE_SUMMARY).read_text()) == summary


def test_summary_reports_clustered_t_and_gaps():
    v2 = P.STRATEGY_VERSION
    journal, marks = [], []
    for i, move in enumerate((3.0, 5.0, -1.0, 4.0)):
        cid, oid, fid = f"c{i}", f"o{i}", f"f{i}"
        journal += [
            {"event": "intent", "client_order_id": cid, "strategy_version": v2,
             "ticker": f"KXCS2GAME-E{i}-A", "event_ticker": f"KXCS2GAME-E{i}",
             "side": "yes", "price_cents": 41, "count": 5},
            {"event": "accepted", "client_order_id": cid, "order_id": oid},
            {"event": "fill", "fill_id": fid, "order_id": oid, "count_fp": "5.00",
             "utc": NOW.isoformat(), **({} if i == 3 else {"fee_cost": "0.00"})},
        ]  # fmt: skip
        if i < 3:  # the last fill was never measured
            marks.append(
                {
                    "event": "markout",
                    "client_order_id": cid,
                    "fill_id": fid,
                    "horizon_minutes": 30,
                    "minutes_before_start": 90,
                    "contracts": 5,
                    "adverse_move_cents": move - 4,
                    "realized_spread_cents": move,
                    "issue": None,
                }  # fmt: skip
            )
    s = bot.summarize_measurements(journal, marks, NOW + timedelta(hours=2))
    thirty = s["markouts"]["30m"]
    assert thirty["one_sided_fills"] == 3
    assert thirty["one_sided_realized_spread_cents"] == round(7 / 3, 2)
    assert thirty["one_sided_realized_spread_t"] is not None
    assert s["fills"] == 4 and s["fills_never_measured"] == 1
    assert s["fills_without_fee_record"] == 1
    # Too recent to have been measured: not counted as never measured.
    assert bot.summarize_measurements(journal, marks, NOW)["fills_never_measured"] == 0


def test_v3_quotes_two_contracts_a_side_and_caps_net_at_two(world):
    report, _ = run(world)
    assert {(o.side, o.count) for o in world["exchange"].placed} == {
        ("yes", 2),
        ("no", 2),
    }
    # Two YES contracts held: no more YES room; NO may still offset them.
    quotes = bot.desired_quotes(
        [{"ticker": TICKER, "yes_price": 41, "no_price": 49}], {TICKER: 2.0}
    )
    assert quotes == {(TICKER, "no"): (49, 2)}


# ------------------------------------------- v3: changes after review


def _no_milestones(event):
    return {"milestones": []}


def _test_series_milestones(event):
    """Two hours from NOW for KXTESTGAME events, none for any other."""
    return _milestones([])(event) if event.startswith("KXTESTGAME") else {}


def _untimed(event, hours):
    return {"event_ticker": event, "expected_expiration_time": (NOW + timedelta(hours=hours)).isoformat()}  # fmt: skip


def test_offset_start_when_reads_fail_run_out_or_every_type_is_revoked(
    tmp_path, monkeypatch
):
    cs2, only_milestone = "KXCS2GAME-26OCT22E0", "KXTESTGAME-26OCT22E0"
    offset = NOW + timedelta(hours=10) - timedelta(hours=4, minutes=30)
    listings = {
        "KXCS2GAME": [_untimed(cs2, 10.0)],
        "KXTESTGAME": [_untimed(only_milestone, 10.0)],
    }

    def broken(event):
        raise OSError("timed out")

    # Every read fails: the offset still dates CS2; the other has no start.
    starts, counts = bot.prefetch_starts(listings, NOW, tmp_path / "a", broken)
    assert starts == {cs2: offset} and counts["milestone_read_failures"] == 2
    assert counts["without_start"] == 1
    # No reads left this pass: the same.
    monkeypatch.setattr(P, "MAX_START_LOOKUPS_PER_PASS", 0)
    calls = []
    starts, counts = bot.prefetch_starts(
        listings, NOW, tmp_path / "b", _milestones(calls)
    )
    assert starts == {cs2: offset} and calls == []
    monkeypatch.setattr(P, "MAX_START_LOOKUPS_PER_PASS", 60)
    # Every trusted type revoked (late on a ticker-timed event): no milestone
    # is read for untimed events, and the offset still dates CS2.
    monkeypatch.setattr(P, "TRUSTED_MILESTONE_TYPES", frozenset({"basketball_game"}))
    late = _milestones(calls, shift=timedelta(minutes=5))
    timed = {**listings, "KXDOTA2GAME": [market()]}
    starts, counts = bot.prefetch_starts(timed, NOW, tmp_path / "c", late)
    assert counts["milestone_types_trusted"] == []
    assert calls == [TICKER.rsplit("-", 1)[0]]  # only the ticker-timed check
    assert starts == {cs2: offset}


def test_revoking_one_type_leaves_the_others_trusted(tmp_path):
    listings = {
        "KXDOTA2GAME": [market()],  # its check: a basketball milestone, late
        "KXTESTGAME": [
            _untimed("KXTESTGAME-26OCT22BASE", 5.0),
            _untimed("KXTESTGAME-26OCT22HOOP", 5.0),
        ],
    }

    def fetch(event):
        timed = bot.ticker_start(event)
        kind = "baseball_game" if event.endswith("BASE") else "basketball_game"
        start = timed + timedelta(minutes=5) if timed else NOW + timedelta(hours=2)
        return {"milestones": [{"start_date": start.isoformat(), "type": kind,
                                "primary_event_tickers": [event]}]}  # fmt: skip

    starts, counts = bot.prefetch_starts(listings, NOW, tmp_path, fetch)
    assert counts["milestone_types_late"] == ["basketball_game"]
    assert "baseball_game" in counts["milestone_types_trusted"]
    assert starts == {"KXTESTGAME-26OCT22BASE": NOW + timedelta(hours=2)}


def test_an_event_is_dated_from_its_earliest_market_expiry(tmp_path):
    event = "KXCS2GAME-26OCT22E0"
    listings = {"KXCS2GAME": [_untimed(event, 12.0), _untimed(event, 9.0)]}
    starts, _ = bot.prefetch_starts(listings, NOW, tmp_path, _no_milestones)
    assert starts == {event: NOW + timedelta(hours=9 - 4.5)}


def test_ticker_timed_events_never_use_the_series_offset(tmp_path):
    # CS2 has an offset (4 h): it would date this event 21:30 UTC, but its
    # ticker says 18:00 New York (22:00 UTC), and the ticker is the start.
    event = "KXCS2GAME-26OCT221800ABCD"
    listings = {"KXCS2GAME": [_untimed(event, 8.0)]}
    starts, counts = bot.prefetch_starts(listings, NOW, tmp_path, _milestones([]))
    assert starts == {} and counts["with_series_offset_start"] == 0
    assert bot.event_start(event, starts) == START


def test_a_start_moves_earlier_but_never_later(tmp_path):
    cs2, test = "KXCS2GAME-26OCT22E0", "KXTESTGAME-26OCT22E0"
    first = {"KXCS2GAME": [_untimed(cs2, 10.0)], "KXTESTGAME": [_untimed(test, 10.0)]}
    starts, counts = bot.prefetch_starts(first, NOW, tmp_path, _test_series_milestones)
    assert starts == {
        cs2: NOW + timedelta(hours=5, minutes=30),
        test: NOW + timedelta(hours=2),  # _milestones: two hours from NOW
    }
    # An hour later Kalshi has moved both expirations two hours later and the
    # milestone an hour later: both starts stay where they were.
    later = {"KXCS2GAME": [_untimed(cs2, 12.0)], "KXTESTGAME": [_untimed(test, 12.0)]}

    def moved(event):
        if not event.startswith("KXTESTGAME"):
            return {}
        return {"milestones": [{"start_date": (NOW + timedelta(hours=3)).isoformat(),
                                "type": "basketball_game",
                                "primary_event_tickers": [event]}]}  # fmt: skip

    hour = NOW + timedelta(hours=1)
    starts, counts = bot.prefetch_starts(later, hour, tmp_path, moved)
    assert starts == {
        cs2: NOW + timedelta(hours=5, minutes=30),
        test: NOW + timedelta(hours=2),
    }
    assert counts["kept_earlier_start"] == 2

    # The memory never dates an event on its own: with the read failing and
    # no offset, the milestone-only event has no start this pass.
    def broken(event):
        raise OSError("timed out")

    starts, _ = bot.prefetch_starts(later, NOW + timedelta(hours=2), tmp_path, broken)
    assert starts == {cs2: NOW + timedelta(hours=5, minutes=30)}
    # A damaged memory is ignored; starts more than two days past are dropped.
    path = tmp_path / "event_starts.json"
    saved = json.loads(path.read_text())
    saved["earliest"] = {cs2: "garbage", "": "2026-10-22T00:00:00+00:00",
                         "KXOLD-1": "2026-10-01T00:00:00+00:00"}  # fmt: skip
    path.write_text(json.dumps(saved))
    starts, _ = bot.prefetch_starts(later, hour, tmp_path, _no_milestones)
    assert starts[cs2] == NOW + timedelta(hours=7, minutes=30)
    assert set(json.loads(path.read_text())["earliest"]) == {cs2, test}


def test_reads_go_first_to_events_without_an_offset():
    candidates = {
        "KXCS2GAME-26OCT22E0": NOW,  # has an offset
        "KXTESTGAME-26OCT22E0": NOW,
        "KXTESTGAME-26OCT22E1": NOW,
        "KXTESTGAME-26OCT22E2": NOW,
    }
    order = bot._read_order(candidates, NOW, active={"KXTESTGAME-26OCT22E2"})
    assert order[0] == "KXTESTGAME-26OCT22E2"  # may have quotes resting
    assert set(order[1:3]) == {"KXTESTGAME-26OCT22E0", "KXTESTGAME-26OCT22E1"}
    assert order[3] == "KXCS2GAME-26OCT22E0"
    # The rest rotate from pass to pass, so a budget cut starves no event.
    later = bot._read_order(candidates, NOW + timedelta(minutes=10))
    assert later[:3] != bot._read_order(candidates, NOW)[:3]


def test_financial_daily_series_are_never_quoted(world, tmp_path):
    reasons = bot.Counter()
    brent = market("KXBRENTD-26OCT2317-T80.99")
    assert bot.eligible_markets([brent], "KXBRENTD", NOW, reasons=reasons) == []
    assert reasons["no_start_series"] == 1
    calls = []
    starts, counts = bot.prefetch_starts(
        {"KXBRENTD": [brent]}, NOW, tmp_path, _milestones(calls)
    )
    assert starts == {} and calls == [] and counts["events_without_ticker_time"] == 0
    # They are not even listed.
    seen = []
    public = {
        **world["public"],
        "fetch_markets": lambda s, status="open": seen.append(s) or [],
    }
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(P, "SERIES", ("KXDOTA2GAME", "KXBRENTD", "KXINXDUD", "KXTNOTED"))
        bot.prefetch(public)
    assert seen == ["KXDOTA2GAME"]


def test_an_offset_dated_quote_is_cancelled_20_minutes_before_the_start(world):
    untimed = "KXCS2GAME-26OCT22ABCD-A"
    world["quotes"].clear()
    world["quotes"][untimed] = market(untimed, hours=8.0)
    start = NOW + timedelta(hours=8) - timedelta(hours=4, minutes=30)
    listings = {"KXCS2GAME": [world["quotes"][untimed]]}
    starts, _ = bot.prefetch_starts(listings, NOW, world["dir"], _no_milestones)
    world["public"]["event_starts"] = starts
    run(world)
    intents = [e for e in journal(world) if e["event"] == "intent"]
    assert {i["event_start_utc"] for i in intents} == {start.isoformat()}
    assert len(world["exchange"].resting) == 2
    # Ten minutes before the estimate: cancelled, even with no start known
    # this pass (the start recorded with the order counts).
    world["public"]["event_starts"] = {}
    report, _ = run(world, start - timedelta(minutes=10))
    assert report["canceled_event_start"] == 2 and world["exchange"].resting == []


def test_v3_replaces_resting_five_contract_v2_orders(world, monkeypatch):
    monkeypatch.setattr(P, "STRATEGY_VERSION", "spread-maker-v2-pregame")
    run(world)  # v2: 5 contracts a side
    assert {o.count for o in world["exchange"].placed} == {5}
    monkeypatch.setattr(P, "STRATEGY_VERSION", "spread-maker-v3-24h-starts")
    monkeypatch.setattr(P, "CONTRACTS", 2)
    monkeypatch.setattr(P, "MAX_NET_PER_MARKET", 2)
    report, _ = run(world, NOW + timedelta(minutes=10))
    # Five resting contracts no longer fit the 2-contract cap: both go, and
    # 2-contract quotes replace them at the same prices.
    assert report["canceled"] == 2
    assert [(o.side, o.count) for o in world["exchange"].placed[2:]] == [
        ("yes", 2),
        ("no", 2),
    ]
    assert sorted(o["remaining_count_fp"] for o in world["exchange"].resting) == [
        "2.00",
        "2.00",
    ]


def test_shadow_reads_are_capped_and_stop_at_the_deadline():
    quotes = []
    for i in range(3):
        ticker = f"KXCS2GAME-E{i}-A"
        quotes.append({"event": "shadow_quote", "id": f"q{i}", "ticker": ticker,
                       "side": "yes", "price_cents": 41,
                       "posted_utc": NOW.isoformat(),
                       "expires_utc": (NOW + timedelta(hours=1)).isoformat(),
                       "market_expiration_utc": (NOW + timedelta(hours=3)).isoformat()})  # fmt: skip
    calls = []

    def trades(ticker, a, b):
        calls.append(ticker)
        return [{"created_time": (NOW + timedelta(minutes=5)).isoformat(),
                 "yes_price": 0.40, "count": 2, "taker_outcome_side": "no"}]  # fmt: skip

    later = NOW + timedelta(hours=2)
    fills = bot.shadow_score(quotes, later, trades, limit=2, order=lambda k: None)
    assert calls == ["KXCS2GAME-E0-A", "KXCS2GAME-E1-A"] and len(fills) == 2
    gone = time.monotonic() - 1
    assert bot.shadow_score(quotes, later, trades, deadline=gone) == []
    # Results are read only after the expected expiration, also capped.
    results = []

    def market_of(ticker):
        results.append(ticker)
        return {"result": "no"}

    assert bot.shadow_settle(quotes + fills, market_of, later) == []
    assert results == []
    after = NOW + timedelta(hours=4)
    got = bot.shadow_settle(
        quotes + fills, market_of, after, limit=1, order=lambda k: None
    )
    assert [g["ticker"] for g in got] == ["KXCS2GAME-E0-A"]


def test_standing_records_carry_their_rule_version(world):
    run(world)
    world["quotes"][TICKER] = {**world["quotes"][TICKER], "yes_bid_dollars": "0.42",
                               "yes_ask_dollars": "0.51"}  # fmt: skip
    run(world, NOW + timedelta(minutes=10))
    state = world["dir"]
    (event,) = [e for e in _measures(state) if e["event"] == "standing"]
    assert event["strategy_version"] == P.STRATEGY_VERSION
    # A record from an earlier version (none carried one) is not counted.
    bot.write_measurement(
        state / bot.MEASURE_FILE,
        {"event": "standing", "orders_checked": 8, "outbid": 8},
    )
    assert _summary(state)["standing_checks"] == 2


def test_live_measurements_run_before_the_shadow_ledger(world, monkeypatch, tmp_path):
    import contextlib

    import live.production_lock as production_lock

    state = tmp_path / "state"
    monkeypatch.setattr(P, "STATE", state)
    world["public"]["window_trades"] = lambda ticker, a, b: []
    monkeypatch.setattr(bot, "public_api", lambda: world["public"])
    monkeypatch.setattr(bot, "armed", lambda env: True)
    monkeypatch.setattr(bot, "TradingClient", lambda **kwargs: object())
    monkeypatch.setattr(production_lock, "account_lock", contextlib.nullcontext)
    order = []

    def step(name, value=0):
        return lambda *a, **k: order.append(name) or value

    monkeypatch.setattr(bot, "pass_live", step("live", ({"decision": "quoted"}, [])))
    monkeypatch.setattr(bot, "record_markouts", step("markouts"))
    monkeypatch.setattr(bot, "write_measure_summary", step("summary"))
    monkeypatch.setattr(bot, "score_live_windows", step("windows"))

    def slow_shadow(*args, **kwargs):
        order.append("shadow")
        assert kwargs["deadline"] == bot.PROCESS_START + bot.SHADOW_DEADLINE_SECONDS
        raise RuntimeError("endpoint timed out")

    monkeypatch.setattr(bot, "run_shadow", slow_shadow)
    monkeypatch.setattr("sys.argv", ["prod_spread_auto", "--auto"])
    bot.main()
    assert order == ["live", "markouts", "summary", "windows", "shadow"]
    # A shadow failure after a live pass still leaves that pass's report.
    report = json.loads((state / "last_scan.json").read_text())
    assert report["live"] == {"decision": "quoted"}
    assert report["shadow_error"] == "RuntimeError"
