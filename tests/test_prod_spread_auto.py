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
    fill_placed(world, 1, 6)  # NO 49c: five locked pairs, 5 x 10c
    run(world, NOW + timedelta(minutes=10))
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
    # $5, $15). Change these only through a new, recorded amendment.
    assert (P.CONTRACTS, P.MAX_NET_PER_MARKET) == (5, 5)
    assert (P.MAX_ACTIVE_COST, P.DAILY_LOSS_STOP, P.CUMULATIVE_LOSS_STOP) == (
        60,
        10,
        40,
    )
    assert (P.MAX_ORDERS_PER_PASS, P.MAX_SUBMISSIONS_PER_DAY) == (20, 300)
    assert P.MIN_SPREAD_CENTS == 8 and P.WINDOW_HOURS == (4.0, 7.0)
    assert shared.ACCOUNT_LOSS_STOPS == {"daily": 20.0, "cumulative": 60.0}


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
