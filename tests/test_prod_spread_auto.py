"""Offline tests for the spread maker (live/prod_spread_auto.py). No network."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from kalshi.trading import TradingError
from live import prod_spread_auto as bot
from live import shared_account_risk as shared
from live import spread_policy as P

NOW = datetime(2026, 10, 22, 18, 0, tzinfo=UTC)
TICKER = "KXDOTA2GAME-26OCT22AB-A"


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
            market("KXDOTA2GAME-X-B", hours=3.0),
            market("KXDOTA2GAME-X-C", hours=8.0),
            market("KXDOTA2GAME-X-D", ask=0.45),
            market("KXDOTA2GAME-X-E", status="closed"),
            market("KXDOTA2GAME-X-F"),
            market("KXNBAPTS-26OCT22AB-P10"),
        ],
        "KXDOTA2GAME",
        NOW,
        other_tickers={"KXDOTA2GAME-X-F"},
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
    assert set(bot.desired_quotes(rows, {})) == {(TICKER, "yes"), (TICKER, "no")}
    assert set(bot.desired_quotes(rows, {TICKER: 1.0})) == {(TICKER, "no")}
    assert set(bot.desired_quotes(rows, {TICKER: -1.0})) == {(TICKER, "yes")}
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
            }
        )
        return {"order_id": oid}

    def cancel(self, order_id, ticker=None):
        if self.fail_cancel:
            error, self.fail_cancel = self.fail_cancel, None
            self.resting = [o for o in self.resting if o["order_id"] != order_id]
            raise error
        self.canceled.append(order_id)
        self.history["canceled"] += [
            o for o in self.resting if o["order_id"] == order_id
        ]
        self.resting = [o for o in self.resting if o["order_id"] != order_id]


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
                level = [f"{o['price_cents'] / 100:.2f}", "1.00"]
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
        ("yes", 41, 1, True),
        ("no", 49, 1, True),
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
    ex = world["exchange"]
    yes = [
        o for o in ex.resting if o["client_order_id"] == ex.placed[0].client_order_id
    ]
    ex.resting = [o for o in ex.resting if o not in yes]  # the YES quote filled
    ex.positions_ = [{"market_ticker": TICKER, "position_fp": "1"}]
    report, _ = run(world, NOW + timedelta(minutes=10))
    assert report["placed"] == 0  # NO quote kept, YES not re-posted


def test_active_cap_blocks_new_quotes(world, monkeypatch):
    monkeypatch.setattr(P, "MAX_ACTIVE_COST", 0.45)
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


def test_unreadable_book_pulls_our_quotes(world):
    run(world)

    def broken(ticker):
        raise OSError("timed out")

    world["public"]["fetch_orderbook"] = broken
    report, markets = run(world, NOW + timedelta(minutes=10))
    assert markets == [] and report["canceled"] == 2 and report["placed"] == 0


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


def fill_of(order, minutes, fid=None):
    """An exchange fill of one of our placed orders, as Kalshi lists it."""
    yes = order.price_cents if order.side == "yes" else 100 - order.price_cents
    return {
        "fill_id": fid or f"fill-{order.client_order_id}",
        "order_id": None,  # set by the caller from the fake exchange
        "ticker": order.ticker,
        "created_time": (NOW + timedelta(minutes=minutes)).isoformat(),
        "count_fp": "1.00",
        "yes_price_dollars": f"{yes / 100:.4f}",
        "no_price_dollars": f"{(100 - yes) / 100:.4f}",
        "outcome_side": order.side,
        "book_side": "bid" if order.side == "yes" else "ask",
        "fee_cost": "0.00",
    }


def fill_placed(world, index, minutes):
    """Fill the index-th order we placed: it leaves the book."""
    ex = world["exchange"]
    order = ex.placed[index]
    oid = f"oid-{index + 1}"
    ex.resting = [o for o in ex.resting if o["order_id"] != oid]
    ex.fills_.append({**fill_of(order, minutes), "order_id": oid})
    return order


def test_own_loss_stop_cancels_everything(world, monkeypatch):
    monkeypatch.setattr(P, "DAILY_LOSS_STOP", 0.40)
    run(world)
    ex = world["exchange"]
    fill_placed(world, 0, 5)  # the YES quote at 41c fills
    ex.settlements_ = [  # and the market settles NO: -41c
        {
            "market_ticker": TICKER,
            "settled_time": (NOW + timedelta(minutes=8)).isoformat(),
            "market_result": "no",
            "revenue_dollars": "0.00",
            "yes_total_cost_dollars": "0.41",
            "no_total_cost_dollars": "0.00",
            "fee_cost": "0.00",
        }
    ]
    report, markets = run(world, NOW + timedelta(minutes=10))
    assert report["decision"] == "spread_loss_stop" and markets is None
    assert report["daily"] == pytest.approx(-0.41)
    assert ex.resting == [] and len(ex.canceled) == 1  # the NO quote


def test_a_losing_pair_counts_at_once_without_any_settlement(world, monkeypatch):
    # The reviewer's case: YES fills at 41c, the market falls, our NO quote
    # is repriced to 74c and fills. Kalshi nets the pair to zero: no
    # settlement record will ever show the 15c loss, but the stop must.
    monkeypatch.setattr(P, "DAILY_LOSS_STOP", 0.10)
    run(world)
    ex = world["exchange"]
    fill_placed(world, 0, 5)
    ex.positions_ = [{"market_ticker": TICKER, "position_fp": "1"}]
    world["quotes"][TICKER] = market(bid=0.15, ask=0.27)  # NO bid now 74c
    run(world, NOW + timedelta(minutes=10))
    no_74 = len(ex.placed) - 1
    assert (ex.placed[no_74].side, ex.placed[no_74].price_cents) == ("no", 74)
    fill_placed(world, no_74, 12)
    ex.positions_ = []  # netted to zero
    report, markets = run(world, NOW + timedelta(minutes=20))
    assert report["decision"] == "spread_loss_stop" and report[
        "daily"
    ] == pytest.approx(-0.15)
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
    world["public"]["fetch_market"] = lambda ticker: {"result": "no"}
    first = bot.run_shadow(folder, NOW, world["public"])
    assert first == {"quotes": 2, "scored": 0}
    later = bot.run_shadow(folder, NOW + timedelta(minutes=61), world["public"])
    assert later["filled"] == 1 and later["settled_fills"] == 1
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
    bot.main()
    report = json.loads((state / "last_scan.json").read_text())
    assert report["mode"] == "shadow" and "live" not in report
    assert report["shadow"]["quotes"] == 2
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


def test_status_reports_live_and_shadow_apart(world, capsys):
    run(world)
    fill_placed(world, 0, 5)  # YES 41c
    fill_placed(world, 1, 6)  # NO 49c: a locked pair, +10c
    run(world, NOW + timedelta(minutes=10))
    bot.status(world["dir"])
    out = capsys.readouterr().out
    assert "LIVE realized P&L (from fills): today $+0.10" in out
    assert "SHADOW (simulated" in out
