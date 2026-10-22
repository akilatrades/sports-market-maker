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
    fills = [
        {
            "order_id": "o1",
            "ticker": TICKER,
            "side": "yes",
            "yes_price_dollars": "0.41",
            "count_fp": "1",
        },
        {
            "order_id": "foreign",
            "ticker": TICKER,
            "side": "yes",
            "yes_price_dollars": "0.90",
            "count_fp": "1",
        },
    ]
    assert bot.held_cost({TICKER: 1.0}, fills, {"o1"}) == pytest.approx(0.41)
    assert bot.held_cost({"KXOTHER": -2.0}, fills, {"o1"}) == pytest.approx(2.0)


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

    def orders(self, status="resting", ticker=None):
        return [o for o in self.resting if ticker is None or o["ticker"] == ticker]

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
    with pytest.raises(TradingError, match="no order id"):
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
    run(world, NOW + timedelta(minutes=10))
    assert any(e.get("event") == "cancel_moot" for e in journal(world))


def test_own_loss_stop_cancels_everything(world):
    run(world)
    ex = world["exchange"]
    ex.settlements_ = [
        {
            "market_ticker": TICKER,
            "settled_time": NOW.isoformat(),
            "revenue_dollars": "0.00",
            "yes_total_cost_dollars": "5.00",
            "no_total_cost_dollars": "0.00",
            "fee_cost": "0.00",
        }
    ]
    report, markets = run(world, NOW + timedelta(minutes=10))
    assert report["decision"] == "spread_loss_stop" and markets is None
    assert ex.resting == [] and len(ex.canceled) == 2


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
