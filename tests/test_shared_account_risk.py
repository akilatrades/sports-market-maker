"""Offline tests for explicit, opt-in cross-sport production risk checks."""

from datetime import UTC, datetime, timedelta

import pytest

from kalshi.trading import TradingError
from live import shared_account_risk as shared

NOW = datetime(2026, 10, 19, 22, 0, tzinfo=UTC)


def pair(sport, key, cost=2.0, utc=None):
    ticker = f"KX{sport.upper()}-TEST-{key}"
    cid = f"client-{sport}-{key}"
    return [
        {
            "event": "intent",
            "client_order_id": cid,
            "ticker": ticker,
            "utc": (utc or NOW).isoformat(),
            "cost": cost,
            "count": 4,
            "tip_utc": (NOW + timedelta(hours=4)).isoformat(),
        },
        {"event": "accepted", "client_order_id": cid, "order_id": f"order-{cid}"},
    ]


def both():
    return {"nfl": pair("nfl", "a"), "nba": pair("nba", "b")}


def test_two_cohort_orders_are_recognized_without_losing_ownership():
    owner = shared.ownership(both())
    actual = shared.classify(
        [
            {"order_id": "order-client-nfl-a", "ticker": "KXNFL-TEST-a"},
            {"order_id": "order-client-nba-b", "ticker": "KXNBA-TEST-b"},
        ],
        [
            {"market_ticker": "KXNFL-TEST-a", "position_fp": "-2"},
            {"market_ticker": "KXNBA-TEST-b", "position_fp": "-1"},
        ],
        owner,
    )
    assert len(actual["nfl"]["resting"]) == 1
    assert actual["nba"]["held"] == ["KXNBA-TEST-b"]


def test_unknown_open_order_and_unknown_position_fail_closed():
    owner = shared.ownership(both())
    with pytest.raises(TradingError, match="Unowned resting"):
        shared.classify([{"order_id": "manual-order"}], [], owner)
    with pytest.raises(TradingError, match="Unowned or wrong-side"):
        shared.classify([], [{"ticker": "MANUAL", "position_fp": "-1"}], owner)
    with pytest.raises(TradingError, match="Unowned or wrong-side"):
        shared.classify([], [{"ticker": "KXNFL-TEST-a", "position_fp": "1"}], owner)


def test_unknown_outcome_missing_acceptance_and_duplicate_id_block_all_trading():
    base = both()
    for events in [
        {"nfl": base["nfl"][:-1], "nba": base["nba"]},
        {
            "nfl": base["nfl"]
            + [{"event": "unknown_outcome", "client_order_id": "client-nfl-a"}],
            "nba": base["nba"],
        },
        {"nfl": base["nfl"] + base["nfl"], "nba": base["nba"]},
    ]:
        with pytest.raises(TradingError):
            shared.ownership(events)


def test_sports_share_one_combined_lifetime_daily_and_active_budget():
    events = both()
    owner = shared.ownership(events)
    active = {"client-nfl-a", "client-nba-b"}
    baseline = shared.room(owner, active, 3, NOW)
    assert all(baseline.values())
    assert shared.LIMITS == {"lifetime": 100.0, "daily": 40.0, "active": 25.0}
    expensive = {"nfl": [*pair("nfl", "a", 15.0)], "nba": pair("nba", "b", 11.0)}
    owner = shared.ownership(expensive)
    checks = shared.room(owner, active, 2, NOW)
    assert not checks["shared_active"]
    assert checks["shared_lifetime"]


def test_cumulative_spend_never_resets_when_an_order_settles():
    owner = shared.ownership(both())
    none_active = set()
    result = shared.room(owner, none_active, 3, NOW)
    assert result["shared_active"]
    # Even though no contracts are currently held, old submissions count.
    from live.nfl_policy import reserve

    assert sum(reserve(x["cost"]) for x in owner["attempts"]) == 4.4
    assert not shared.room(owner, none_active, 100, NOW)["shared_lifetime"]


