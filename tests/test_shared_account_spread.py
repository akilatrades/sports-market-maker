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


def test_account_loss_stop_counts_spread_markets(monkeypatch, tmp_path):
    def settled(ticker, pnl):
        return {
            "market_ticker": ticker,
            "settled_time": NOW.isoformat(),
            "revenue_dollars": "0.00",
            "yes_total_cost_dollars": str(abs(pnl)),
            "no_total_cost_dollars": "0.00",
            "fee_cost": "0.00",
        }

    monkeypatch.setattr(shared, "ROOT", tmp_path)
    events = cohorts()
    for sport in ("nfl", "nba", "spread"):
        _write(tmp_path, sport, events[sport])
    exchange = Exchange(
        settlements=[settled("KXNBAPTS-B", -12), settled("KXDOTA2GAME-C", -8)]
    )
    _, context = shared.state_for(exchange, "nba", NOW)
    assert context["account_pnl"]["daily_realized_pnl_dollars"] == -20
    assert shared.account_loss_stop(context) is True
