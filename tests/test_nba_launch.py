import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from kalshi.fees import maker_fee_bound
from kalshi.trading import TradingClient, TradingError
from live import nba_inputs, prod_nba_auto as nba
from markets.nba.live import parse_injuries, parse_scoreboard


@pytest.fixture(autouse=True)
def mocked_production_shard_for_offline_tests(monkeypatch):
    # These legacy unit clients are intentionally offline stubs. Separate
    # tests/test_shard_funding.py validates the actual signed-GET gate.
    monkeypatch.setattr(nba, "require_funded_shard", lambda *args: 3)


def test_nba_orders_expire_at_tip_despite_early_entry_cutoff():
    now = datetime.now(UTC)
    row = SimpleNamespace(
        price=0.60, ticker="KXNBAPTS-X-Y", tip_utc=now + timedelta(hours=4)
    )
    order, cost = nba.order_from_row(row, now)
    assert order.count == nba.MAX_CONTRACTS == 1
    assert cost == 0.6 and nba.reserve(cost) == 0.66
    # New maker orders are submitted 2-6h before tip, but may rest until tip.
    assert order.expiration_ts == int(now.timestamp()) + 4 * 3600
    row.tip_utc = now + timedelta(hours=2, minutes=20)
    assert (
        nba.order_from_row(row, now)[0].expiration_ts
        == int(now.timestamp()) + 2 * 3600 + 1200
    )


def test_bundle_detects_mixed_generation_future_and_stale(tmp_path):
    now = datetime.now(UTC)
    nba_inputs.publish(pd.DataFrame({"ticker": ["A"]}), tmp_path, now)
    data, meta = nba_inputs.read(tmp_path, now)
    assert meta["rows"] == 1
    with pytest.raises(ValueError, match="checksum"):
        nba_inputs.validate(data + b"\n", meta, now)
    with pytest.raises(ValueError, match="age"):
        nba_inputs.validate(data, meta, now + timedelta(hours=10))
    with pytest.raises(ValueError, match="age"):
        nba_inputs.validate(data, meta, now - timedelta(minutes=1))


