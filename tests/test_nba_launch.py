import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from kalshi.fees import maker_fee_bound
from kalshi.trading import TradingClient, TradingError
from live import nba_inputs, prod_nba_auto as nba
from markets.nba.live import parse_injuries, parse_scoreboard


def test_sizing_includes_reserve_and_expiry_stays_before_last_two_hours():
    now = datetime.now(UTC)
    row = SimpleNamespace(price=.60, ticker="KXNBAPTS-X-Y", tip_utc=now+timedelta(hours=4))
    order, cost = nba.order_from_row(row, now)
    assert order.count == 4
    assert cost == 2.4 and nba.reserve(cost) == 2.64
    assert order.expiration_ts == int(now.timestamp())+3600
    row.tip_utc = now+timedelta(hours=2, minutes=20)
    assert nba.order_from_row(row, now)[0].expiration_ts == int(now.timestamp())+1200


def test_bundle_detects_mixed_generation_future_and_stale(tmp_path):
    now = datetime.now(UTC)
    nba_inputs.publish(pd.DataFrame({"ticker": ["A"]}), tmp_path, now)
    data, meta = nba_inputs.read(tmp_path, now)
    assert meta["rows"] == 1
    with pytest.raises(ValueError, match="checksum"):
        nba_inputs.validate(data+b"\n", meta, now)
    with pytest.raises(ValueError, match="age"):
        nba_inputs.validate(data, meta, now+timedelta(hours=10))
    with pytest.raises(ValueError, match="age"):
        nba_inputs.validate(data, meta, now-timedelta(minutes=1))


def test_input_sync_pins_all_data_to_one_commit(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    source = tmp_path / "source"
    nba_inputs.publish(pd.DataFrame({"ticker": ["A"]}), source, now)
    calls = []
    def get(url):
        calls.append(url)
        if "/commits/main" in url:
            return json.dumps({"sha": "a"*40}).encode()
        if url.endswith("nba_latest.csv"):
            raise OSError("missing books")
        return (source / url.rsplit("/", 1)[-1]).read_bytes()
    monkeypatch.setattr(nba_inputs, "download", get)
    dest = tmp_path / "dest"
    nba_inputs.sync(dest, now)
    assert all("a"*40 in url for url in calls[1:])
    assert (dest / "nba_books.csv").read_bytes() == b""
    assert nba_inputs.read(dest, now)[1]["source_commit"] == "a"*40


def test_malformed_feeds_are_not_healthy_empty_reports():
    for value in ({}, {"injuries": None}, {"injuries": [{}]}):
        with pytest.raises(ValueError):
            parse_injuries(value)
    with pytest.raises(ValueError):
        parse_scoreboard({}, 2027)
    report = parse_injuries({"injuries": [{"injuries": [{"status":"Out", "athlete":{"id":"42"}}]}]})
    assert report.player_id.iloc[0] == 42
    assert report.out.iloc[0]


def test_fee_bounds_event_override_and_unsupported_models():
    series = {"fee_type":"quadratic", "fee_multiplier":1}
    assert maker_fee_bound(.6, 4, series, {}) == 0
    assert maker_fee_bound(.6, 4, series, {"fee_type_override":"quadratic_with_maker_fees"}) == .04
    with pytest.raises(TradingError):
        maker_fee_bound(.6, 4, series, {"fee_type_override":"flat"})
    with pytest.raises(TradingError):
        maker_fee_bound(.6, 4, {"fee_type":"quadratic"}, {})


def test_settlement_corrects_legacy_record_and_does_not_double_count(tmp_path):
    journal = tmp_path / "journal.jsonl"
    attempts = [{"ticker":"NBA"}]
    old = {"event":"settlement", "ticker":"NBA", "fee_cents": ".02"}
    nba.write_event(journal, old)
    result = {"ticker":"NBA", "revenue":400, "yes_total_cost_dollars":"0", "no_total_cost_dollars":"2.4", "fee_cost":"0.02"}
    nba.record_execution(journal, [old], attempts, {}, [], [result])
    events = nba.load_journal(journal)
    assert events[-1]["net_profit_dollars"] == 1.58
    assert events[-1]["fee_dollars"] == .02
    nba.record_execution(journal, events, attempts, {}, [], [result])
    assert len(nba.load_journal(journal)) == 2


@pytest.mark.parametrize("method,key", [("orders","orders"),("fills","fills"),("settlements","settlements")])
def test_account_reads_reject_missing_lists_and_repeated_cursors(monkeypatch, method, key):
    client = TradingClient(dry_run=True, env="prod")
    monkeypatch.setattr(client, "_request", lambda *args: {})
    with pytest.raises(TradingError):
        getattr(client, method)()
    monkeypatch.setattr(client, "_request", lambda *args: {key: [], "cursor":"repeat"})
    with pytest.raises(TradingError, match="cursor"):
        getattr(client, method)()


def test_balance_prefers_fixed_point_and_rejects_unknown(monkeypatch):
    client = TradingClient(dry_run=True, env="prod")
    monkeypatch.setattr(client, "_request", lambda *args: {"balance":12, "balance_dollars":"0.1234", "portfolio_value":100})
    assert client.balance() == {"balance":.1234, "portfolio_value":1.0}
    monkeypatch.setattr(client, "_request", lambda *args: {"portfolio_value":0})
    with pytest.raises(TradingError):
        client.balance()


def test_preflight_client_cannot_write():
    client = nba.ReadOnlyClient(dry_run=True, env="prod")
    for method in ("POST", "DELETE", "PUT"):
        with pytest.raises(TradingError, match="rejects exchange writes"):
            client._request(method, "/portfolio/orders")


def test_actual_fill_markouts_separate_mid_from_executable_bid_and_missing_windows(tmp_path):
    now = datetime.now(UTC)
    journal = tmp_path / "journal.jsonl"
    nba.write_event(journal, {"event":"fill", "fill_id":"f1", "ticker":"NBA", "utc":(now-timedelta(minutes=6)).isoformat(), "no_price":"0.60"})
    quotes = pd.DataFrame([{"ticker":"NBA", "yes_bid_dollars":.42, "yes_ask_dollars":.44}])
    nba.record_markouts(journal, quotes, now)
    mark = nba.load_journal(journal)[-1]
    assert mark["mid_move_dollars"] == -.03
    assert mark["bid_move_dollars"] == -.04
    nba.record_markouts(journal, quotes, now+timedelta(minutes=90))
    assert nba.load_journal(journal)[-1]["issue"] == "missed_observation_window"
    assert nba.load_journal(journal)[-1]["mid_move_dollars"] is None
