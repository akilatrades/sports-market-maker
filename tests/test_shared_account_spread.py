"""Shared account risk with the spread maker as a third cohort (offline)."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from kalshi.trading import TradingError
from live import shared_account_risk as shared

NOW = datetime(2026, 10, 22, 22, 0, tzinfo=UTC)


def pair(sport, ticker, key, cost=0.5, count=1, side="no", accepted=True):
    cid = f"client-{sport}-{key}"
    events = [
        {
            "event": "intent",
            "client_order_id": cid,
            "ticker": ticker,
            "utc": NOW.isoformat(),
            "cost": cost,
            "count": count,
            "side": side,
            "tip_utc": (NOW + timedelta(hours=4)).isoformat(),
        }
    ]
    if accepted:
        events.append(
            {"event": "accepted", "client_order_id": cid, "order_id": f"order-{cid}"}
        )
    return events


def cohorts(spread=None):
    return {
        "nfl": pair("nfl", "KXNFLRECYDS-A", "a"),
        "nba": pair("nba", "KXNBAPTS-B", "b"),
        "spread": spread
        if spread is not None
        else pair("spread", "KXDOTA2GAME-C", "c1", side="yes")
        + pair("spread", "KXDOTA2GAME-C", "c2", side="no"),
    }


def test_spread_orders_and_either_side_positions_are_owned():
    owner = shared.ownership(cohorts())
    assert owner["cohorts"] == ("nfl", "nba", "spread")
    result = shared.classify(
        [{"order_id": "order-client-spread-c1", "ticker": "KXDOTA2GAME-C"}],
        [{"market_ticker": "KXDOTA2GAME-C", "position_fp": "1"}],
        owner,
    )
    assert len(result["spread"]["resting"]) == 1
    assert result["spread"]["positions"] == {"KXDOTA2GAME-C": 1.0}


def test_nba_and_nfl_still_cannot_hold_yes():
    owner = shared.ownership(cohorts())
    with pytest.raises(TradingError, match="wrong-side"):
        shared.classify([], [{"ticker": "KXNBAPTS-B", "position_fp": "1"}], owner)


def test_spread_cannot_hold_more_than_it_ordered():
    owner = shared.ownership(cohorts())
    with pytest.raises(TradingError, match="exceeds accepted intent"):
        shared.classify([], [{"ticker": "KXDOTA2GAME-C", "position_fp": "3"}], owner)


def test_bots_never_share_a_market():
    events = cohorts(spread=pair("spread", "KXNBAPTS-B", "x", side="yes"))
    with pytest.raises(TradingError, match="Overlapping markets"):
        shared.ownership(events)


def test_spread_orders_do_not_use_nba_nfl_limits():
    big = [
        e
        for i in range(40)
        for e in pair("spread", f"KXDOTA2GAME-{i}", f"s{i}", cost=60.0)
    ]
    owner = shared.ownership(cohorts(spread=big))
    checks = shared.room(owner, set(), 3, NOW)
    assert all(checks.values())
    with pytest.raises(TradingError, match="Unreconciled shared active"):
        shared.room(owner, {"client-spread-s1"}, 3, NOW)


def test_refused_quote_is_resolved_only_with_signed_evidence():
    refused = pair("spread", "KXDOTA2GAME-C", "r", accepted=False)
    good = refused + [
        {
            "event": "rejected_4xx",
            "client_order_id": "client-spread-r",
            "http_status": 400,
            "evidence": shared.SPREAD_REJECTION_EVIDENCE,
            "utc": NOW.isoformat(),
        }
    ]
    owner = shared.ownership(cohorts(spread=good))
    assert "client-spread-r" in owner["rejected_by_sport"]["spread"]
    # A refused quote never existed, so it adds no inventory allowance, but
    # it does not make the market a rejected ticker either.
    assert "KXDOTA2GAME-C" not in owner["rejected_tickers"]
    with pytest.raises(TradingError, match="exceeds accepted intent"):
        shared.classify([], [{"ticker": "KXDOTA2GAME-C", "position_fp": "1"}], owner)
    for bad in (
        {"http_status": 500},
        {"http_status": "400"},
        {"evidence": "assumed"},
        {"utc": ""},
    ):
        event = {**good[-1], **bad}
        with pytest.raises(TradingError, match="spread rejection"):
            shared.ownership(cohorts(spread=refused + [event]))


def test_unanswered_or_ambiguous_spread_order_halts_every_bot():
    pending = pair("spread", "KXDOTA2GAME-C", "p", accepted=False)
    with pytest.raises(TradingError, match="Unreconciled"):
        shared.ownership(cohorts(spread=pending))
    unknown = pending + [
        {"event": "unknown_outcome", "client_order_id": "client-spread-p"}
    ]
    with pytest.raises(TradingError, match="Ambiguous"):
        shared.ownership(cohorts(spread=unknown))


def _write(root, sport, events):
    folder = root / f"prod-{sport}-auto"
    folder.mkdir()
    (folder / "journal.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))


class Exchange:
    def __init__(self, resting=(), positions=(), fills=(), settlements=()):
        self._resting, self._positions = list(resting), list(positions)
        self._fills, self._settlements = list(fills), list(settlements)

    def orders(self, status):
        return self._resting

    def positions(self):
        return self._positions

    def settlements(self):
        return self._settlements

    def fills(self, min_ts):
        return self._fills


def test_state_for_without_spread_journal_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(shared, "ROOT", tmp_path)
    events = cohorts()
    _write(tmp_path, "nfl", events["nfl"])
    _write(tmp_path, "nba", events["nba"])
    state, context = shared.state_for(Exchange(), "nba", NOW)
    assert context["ownership"]["cohorts"] == ("nfl", "nba")
    with pytest.raises(TradingError, match="Missing spread"):
        shared.state_for(Exchange(), "spread", NOW)
    # Without the spread journal, a spread order is unowned: everyone halts.
    stray = Exchange(resting=[{"order_id": "order-client-spread-c1"}])
    with pytest.raises(TradingError, match="Unowned resting"):
        shared.state_for(stray, "nba", NOW)


def test_state_for_with_spread_journal(monkeypatch, tmp_path):
    monkeypatch.setattr(shared, "ROOT", tmp_path)
    events = cohorts()
    for sport in ("nfl", "nba", "spread"):
        _write(tmp_path, sport, events[sport])
    exchange = Exchange(
        resting=[
            {"order_id": "order-client-spread-c2", "ticker": "KXDOTA2GAME-C"},
            {"order_id": "order-client-nba-b", "ticker": "KXNBAPTS-B"},
        ],
        positions=[{"market_ticker": "KXDOTA2GAME-C", "position_fp": "1"}],
        fills=[{"ticker": "KXDOTA2GAME-C", "order_id": "order-client-spread-c1"}],
    )
    nba, context = shared.state_for(exchange, "nba", NOW)
    assert len(nba["resting"]) == 1
    assert context["active_client_ids"] <= {"client-nfl-a", "client-nba-b"}
    spread, _ = shared.state_for(exchange, "spread", NOW)
    assert spread["positions"] == {"KXDOTA2GAME-C": 1.0}
    assert len(spread["attempts"]) == 2
    foreign = Exchange(fills=[{"ticker": "KXDOTA2GAME-C", "order_id": "manual"}])
    with pytest.raises(TradingError, match="Unowned fill"):
        shared.state_for(foreign, "spread", NOW)


def settled(ticker, pnl, result="no"):
    return {
        "market_ticker": ticker,
        "settled_time": NOW.isoformat(),
        "market_result": result,
        "revenue_dollars": "0.00",
        "yes_total_cost_dollars": str(abs(pnl)),
        "no_total_cost_dollars": "0.00",
        "fee_cost": "0.00",
    }


def spread_events(*legs):
    """Spread intents with prices, each accepted: (key, side, cents)."""
    events = []
    for key, side, cents in legs:
        for e in pair("spread", "KXDOTA2GAME-C", key, cost=cents / 100, side=side):
            events.append({**e, "price_cents": cents} if e["event"] == "intent" else e)
    return events


def spread_fill(key, side, cents, minutes, **extra):
    yes = cents if side == "yes" else 100 - cents
    return {
        "fill_id": f"f-{key}",
        "order_id": f"order-client-spread-{key}",
        "ticker": "KXDOTA2GAME-C",
        "created_time": (NOW - timedelta(minutes=minutes)).isoformat(),
        "count_fp": "1.00",
        "yes_price_dollars": f"{yes / 100:.2f}",
        "no_price_dollars": f"{(100 - yes) / 100:.2f}",
        "fee_cost": "0.00",
        **extra,
    }


def test_spread_ledger_pairs_settlements_and_checks():
    events = spread_events(("a", "yes", 41), ("b", "no", 74), ("c", "yes", 40))
    fills = [spread_fill("a", "yes", 41, 30), spread_fill("b", "no", 74, 20)]
    # A closed pair realizes $1 - 41c - 74c = -15c when the second leg fills.
    ledger = shared.spread_ledger(events, fills, [], NOW)
    assert ledger["daily"] == pytest.approx(-0.15) and ledger["open"] == {}
    # A duplicate copy of a fill counts once.
    assert shared.spread_ledger(events, fills + fills[:1], [], NOW) == ledger
    # A contract still held at settlement realizes payout minus price.
    fills.append(spread_fill("c", "yes", 40, 10))
    held = shared.spread_ledger(events, fills, [], NOW)
    assert held["open"] == {"KXDOTA2GAME-C": [("yes", 0.40, 1.0)]}
    win = shared.spread_ledger(
        events,
        fills,
        [{**settled("KXDOTA2GAME-C", 0, "yes"), "revenue_dollars": "1.00"}],
        NOW,
    )
    assert win["daily"] == pytest.approx(-0.15 + 0.60) and win["settled"] == {
        "KXDOTA2GAME-C"
    }
    for bad_settlement in (
        {**settled("KXDOTA2GAME-C", 0, "yes")},  # revenue 0 but we held a winner
        {**settled("KXDOTA2GAME-C", 0, ""), "revenue_dollars": None},
    ):
        with pytest.raises(TradingError, match="settlement"):
            shared.spread_ledger(events, fills, [bad_settlement], NOW)
    for bad_fill, message in (
        (spread_fill("a", "yes", 41, 30, outcome_side="no"), "direction"),
        (spread_fill("a", "yes", 45, 30), "price"),
        ({**spread_fill("a", "yes", 41, 30), "fill_id": None}, "identity"),
        ({**spread_fill("a", "yes", 41, 30), "created_time": None}, "Undated"),
    ):
        with pytest.raises(TradingError, match=message):
            shared.spread_ledger(events, [bad_fill], [], NOW)


def test_account_loss_stop_counts_spread_pairs_and_settlements(monkeypatch, tmp_path):
    monkeypatch.setattr(shared, "ROOT", tmp_path)
    events = cohorts(spread=spread_events(("a", "yes", 41), ("b", "no", 74)))
    for sport in ("nfl", "nba", "spread"):
        _write(tmp_path, sport, events[sport])
    fills = [spread_fill("a", "yes", 41, 30), spread_fill("b", "no", 74, 20)]
    nba_loss = settled("KXNBAPTS-B", -19.85)
    exchange = Exchange(settlements=[nba_loss], fills=fills)
    _, context = shared.state_for(exchange, "nba", NOW)
    pnl = context["account_pnl"]
    # -19.85 settled on NBA plus the spread pair's -0.15 that no settlement shows.
    assert pnl["daily_realized_pnl_dollars"] == pytest.approx(-20.0)
    assert pnl["spread_daily_realized_pnl_dollars"] == pytest.approx(-0.15)
    assert shared.account_loss_stop(context) is True
    # Spread settlement records never count twice: its markets come from the ledger.
    exchange = Exchange(settlements=[settled("KXDOTA2GAME-C", -8)], fills=fills)
    _, context = shared.state_for(exchange, "nba", NOW)
    assert context["account_pnl"]["daily_realized_pnl_dollars"] == pytest.approx(-0.15)
    # An unaccountable spread fill blocks new orders for every bot.
    bad = Exchange(fills=[spread_fill("a", "yes", 45, 30)])
    _, context = shared.state_for(bad, "nba", NOW)
    with pytest.raises(TradingError, match="unverifiable"):
        shared.account_loss_stop(context)


def test_owner_reconciliation_resolves_an_ambiguous_spread_order():
    pending = pair("spread", "KXDOTA2GAME-C", "p", accepted=False) + [
        {"event": "unknown_outcome", "client_order_id": "client-spread-p"}
    ]
    found = pending + [
        {"event": "accepted", "client_order_id": "client-spread-p", "order_id": "o-p"}
    ]
    assert shared.ownership(cohorts(spread=found))["orders"]["o-p"] == "spread"
    absent = {
        "event": "reconciled_absent",
        "client_order_id": "client-spread-p",
        "evidence": shared.SPREAD_ABSENT_EVIDENCE,
        "intent_age_seconds": 900,
        "utc": NOW.isoformat(),
    }
    owner = shared.ownership(cohorts(spread=pending + [absent]))
    assert "client-spread-p" in owner["rejected_by_sport"]["spread"]
    assert "KXDOTA2GAME-C" not in owner["rejected_tickers"]
    for bad in ({"intent_age_seconds": 300}, {"evidence": "assumed"}, {"utc": ""}):
        with pytest.raises(TradingError, match="spread rejection"):
            shared.ownership(cohorts(spread=pending + [{**absent, **bad}]))
    # NBA keeps its stricter rule: an acceptance never clears an unknown.
    nba = pair("nba", "KXNBAPTS-B", "b") + [
        {"event": "unknown_outcome", "client_order_id": "client-nba-b"}
    ]
    with pytest.raises(TradingError, match="Ambiguous"):
        shared.ownership({**cohorts(), "nba": nba})