def test_input_sync_pins_all_data_to_one_commit(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    source = tmp_path / "source"
    nba_inputs.publish(pd.DataFrame({"ticker": ["A"]}), source, now)
    calls = []

    def get(url):
        calls.append(url)
        if "/commits/main" in url:
            return json.dumps({"sha": "a" * 40}).encode()
        if url.endswith("nba_latest.csv"):
            raise OSError("missing books")
        return (source / url.rsplit("/", 1)[-1]).read_bytes()

    monkeypatch.setattr(nba_inputs, "download", get)
    dest = tmp_path / "dest"
    nba_inputs.sync(dest, now)
    assert all("a" * 40 in url for url in calls[1:])
    assert (dest / "nba_books.csv").read_bytes() == b""
    assert nba_inputs.read(dest, now)[1]["source_commit"] == "a" * 40


def test_malformed_feeds_are_not_healthy_empty_reports():
    for value in ({}, {"injuries": None}, {"injuries": [{}]}):
        with pytest.raises(ValueError):
            parse_injuries(value)
    with pytest.raises(ValueError):
        parse_scoreboard({}, 2027)
    report = parse_injuries(
        {"injuries": [{"injuries": [{"status": "Out", "athlete": {"id": "42"}}]}]}
    )
    assert report.player_id.iloc[0] == 42
    assert report.out.iloc[0]


def test_empty_schedule_days_preserve_utc_dtype_for_opening_week():
    empty = parse_scoreboard({"events": []}, 2027)
    assert pd.api.types.is_float_dtype(empty.home_spread)
    assert pd.api.types.is_float_dtype(empty.total)
    game = pd.DataFrame(
        {"tip_utc": [pd.Timestamp("2026-10-20T19:00:00Z")], "completed": [False]}
    )
    joined = pd.concat([empty, game, empty], ignore_index=True)
    assert joined.tip_utc.dt.tz_convert("America/New_York").dt.hour.tolist() == [15]
    assert not joined.completed.iloc[0]


def test_fee_bounds_event_override_and_unsupported_models():
    series = {"fee_type": "quadratic", "fee_multiplier": 1}
    assert maker_fee_bound(0.6, 4, series, {}) == 0
    assert (
        maker_fee_bound(
            0.6, 4, series, {"fee_type_override": "quadratic_with_maker_fees"}
        )
        == 0.04
    )
    with pytest.raises(TradingError):
        maker_fee_bound(0.6, 4, series, {"fee_type_override": "flat"})
    with pytest.raises(TradingError):
        maker_fee_bound(0.6, 4, {"fee_type": "quadratic"}, {})


def test_settlement_corrects_legacy_record_and_does_not_double_count(tmp_path):
    journal = tmp_path / "journal.jsonl"
    attempts = [{"ticker": "NBA"}]
    old = {"event": "settlement", "ticker": "NBA", "fee_cents": ".02"}
    nba.write_event(journal, old)
    result = {
        "ticker": "NBA",
        "revenue": 400,
        "yes_total_cost_dollars": "0",
        "no_total_cost_dollars": "2.4",
        "fee_cost": "0.02",
    }
    nba.record_execution(journal, [old], attempts, {}, [], [result])
    events = nba.load_journal(journal)
    assert events[-1]["net_profit_dollars"] == 1.58
    assert events[-1]["fee_dollars"] == 0.02
    nba.record_execution(journal, events, attempts, {}, [], [result])
    assert len(nba.load_journal(journal)) == 2


@pytest.mark.parametrize(
    "method,key",
    [("orders", "orders"), ("fills", "fills"), ("settlements", "settlements")],
)
def test_account_reads_reject_missing_lists_and_repeated_cursors(
    monkeypatch, method, key
):
    client = TradingClient(dry_run=True, env="prod")
    monkeypatch.setattr(client, "_request", lambda *args: {})
    with pytest.raises(TradingError):
        getattr(client, method)()
    monkeypatch.setattr(client, "_request", lambda *args: {key: [], "cursor": "repeat"})
    with pytest.raises(TradingError, match="cursor"):
        getattr(client, method)()


def test_balance_prefers_fixed_point_and_rejects_unknown(monkeypatch):
    client = TradingClient(dry_run=True, env="prod")
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args: {
            "balance": 12,
            "balance_dollars": "0.1234",
            "portfolio_value": 100,
        },
    )
    assert client.balance() == {"balance": 0.1234, "portfolio_value": 1.0}
    monkeypatch.setattr(client, "_request", lambda *args: {"portfolio_value": 0})
    with pytest.raises(TradingError):
        client.balance()


def test_preflight_client_cannot_write():
    client = nba.ReadOnlyClient(dry_run=True, env="prod")
    for method in ("POST", "DELETE", "PUT"):
        with pytest.raises(TradingError, match="rejects exchange writes"):
            client._request(method, "/portfolio/orders")


def test_actual_fill_markouts_separate_mid_from_executable_bid_and_missing_windows(
    tmp_path,
):
    now = datetime.now(UTC)
    journal = tmp_path / "journal.jsonl"
    nba.write_event(
        journal,
        {
            "event": "fill",
            "fill_id": "f1",
            "ticker": "NBA",
            "utc": (now - timedelta(minutes=6)).isoformat(),
            "no_price": "0.60",
        },
    )
    quotes = pd.DataFrame(
        [{"ticker": "NBA", "yes_bid_dollars": 0.42, "yes_ask_dollars": 0.44}]
    )
    nba.record_markouts(journal, quotes, now)
    mark = nba.load_journal(journal)[-1]
    assert mark["mid_move_dollars"] == -0.03
    assert mark["bid_move_dollars"] == -0.04
    nba.record_markouts(journal, quotes, now + timedelta(minutes=90))
    assert nba.load_journal(journal)[-1]["issue"] == "missed_observation_window"
    assert nba.load_journal(journal)[-1]["mid_move_dollars"] is None


