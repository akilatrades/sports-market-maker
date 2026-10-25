from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from deploy.spread_forward_control import cron
from research.spread_forward_core import (
    EvidenceError,
    consume,
    external_book,
    normalize_fill,
    normalized_orders,
    replay,
)
from research.spread_forward_recorder import ReadOnlyAPI, Store, cohort, environment
from research.spread_forward_report import report

START = datetime(2026, 10, 26, tzinfo=UTC)


def fill(fid="a", side="yes", quantity="5", price="0.40", minutes=0):
    return dict(
        fid=fid,
        oid=fid,
        ticker="TEST-E-M",
        event_ticker="TEST-E",
        side=side,
        quantity=quantity,
        price=price,
        fee="0.03",
        at=(START + timedelta(minutes=minutes)).isoformat(),
        version="v3",
    )


def sample(fills, yes=None, minute=10, valid=True):
    return dict(
        id=str(minute),
        at=(START + timedelta(minutes=minute)).isoformat(),
        ticker="TEST-E-M",
        valid=valid,
        fee_type="quadratic",
        fee_multiplier="1",
        external_book={"yes": yes or [["0.55", "2"]], "no": [["0.30", "5"]]},
        lots=[
            {
                "fid": f["fid"],
                "fill_at": f["at"],
                "horizon_seconds": minute * 60,
                "remaining_actual": f["quantity"],
            }
            for f in fills
        ],
    )


def test_partial_exit_keeps_remaining_inventory_and_fees():
    f = fill()
    result = replay([f], [sample([f])], {"TEST-E-M": {"yes_payout": "1"}})
    # 2 sold: .30 gross - .04 exit fees. 3 settle: 1.80. Entry fee .03.
    assert Decimal(result["resolved_total"]) == Decimal("2.03")
    assert result["sales"][0]["quantity"] == "2"
    assert result["sales"][0]["remaining"] == "3"
    assert Decimal(
        replay([f], outcomes={"TEST-E-M": {"yes_payout": "1"}})["resolved_total"]
    ) == Decimal("2.97")


def test_fifo_pair_cannot_be_sold_again():
    a, b = fill(), fill("b", "no", "5", "0.50", 5)
    result = replay([a, b], [sample([a])])
    assert result["sales"] == []
    assert result["open_lots"] == {}
    assert Decimal(result["resolved_total"]) == Decimal("0.44")


def test_shared_depth_and_duplicate_fills_are_not_double_counted():
    a, b = fill(quantity="2"), fill("b", quantity="2")
    result = replay([a, a, b], [sample([a, b], [["0.55", "3"]])])
    assert sum(Decimal(x["quantity"]) for x in result["sales"]) == 3
    assert sum(Decimal(x["left"]) for x in result["open_lots"]["TEST-E-M"]) == 1
    with pytest.raises(EvidenceError):
        replay([a, dict(a, fee="0.04")])


def test_missing_and_late_quotes_do_not_create_exits():
    a = fill()
    invalid = sample([a], valid=False)
    assert replay([a], [invalid])["sales"] == []
    late = sample([a])
    late["at"] = (START + timedelta(minutes=12)).isoformat()
    result = replay([a], [late])
    assert result["sales"] == []
    assert result["invalid_comparison_markets"] == ["TEST-E-M"]


def test_remaining_actual_caps_exit_and_only_one_attempt():
    a = fill()
    first, later = sample([a], [["0.60", "5"]]), sample([a], [["0.65", "5"]], 30)
    first["lots"][0]["remaining_actual"] = "1"
    result = replay([a], [first, later])
    assert len(result["sales"]) == 1
    assert result["sales"][0]["quantity"] == "1"


def test_no_side_uses_no_book():
    a = fill(side="no", price="0.10")
    result = replay([a], [sample([a])])
    assert result["sales"][0]["levels"][0][0] == "0.30"


def test_all_own_quotes_are_removed_and_inconsistent_snapshot_rejected():
    raw = {"orderbook_fp": {"yes_dollars": [["0.50", "7"]], "no_dollars": []}}
    own = [dict(ticker="T", side="yes", price="0.50", quantity="5")]
    assert external_book(raw, "T", own)["yes"] == [["0.50", "2"]]
    own[0]["quantity"] = "8"
    with pytest.raises(EvidenceError):
        external_book(raw, "T", own)