def test_daily_risk_uses_new_york_rollover():
    old = NOW - timedelta(days=1)
    owner = shared.ownership(
        {
            "nfl": pair("nfl", "a", 23, utc=old),
            "nba": pair("nba", "b", 16),
        }
    )
    # The older trade remains in lifetime exposure even on a new date.
    assert shared.room(owner, set(), 10, NOW)["shared_daily"]
    assert not shared.room(owner, set(), 90, NOW)["shared_lifetime"]


def test_missing_private_journal_is_not_an_empty_cohort(monkeypatch, tmp_path):
    monkeypatch.setattr(shared, "ROOT", tmp_path)
    with pytest.raises(TradingError, match="Missing other-cohort"):
        shared.journal_events("nba")


def test_live_opt_in_requires_owner_marker(monkeypatch, tmp_path):
    from pathlib import Path

    original = Path.exists

    def patched_exists(self):
        if str(self) == "/etc/market-maker-shared-account.enabled":
            return False
        return original(self)

    monkeypatch.setattr(Path, "exists", patched_exists)
    assert not shared.dual_mode({})
    with pytest.raises(TradingError, match="Owner has not enabled"):
        shared.dual_mode({"SMM_DUAL_MARKET": "YES"})


def test_incomplete_or_corrupt_journal_halts(monkeypatch, tmp_path):
    monkeypatch.setattr(shared, "ROOT", tmp_path)
    path = tmp_path / "prod-nba-auto" / "journal.jsonl"
    path.parent.mkdir()
    path.write_text('{"event":"intent"')
    with pytest.raises(TradingError, match="Incomplete"):
        shared.journal_events("nba")
    path.write_text('{"event":"intent",\n')
    with pytest.raises(TradingError, match="Invalid production"):
        shared.journal_events("nba")


def test_full_signed_reconciliation_keeps_both_sports_active(monkeypatch, tmp_path):
    import json

    monkeypatch.setattr(shared, "ROOT", tmp_path)
    for sport, key in (("nfl", "a"), ("nba", "b")):
        directory = tmp_path / f"prod-{sport}-auto"
        directory.mkdir()
        (directory / "journal.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in pair(sport, key))
        )

    class Exchange:
        def orders(self, status):
            assert status == "resting"
            return [
                {"order_id": "order-client-nfl-a", "ticker": "KXNFL-TEST-a"},
                {"order_id": "order-client-nba-b", "ticker": "KXNBA-TEST-b"},
            ]

        def positions(self):
            return [
                {"market_ticker": "KXNFL-TEST-a", "position_fp": "-1"},
                {"market_ticker": "KXNBA-TEST-b", "position_fp": "-2"},
            ]

        def settlements(self):
            return []

        def fills(self, min_ts):
            assert min_ts < NOW.timestamp()
            return []

    for sport in ("nfl", "nba"):
        state, context = shared.state_for(Exchange(), sport, NOW)
        assert len(state["resting"]) == 1
        assert len(state["held"]) == 1
        assert len(context["active_client_ids"]) == 2
        assert shared.fits(context, 3, NOW)


def test_inconsistent_foreign_fill_on_our_market_halts(monkeypatch, tmp_path):
    import json

    monkeypatch.setattr(shared, "ROOT", tmp_path)
    for sport, key in (("nfl", "a"), ("nba", "b")):
        directory = tmp_path / f"prod-{sport}-auto"
        directory.mkdir()
        (directory / "journal.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in pair(sport, key))
        )

    class Exchange:
        def orders(self, status):
            return []

        def positions(self):
            return []

        def settlements(self):
            return []

        def fills(self, min_ts):
            return [{"ticker": "KXNFL-TEST-a", "order_id": "manual-fill"}]

    with pytest.raises(TradingError, match="Unowned fill"):
        shared.state_for(Exchange(), "nba", NOW)