def test_full_pass_records_fee_evidence_and_never_retries_an_uncertain_post(
    tmp_path, monkeypatch
):
    import kalshi.fees as fees
    from tests.test_prod_nba_auto import ARMED, NOW, priced

    class Client:
        env, dry_run, can_sign = "prod", False, True

        def __init__(self):
            self.posts = 0
            self.fail = False

        def orders(self, *args):
            return []

        def positions(self):
            return []

        def settlements(self):
            return []

        def fills(self, **kwargs):
            return []

        def balance(self):
            return {"balance": 100.0}

        def queue_position(self, oid):
            return 12.0

        def place(self, order):
            self.posts += 1
            assert (
                order.post_only
                and nba.reserve(order.count * order.price_cents / 100)
                <= nba.MAX_ORDER_COST
            )
            if self.fail:
                raise OSError("timeout")
            return {"order_id": "accepted"}

    monkeypatch.setattr(nba, "verify_quote", lambda *args: None)
    monkeypatch.setattr(
        fees,
        "live_maker_fee_bound",
        lambda *args: (
            0.05,
            {"fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1},
        ),
    )
    client = Client()
    journal = tmp_path / "journal.jsonl"
    assert nba.pass_once(client, ARMED, priced(), NOW, journal)
    events = nba.load_journal(journal)
    assert events[0]["probability_source"] == "sportsbook"
    assert events[0]["net_edge_after_fee_bound"] > 0
    assert client.posts == 1
    assert (
        json.loads((tmp_path / "last_scan.json").read_text())["decision"] == "accepted"
    )
    uncertain = tmp_path / "uncertain.jsonl"
    client.fail = True
    with pytest.raises(TradingError, match="Ambiguous"):
        nba.pass_once(client, ARMED, priced(), NOW, uncertain)
    assert client.posts == 2
    with pytest.raises(TradingError, match="Uncertain"):
        nba.pass_once(client, ARMED, priced(), NOW, uncertain)
    assert client.posts == 2


def test_expired_unfilled_uses_recorded_expiry_and_keeps_partial_fills_reserved():
    now = datetime.now(UTC)
    intent = {
        "client_order_id": "c",
        "ticker": "NBA",
        "expiration_ts": int((now - timedelta(minutes=11)).timestamp()),
        "tip_utc": (now + timedelta(hours=3)).isoformat(),
    }
    accepted = {"c": {"order_id": "o"}}
    state = {"resting": [], "held": [], "settled": set()}
    active, released = nba.reconcile_expired_unfilled(
        [intent], accepted, state, [], now
    )
    assert not active and released == 1
    active, released = nba.reconcile_expired_unfilled(
        [intent], accepted, state, [{"order_id": "o"}], now
    )
    assert active == [intent] and released == 0


def test_private_dashboard_keeps_nba_cohort_separate(tmp_path):
    from live.account_dashboard import collect

    state = tmp_path / "prod-nba-auto"
    state.mkdir()
    (state / "journal.jsonl").write_text("")
    stamp = datetime.now(UTC).isoformat()
    (state / "last_scan.json").write_text(
        json.dumps(
            {
                "utc": stamp,
                "decision": "no_eligible_candidates",
                "inputs": {"rows": 312, "in_entry_window": 0},
                "candidate_count": 0,
            }
        )
    )
    client = SimpleNamespace(
        _request=lambda *args: {"balance_dollars": "123.45", "portfolio_value": 0},
        pages=lambda *args, **kwargs: [],
    )
    result = collect(client, state)
    assert result["strategy"]["name"] == "NBA passive NO entries"
    assert result["strategy"]["accepted_orders"] == 0
    assert result["account"]["cash_dollars"] == 123.45
    assert result["scan"]["run_utc"] == stamp


def test_fixed_point_foreign_or_opposite_positions_cannot_hide_behind_legacy_zero():
    client = SimpleNamespace(
        orders=lambda *args: [],
        positions=lambda: [{"ticker": "NBA", "position": 0, "position_fp": "-0.5"}],
        settlements=lambda: [],
    )
    with pytest.raises(TradingError, match="Foreign open"):
        nba.current_production_state(client, [], {})
    client.positions = lambda: [{"ticker": "NBA", "position_fp": "1.0"}]
    with pytest.raises(TradingError, match="contradicts"):
        nba.current_production_state(client, [{"ticker": "NBA", "count": 2}], {})
