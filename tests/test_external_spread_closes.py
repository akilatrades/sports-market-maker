"""Explicit external closes must reduce inventory and retain fail-closed ownership."""
from copy import deepcopy
from datetime import timedelta

import pytest

from kalshi.trading import TradingError
from live import external_spread_closes as external
from live import shared_account_risk as shared
from tests.test_shared_account_spread import NOW, spread_events, spread_fill, settled, cohorts, Exchange, _write


def fixture():
    events = spread_events(("a", "yes", 6))
    entry = spread_fill("a", "yes", 6, 30, count_fp="5.00")
    close = {"fill_id": "manual-fill", "order_id": "manual-order", "ticker": entry["ticker"],
             "created_time": (NOW-timedelta(minutes=20)).isoformat(), "count_fp": "5.00",
             "outcome_side": "no", "book_side": "ask", "side": "no", "action": "sell",
             "yes_price_dollars": "0.4500", "no_price_dollars": "0.5500", "fee_cost": "0.086700"}
    approval = {"event": "external_close", "utc": NOW.isoformat(), "fill": close,
                "fill_sha256": external.fingerprint(close), "snapshot_sha256": "a"*64,
                "reason": "owner_manual_cashout", "evidence": external.EVIDENCE}
    return events+[approval], entry, close


def test_exact_manual_close_nets_and_charges_precise_fee_once():
    events, entry, close = fixture()
    ledger = shared.spread_ledger(events, [entry, close, close], [], NOW)
    assert ledger['open']=={}
    assert ledger['cumulative']==pytest.approx(1.8633)
    assert ledger['fills']==2


def test_settlement_for_closed_market_requires_zero_payout():
    events, entry, close = fixture()
    end = settled(entry['ticker'], 0, 'yes')
    assert shared.spread_ledger(events,[entry,close],[end],NOW)['cumulative']==pytest.approx(1.8633)
    with pytest.raises(TradingError, match='settlement disagrees'):
        shared.spread_ledger(events,[entry,close],[{**end,'revenue_dollars':'5'}],NOW)


def test_approved_evidence_survives_exchange_history_retention():
    events, entry, _ = fixture()
    assert shared.spread_ledger(events,[entry],[],NOW)['cumulative']==pytest.approx(1.8633)


def test_signed_fill_disagreement_halts():
    events, entry, close = fixture()
    with pytest.raises(TradingError,match='disagrees'):
        shared.spread_ledger(events,[entry,{**close,'count_fp':'6'}],[],NOW)


def test_changed_approval_evidence_halts():
    events, _, close = fixture()
    changed=deepcopy(events);changed[-1]['fill']['fee_cost']='0'
    with pytest.raises(TradingError,match='evidence changed'):external.approved(changed,[close],NOW)


def test_approval_cannot_open_reverse_position():
    events, entry, close=fixture()
    entry={**entry,'count_fp':'4'}
    with pytest.raises(TradingError,match='exceed held'):shared.spread_ledger(events,[entry,close],[],NOW)


def test_approval_cannot_close_same_side_position():
    events, _, close=fixture()
    with pytest.raises(TradingError,match='exceed held'):shared.spread_ledger(events,[close],[],NOW)


def test_close_after_settlement_halts():
    events,entry,close=fixture()
    end={**settled(entry['ticker'],0),'settled_time':(NOW-timedelta(minutes=25)).isoformat()}
    with pytest.raises(TradingError,match='exceed held'):shared.spread_ledger(events,[entry,close],[end],NOW)


def test_duplicate_approval_not_silently_accepted():
    events, _, close=fixture()
    with pytest.raises(TradingError,match='Ambiguous'):external.approved(events+[events[-1]],[close],NOW)


def test_incomplete_canonical_fields_and_unknown_fees_rejected():
    _, _, close=fixture()
    for key in ('book_side','outcome_side','fee_cost','fill_id'):
        f=deepcopy(close);del f[key]
        with pytest.raises(TradingError):external.normalize(f)


def test_unowned_market_cannot_be_adopted():
    events, _, close=fixture()
    events[-1]['fill']={**close,'ticker':'UNOWNED'}
    events[-1]['fill_sha256']=external.fingerprint(events[-1]['fill'])
    with pytest.raises(TradingError,match='Ambiguous'):external.approved(events,[],NOW)


def test_shared_guard_uses_approved_close_and_reconciles_positions(monkeypatch,tmp_path):
    events,entry,close=fixture()
    all_events=cohorts(spread=events)
    monkeypatch.setattr(shared,'ROOT',tmp_path)
    for sport, rows in all_events.items():_write(tmp_path,sport,rows)
    exchange=Exchange(fills=[entry,close])
    state,_=shared.state_for(exchange,'nba',NOW)
    assert state['held']==[]
    with pytest.raises(TradingError,match='Unowned fill'):
        shared.state_for(Exchange(fills=[entry,close,{**close,'fill_id':'other-manual'}]),'nba',NOW)
    with pytest.raises(TradingError,match='signed positions'):
        shared.state_for(Exchange(fills=[entry,close],positions=[{'market_ticker':entry['ticker'],'position_fp':'1'}]),'nba',NOW)