def test_normalized_order_canonical_book_direction():
    row = dict(
        order_id="x",
        ticker="T",
        status="resting",
        book_side="ask",
        outcome_side="yes",
        yes_price_dollars="0.40",
        no_price_dollars="0.60",
        remaining_count_fp="1.25",
    )
    assert normalized_orders([row])[0]["side"] == "no"
    assert normalized_orders([row])[0]["quantity"] == "1.25"


def test_missing_entry_fee_fails_and_canonical_side_is_required():
    intent = dict(
        side="yes", price_cents=50, ticker="T", event_ticker="E", strategy_version="v3"
    )
    raw = dict(
        order_id="o",
        fill_id="f",
        ticker="T",
        outcome_side="yes",
        book_side="bid",
        count_fp="1.25",
        yes_price_dollars="0.40",
        no_price_dollars="0.60",
        created_time=START.isoformat(),
    )
    with pytest.raises(EvidenceError):
        normalize_fill(raw, intent)
    raw["fee_cost"] = "0.014"
    assert normalize_fill(raw, intent)["fee"] == "0.014"
    raw["book_side"] = "ask"
    with pytest.raises(EvidenceError):
        normalize_fill(raw, intent)


def test_slippage_is_applied_and_empty_depth_is_unfilled():
    sale = consume([["0.55", "2"]], "5", slippage=Decimal("0.02"))
    assert sale["proceeds"] == "1.06"
    assert consume([], "5")["quantity"] == "0"


def test_get_route_allowlist_rejects_funded_writes_and_foreign_hosts():
    client = ReadOnlyAPI.__new__(ReadOnlyAPI)
    for path in (
        "https://evil.test",
        "/portfolio/events/orders",
        "/portfolio/balance",
        "/markets/../portfolio/events/orders",
        "/markets?x=y",
    ):
        with pytest.raises(EvidenceError):
            client.get(path)
    assert not hasattr(client, "post")
    assert not hasattr(client, "cancel")


def test_pagination_refuses_missing_or_repeated_cursor():
    client = ReadOnlyAPI.__new__(ReadOnlyAPI)
    client.get = lambda *args: {"fills": [], "cursor": "repeat"}
    with pytest.raises(EvidenceError, match="repeated_cursor"):
        client.pages("/portfolio/fills", "fills")
    client.get = lambda *args: {}
    with pytest.raises(EvidenceError, match="missing_page_rows"):
        client.pages("/portfolio/fills", "fills")


def test_environment_is_parsed_without_shell_and_requires_prod(tmp_path):
    path = tmp_path / "env"
    path.write_text(
        'KALSHI_ENV=prod\nKALSHI_KEY_ID=id\nKALSHI_PRIVATE_KEY="$(false)"\n'
    )
    assert environment(path)["KALSHI_PRIVATE_KEY"] == "$(false)"
    path.write_text("KALSHI_ENV=demo\n")
    with pytest.raises(EvidenceError):
        environment(path)


def test_cohort_excludes_baseline_events_and_freezes_30_day_window():
    manifest = dict(
        start=START.isoformat(),
        end=(START + timedelta(days=30)).isoformat(),
        baseline_events=["OLD"],
    )
    intent = dict(
        strategy_version="spread-maker-v3-24h-starts",
        utc=START.isoformat(),
        event_ticker="NEW",
    )
    orders = {
        "a": intent,
        "b": dict(intent, event_ticker="OLD"),
        "c": dict(intent, utc=manifest["end"]),
        "d": dict(intent, strategy_version="v4"),
    }
    assert list(cohort(orders, manifest)) == ["a"]


def test_cron_is_idempotent_and_preserves_unrelated_jobs():
    original = "0 1 * * * unrelated\n"
    first = cron(original, "* * * * * observer")
    assert cron(first, "* * * * * observer") == first
    assert cron(first, None) == original


def test_private_store_restart_and_incomplete_report(tmp_path):
    path = tmp_path / "db"
    store = Store(path)
    a = fill()
    store.put("fill", "a", a)
    store.put("fill", "a", a)
    store.meta("manifest", {"protocol": "test", "start": START.isoformat()})
    reopened = Store(path)
    assert len(reopened.values("fill")) == 1
    assert path.stat().st_mode & 0o777 == 0o600
    value = report(reopened)
    assert value["matched_comparison_markets"] == []
    assert value["incomplete_markets"] == ["TEST-E-M"]
    assert value["checkpoint_coverage"] == {"valid": 0, "expected": 4}
    assert value["verdict"] == "collecting_evidence_no_automatic_strategy_change"


def test_settlement_prevents_post_settlement_activity():
    a = fill()
    with pytest.raises(EvidenceError, match="activity_after_settlement"):
        replay(
            [a],
            [sample([a])],
            {
                "TEST-E-M": {
                    "yes_payout": "1",
                    "at": (START + timedelta(minutes=5)).isoformat(),
                }
            },
        )


def test_independent_candidates_use_frozen_policy_and_unknown_starts():
    import runpy
    from pathlib import Path
    from research.spread_forward_candidates import candidate

    config = runpy.run_path(str(Path(__file__).parents[1] / "live/spread_policy.py"))
    row = dict(
        ticker="KXAHLGAME-E-M",
        event_ticker="KXAHLGAME-E",
        status="active",
        expected_expiration_time=(START + timedelta(hours=10)).isoformat(),
        yes_bid_dollars="0.40",
        yes_ask_dollars="0.60",
    )
    decision = candidate(row, "KXAHLGAME", config, {}, START)
    assert decision["eligible"]
    assert decision["yes_price_cents"] == 41
    assert decision["no_price_cents"] == 41
    assert (
        candidate(dict(row, yes_ask_dollars="0.45"), "KXAHLGAME", config, {}, START)[
            "reason"
        ]
        == "spread_too_narrow"
    )
    assert (
        candidate(
            dict(row, ticker="KXBOXING-E-M", event_ticker="KXBOXING-E"),
            "KXBOXING",
            config,
            {},
            START,
        )["reason"]
        == "event_start_unknown"
    )


def test_mismatched_settlement_revenue_blocks_comparison(tmp_path):
    store = Store(tmp_path / "db")
    store.put("fill", "a", fill())
    store.put(
        "account_snapshot",
        "s",
        {
            "settlements": [
                {
                    "ticker": "TEST-E-M",
                    "market_result": "yes",
                    "revenue_dollars": "3",
                    "settled_time": (START + timedelta(hours=2)).isoformat(),
                }
            ]
        },
    )
    result = report(store)
    assert result["invalid_markets"] == ["TEST-E-M"]
    assert result["matched_comparison_markets"] == []


def test_offline_start_and_restart_preserve_frozen_manifest(tmp_path, monkeypatch):
    import research.spread_forward_recorder as recorder

    at = recorder.now()
    home = tmp_path / "study"
    home.mkdir()
    store = Store(home / "evidence.sqlite3")
    store.meta("survey_success", at.isoformat())
    prior = dict(
        client_order_id="c",
        event="intent",
        ticker="OLD-E-M",
        event_ticker="OLD-E",
        side="yes",
        utc=(at - timedelta(days=1)).isoformat(),
        strategy_version=recorder.VERSION,
    )
    monkeypatch.setattr(
        recorder,
        "journal",
        lambda: [
            prior,
            {
                "event": "accepted",
                "order_id": "o",
                "client_order_id": "c",
            },
        ],
    )
    monkeypatch.setattr(recorder, "environment", lambda path: {})
    monkeypatch.setattr(recorder, "policy", lambda: {})
    monkeypatch.setattr(recorder.os, "nice", lambda n: None)

    class FakeAPI:
        def __init__(self, env):
            pass

        def pages(self, path, key, params=None):
            if path.endswith("/orders"):
                return [{"order_id": "o", "ticker": "OLD-E-M"}]
            if path.endswith("/fills"):
                return [{"order_id": "o", "fill_id": "old", "ticker": "OLD-E-M"}]
            return []

    class FakeThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def join(self, **kwargs):
            pass

    class FakeEvent:
        def wait(self, seconds):
            pass

        def set(self):
            pass

    monkeypatch.setattr(recorder, "ReadOnlyAPI", FakeAPI)
    monkeypatch.setattr(recorder.threading, "Thread", FakeThread)
    monkeypatch.setattr(recorder.threading, "Event", FakeEvent)
    write = recorder.write_json

    def finish(path, value):
        write(path, value)
        if path.name == "health.json":
            (home / "STOP").touch()

    monkeypatch.setattr(recorder, "write_json", finish)
    recorder.run(home)
    first = Store(home / "evidence.sqlite3").meta("manifest")
    assert recorder.status(home)["state"] == "recording"
    assert first["baseline_events"] == ["OLD-E"]
    assert (
        datetime.fromisoformat(first["end"]) - datetime.fromisoformat(first["start"])
    ).days == 30
    (home / "STOP").unlink()
    recorder.run(home)
    assert Store(home / "evidence.sqlite3").meta("manifest") == first
