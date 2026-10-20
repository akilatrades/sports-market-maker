"""Safety tests for the separate, disabled-by-default NBA production worker."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from kalshi.trading import TradingError
from live import prod_nba_auto as nba
from live.nba_inputs import publish

NOW = datetime.now(timezone.utc)
ARMED = {
    "KALSHI_ENV": "prod",
    "TRADE_MODE": "live",
    "PROD_NBA_AUTO_ARM": "YES",
    "ALLOW_PRODUCTION_TRADING": "YES",
    "TRADE_MARKET": "nba",
}


def priced():
    return pd.DataFrame(
        [
            {
                "ticker": "KXNBAPTS-26OCT20LALGSW-LALSPLAYER-30",
                "game_id": 20261020,
                "player": "Test Player",
                "player_id": 1234,
                "team": "LAL",
                "stat": "points",
                "line": 29.5,
                "tip_utc": pd.Timestamp(NOW + timedelta(hours=4)),
                "hours_to_tip": 4.0,
                "p_model": 0.35,
                "p_book": 0.40,
                "book_n": 2,
                "injury_status": "",
                "team_espn": "LAL",
                "home_espn": "GS",
                "away_espn": "LAL",
                "requires_book": False,
                "last_player_team": "LAL",
                "last_player_game_utc": (NOW - timedelta(days=4)).isoformat(),
                "yes_bid_dollars": 0.40,
                "yes_ask_dollars": 0.50,
            }
        ]
    )


@pytest.fixture(autouse=True)
def current_context(monkeypatch):
    import markets.nba.live as source

    monkeypatch.setattr(source, "rosters", lambda teams: {"LAL": {1234}})
    monkeypatch.setattr(
        source,
        "scoreboard",
        lambda day, season: pd.DataFrame(
            [
                {
                    "game_id": 20261020,
                    "home": "GS",
                    "away": "LAL",
                    "completed": False,
                    "tip_utc": pd.Timestamp(NOW + timedelta(hours=4)),
                }
            ]
        ),
    )


def test_live_arm_is_distinct_from_nfl_and_requires_correct_venue():
    live = SimpleNamespace(env="prod", dry_run=False, can_sign=True)
    nba.guard(ARMED, live)
    for name in ARMED:
        env = ARMED.copy()
        del env[name]
        with pytest.raises(TradingError):
            nba.guard(env, live)
    with pytest.raises(TradingError):
        nba.guard({**ARMED, "TRADE_MARKET": "nfl"}, live)
    with pytest.raises(TradingError):
        nba.guard({**ARMED, "DEMO_PILOT": "1"}, live)
    with pytest.raises(TradingError):
        nba.guard(ARMED, SimpleNamespace(env="demo", dry_run=False, can_sign=True))


def test_nba_baseline_retains_no_side_and_passive_price():
    f = priced()
    rows = nba.select_candidates(f, [], {"active": []}, NOW)
    assert len(rows) == 1
    quote, edge, extra = nba.execution_quote(rows[0])
    assert extra == 1  # wide spread and sufficient after-fee edge
    assert quote == round(rows[0].price + 0.01, 2)
    assert edge == round(rows[0].edge - 0.01, 5)
    assert round(1 - quote, 2) > round(rows[0].yes_bid, 2)
    order, cost = nba.order_from_row(rows[0], NOW, no_price=quote)
    assert order.side == "no"
    assert order.post_only
    assert order.body()["side"] == "ask"
    assert 0 < cost <= nba.MAX_ORDER_COST


def test_separate_risk_caps_and_state():
    assert str(nba.STATE).endswith("prod-nba-auto")
    assert nba.MAX_GROSS_COST == 75
    assert nba.MAX_ACTIVE_COST == 20
    assert nba.MAX_ORDER_COST == 4
    assert nba.MAX_GAME_COST == 12
    assert nba.MAX_TEAM_COST == 8
    assert nba.MAX_DAILY_COST == 35
    assert nba.MAX_GAME_ORDERS == 4
    assert nba.MAX_CONTRACTS == 8
    assert nba.WINDOW == (2.0, 6.0)


def test_nba_clock_rejects_below_two_hours_at_submission():
    assert nba.pre_submit_kickoff_ok(NOW + timedelta(hours=4), NOW)
    assert not nba.pre_submit_kickoff_ok(NOW + timedelta(hours=2), NOW)
    assert not nba.pre_submit_kickoff_ok(NOW + timedelta(hours=2, seconds=20), NOW)


def test_missing_projection_or_meta_blocks_new_orders(tmp_path):
    f = tmp_path / "latest.csv"
    assert nba.nba_candidates(NOW, latest=f).empty
    priced().to_csv(f, index=False)
    assert nba.nba_candidates(NOW, latest=f).empty


def test_explicit_fresh_meta_and_current_injury_report_required(tmp_path, monkeypatch):
    latest = tmp_path / "latest.csv"
    priced().to_csv(latest, index=False)
    publish(priced(), tmp_path, NOW)
    import live.nba_trade as trader
    import markets.nba.live as live
    import kalshi.books as books

    monkeypatch.setattr(trader, "refresh_quotes", lambda f, now: f.copy())
    monkeypatch.setattr(books, "attach_latest", lambda f: f.copy())
    monkeypatch.setattr(
        live,
        "injuries",
        lambda: pd.DataFrame(columns=["player_id", "team", "updated", "out"]),
    )
    result = nba.nba_candidates(NOW, latest=latest)
    assert len(result) == 1
    assert result.injury_status.iloc[0] == ""

    def unavailable():
        raise OSError("ESPN unavailable")

    monkeypatch.setattr(live, "injuries", unavailable)
    assert nba.nba_candidates(NOW, latest=latest).empty


def test_new_injury_since_projection_vetoes_candidate(tmp_path, monkeypatch):
    latest = tmp_path / "latest.csv"
    priced().to_csv(latest, index=False)
    publish(priced(), tmp_path, NOW - timedelta(hours=1))
    import live.nba_trade as trader
    import markets.nba.live as live
    import kalshi.books as books

    monkeypatch.setattr(trader, "refresh_quotes", lambda f, now: f.copy())
    monkeypatch.setattr(books, "attach_latest", lambda f: f.copy())
    monkeypatch.setattr(
        live,
        "injuries",
        lambda: pd.DataFrame(
            [
                {
                    "player_id": 1234,
                    "team": "LAL",
                    "updated": NOW.isoformat(),
                    "out": True,
                }
            ]
        ),
    )
    out = nba.nba_candidates(NOW, latest=latest)
    assert len(out) == 1
    assert out.injury_status.iloc[0] == "TEAM_INJURY_CHANGE"
    assert nba.select_candidates(out, [], {"active": []}, NOW) == []


def test_expired_and_outlier_model_timestamp_blocks(tmp_path, monkeypatch):
    latest = tmp_path / "latest.csv"
    priced().to_csv(latest, index=False)
    meta = tmp_path / "latest_meta.json"
    meta.write_text(
        json.dumps({"generated_utc": (NOW - timedelta(hours=11)).isoformat()})
    )
    assert nba.nba_candidates(NOW, latest=latest).empty
    meta.write_text(
        json.dumps({"generated_utc": (NOW + timedelta(hours=1)).isoformat()})
    )
    assert nba.nba_candidates(NOW, latest=latest).empty


def test_shared_account_rejects_active_nfl_timer_or_service(monkeypatch):
    import subprocess

    def active(args, **kwargs):
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", active)
    with pytest.raises(TradingError, match="NFL production still active"):
        nba.assert_nfl_production_stopped()


def test_shared_account_allows_only_known_inactive_states(monkeypatch):
    import subprocess

    def inactive(args, **kwargs):
        return SimpleNamespace(returncode=3)

    monkeypatch.setattr(subprocess, "run", inactive)
    nba.assert_nfl_production_stopped()

    def unverified(args, **kwargs):
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(subprocess, "run", unverified)
    with pytest.raises(TradingError, match="Uncertain"):
        nba.assert_nfl_production_stopped()


def test_selection_funnel_counts_each_gate_without_loosening_it():
    """Zero submitted orders must have an actionable, staged explanation."""
    f = priced()
    stats = {}
    rows = nba.select_candidates(f, [], {"active": []}, NOW, diagnostics=stats)
    assert len(rows) == 1
    assert stats == {
        "open_markets": 1,
        "verified_availability_and_tip": 1,
        "in_entry_window": 1,
        "supported_prop_series": 1,
        "passed_book_model_and_spread": 1,
        "no_side_candidates": 1,
        "passed_edge_sanity": 1,
        "not_previously_attempted": 1,
    }
    f.loc[0, "hours_to_tip"] = 1.5
    stats = {}
    assert nba.select_candidates(f, [], {"active": []}, NOW, diagnostics=stats) == []
    assert stats["in_entry_window"] == 0
    assert stats["open_markets"] == 1
    f.loc[0, "hours_to_tip"] = 4.0
    f.loc[0, "injury_status"] = "UNVERIFIED_CURRENT_ROSTER_OR_GAME"
    stats = {}
    assert nba.select_candidates(f, [], {"active": []}, NOW, diagnostics=stats) == []
    assert stats["verified_availability_and_tip"] == 0


def test_dry_scan_cannot_overwrite_production_scan_status(tmp_path):
    """Health telemetry must not be faked by a research/dry scan."""
    journal = tmp_path / "journal.jsonl"
    report = tmp_path / "last_scan.json"
    report.write_text('{"decision":"exchange_accepted","mode":"live"}')
    assert not nba.pass_once(None, {}, pd.DataFrame(), NOW, journal, dry=True)
    assert json.loads(report.read_text()) == {
        "decision": "exchange_accepted",
        "mode": "live",
    }
    assert not journal.exists()


def test_extended_order_expiration_never_exceeds_existing_pretip_cutoff():
    from kalshi.trading import Order

    for h in (2.5, 4.0, 6.0):
        f = priced()
        f.loc[0, "tip_utc"] = pd.Timestamp(NOW + timedelta(hours=h))
        f.loc[0, "hours_to_tip"] = h
        rows = nba.select_candidates(f, [], {"active": []}, NOW)
        assert len(rows) == 1
        order, _ = nba.order_from_row(rows[0], NOW)
        expected = int((NOW + timedelta(hours=h)).timestamp()) - 7200
        assert order.expiration_ts == expected
        assert order.expiration_ts > int(NOW.timestamp())
        assert order.expiration_ts - int(NOW.timestamp()) > 0
        assert order.expiration_ts - int(NOW.timestamp()) <= 4 * 3600
        assert (
            Order(
                **{
                    "ticker": order.ticker,
                    "side": order.side,
                    "count": order.count,
                    "price_cents": order.price_cents,
                    "expiration_ts": order.expiration_ts,
                }
            ).body()["expiration_time"]
            == expected
        )


def test_resting_quote_retains_order_while_edge_remains_valid():
    row = priced().iloc[0]
    intent = {
        "ticker": row.ticker,
        "price_cents": 51,
        "count": 2,
        "probability_source": "sportsbook",
    }
    market = {"status": "active", "yes_bid_dollars": 0.40, "yes_ask_dollars": 0.50}
    assert nba.resting_cancel_reason(row, intent, market, 0.0) is None


@pytest.mark.parametrize(
    "change, expected",
    [
        ({"injury_status": "NEW_INJURY_NEWS"}, "unverified_roster_injury_or_model"),
        ({"hours_to_tip": 1.9}, "outside_verified_pretip_window"),
        ({"book_n": 1}, "fresh_two_book_consensus_missing"),
        ({"p_book": 0.51}, "current_net_edge_below_minimum"),
        ({"p_book": float("nan"), "book_n": 0}, "fresh_two_book_consensus_missing"),
        ({"requires_book": "unknown"}, "unverified_book_requirement"),
    ],
)
def test_resting_order_is_canceled_when_signal_decays(change, expected):
    row = priced().iloc[0].copy()
    for key, val in change.items():
        row[key] = val
    intent = {
        "ticker": row.ticker,
        "price_cents": 51,
        "count": 2,
        "probability_source": "sportsbook",
    }
    market = {"status": "active", "yes_bid_dollars": 0.40, "yes_ask_dollars": 0.50}
    assert nba.resting_cancel_reason(row, intent, market, 0.0) == expected


def test_resting_market_or_fee_change_forces_cancel():
    row = priced().iloc[0]
    intent = {
        "ticker": row.ticker,
        "price_cents": 51,
        "count": 2,
        "probability_source": "sportsbook",
    }
    market = {"status": "active", "yes_bid_dollars": 0.40, "yes_ask_dollars": 0.50}
    assert (
        nba.resting_cancel_reason(
            row, intent, {**market, "yes_bid_dollars": 0.50, "yes_ask_dollars": 0.55}, 0
        )
        == "resting_quote_no_longer_passive"
    )
    assert (
        nba.resting_cancel_reason(row, intent, {**market, "status": "closed"}, 0)
        == "market_not_active"
    )
    assert (
        nba.resting_cancel_reason(row, intent, market, 0.50)
        == "fee_exceeds_original_reservation"
    )


def test_resting_recheck_cancels_only_bad_order_and_journals_reason(
    tmp_path, monkeypatch
):
    from kalshi import fees

    row = priced().iloc[0]
    ticker = str(row.ticker)
    row = row.copy()
    row["p_book"] = 0.52  # negative after-fee remaining edge
    events = [
        {
            "event": "intent",
            "client_order_id": "cid",
            "ticker": ticker,
            "price_cents": 51,
            "count": 2,
            "probability_source": "sportsbook",
        },
        {"event": "accepted", "client_order_id": "cid", "order_id": "oid"},
    ]

    class Client:
        calls = []

        def cancel(self, order_id, ticker=None):
            self.calls.append((order_id, ticker))

    monkeypatch.setattr(
        nba,
        "fetch_market",
        lambda ticker: {
            "status": "active",
            "yes_bid_dollars": 0.40,
            "yes_ask_dollars": 0.50,
        },
    )
    monkeypatch.setattr(fees, "live_maker_fee_bound", lambda *args: (0.0, {}))
    client = Client()
    journal = tmp_path / "journal.jsonl"
    count = nba.cancel_invalid_resting(
        client,
        journal,
        {"resting": [{"order_id": "oid", "ticker": ticker}]},
        pd.DataFrame([row]),
        NOW,
        events,
    )
    assert count == 1
    assert client.calls == [("oid", ticker)]
    saved = [json.loads(line) for line in journal.read_text().splitlines()]
    assert [r["event"] for r in saved] == ["cancel_intent", "cancel_accepted"]
    assert saved[0]["reason"] == "current_net_edge_below_minimum"


def test_resting_recheck_does_not_place_on_unverified_order(tmp_path, monkeypatch):
    from kalshi import fees

    row = priced().iloc[0]
    ticker = str(row.ticker)
    monkeypatch.setattr(
        nba,
        "fetch_market",
        lambda ticker: {
            "status": "active",
            "yes_bid_dollars": 0.40,
            "yes_ask_dollars": 0.50,
        },
    )
    monkeypatch.setattr(fees, "live_maker_fee_bound", lambda *args: (0.0, {}))
    with pytest.raises(TradingError, match="reconcile"):
        nba.cancel_invalid_resting(
            SimpleNamespace(),
            tmp_path / "journal.jsonl",
            {"resting": [{"order_id": "unrecognized", "ticker": ticker}]},
            priced(),
            NOW,
            [],
        )


def test_unavailable_live_resting_quote_halts_until_exchange_expiry(
    tmp_path, monkeypatch
):
    from kalshi import fees

    row = priced().iloc[0]
    ticker = str(row.ticker)
    events = [
        {
            "event": "intent",
            "client_order_id": "cid",
            "ticker": ticker,
            "price_cents": 51,
            "count": 2,
            "probability_source": "sportsbook",
        },
        {"event": "accepted", "client_order_id": "cid", "order_id": "oid"},
    ]

    def bad_quote(ticker):
        raise OSError("network failure")

    monkeypatch.setattr(nba, "fetch_market", bad_quote)
    monkeypatch.setattr(fees, "live_maker_fee_bound", lambda *args: (0.0, {}))
    with pytest.raises(TradingError, match="HALT new placements"):
        nba.cancel_invalid_resting(
            SimpleNamespace(),
            tmp_path / "journal.jsonl",
            {"resting": [{"order_id": "oid", "ticker": ticker}]},
            priced(),
            NOW,
            events,
        )


def _past_attempt(n, game, team, cost):
    return {
        "client_order_id": "test-client-" + str(n),
        "game_id": str(game),
        "team": team,
        "cost": cost,
        "utc": NOW.isoformat(),
    }


def test_more_distinct_orders_can_fit_without_bypassing_order_limits():
    row = SimpleNamespace(game_id=20261020, team="LAL")
    old_attempts = [
        _past_attempt(1, 20261020, "LAL", 2),
        _past_attempt(2, 20261020, "LAL", 2),
    ]
    assert nba.room_for(old_attempts, [], row, 1.0, NOW)
    assert not nba.budget_blockers(old_attempts, [], row, 1.0, NOW)
    assert nba.reserve(4.0) <= nba.MAX_ACTIVE_COST
    assert nba.MAX_ACTIVE_COST <= 25.0  # shared cross-sport active cap
    assert nba.MAX_DAILY_COST <= 40.0  # shared daily cap
    assert nba.MAX_GROSS_COST <= 100.0  # shared lifetime cap


def test_game_and_team_budget_reasons_are_distinct():
    row = SimpleNamespace(game_id=20261020, team="LAL")
    team_filled = [_past_attempt(i, 20261020, "LAL", 2.5) for i in range(3)]
    reasons = nba.budget_blockers(team_filled, [], row, 1.0, NOW)
    assert "nba_per_team_submissions" in reasons
    assert "nba_per_game_submissions" not in reasons
    assert "nba_game_order_count" not in reasons

    game_filled = [_past_attempt(i, 20261020, "OTHER" + str(i), 3.0) for i in range(3)]
    reasons = nba.budget_blockers(game_filled, [], row, 2.0, NOW)
    assert "nba_per_game_submissions" in reasons
    assert "nba_per_team_submissions" not in reasons


def test_order_count_and_remaining_submission_allowance_still_bind():
    row = SimpleNamespace(game_id=20261020, team="LAL")
    past = [
        _past_attempt(i, 20261020, "OTHER" + str(i), 1.0)
        for i in range(nba.MAX_GAME_ORDERS)
    ]
    reasons = nba.budget_blockers(past, [], row, 0.5, NOW)
    assert "nba_game_order_count" in reasons
    assert "nba_per_game_submissions" not in reasons

    many_games = [_past_attempt(i, i + 100, "OTHER" + str(i), 4.0) for i in range(20)]
    for a in many_games:
        a["utc"] = (NOW - timedelta(days=7)).isoformat()
    reasons = nba.budget_blockers(many_games, [], row, 0.5, NOW)
    assert "nba_lifetime_submissions" in reasons
    assert "nba_daily_submissions" not in reasons


def test_active_and_shared_risk_limits_cannot_be_overridden():
    row = SimpleNamespace(game_id=20261020, team="LAL")
    active = [_past_attempt(i, i + 100, "OTHER" + str(i), 3.5) for i in range(5)]
    reasons = nba.budget_blockers(active, active, row, 2.0, NOW)
    assert "nba_active_exposure" in reasons

    import live.shared_account_risk as shared_risk

    # These caps remain independent, even when the NBA cohort enlarges.
    assert shared_risk.LIMITS == {"lifetime": 100, "daily": 40, "active": 25}


def test_v3_guard_drains_known_v2_and_rejects_unowned_resting_orders():
    old = {
        "client_order_id": "old",
        "ticker": "KXNBA-V2",
        "strategy_version": "nba-no-v2-opening-audit",
    }
    new = {
        "client_order_id": "new",
        "ticker": "KXNBA-V3",
        "strategy_version": nba.STRATEGY_VERSION,
    }
    accepted = {
        "old": {"order_id": "order-v2"},
        "new": {"order_id": "order-v3"},
    }
    assert (
        nba.legacy_resting_count(
            [old, new], accepted, [{"order_id": "order-v2", "ticker": "KXNBA-V2"}]
        )
        == 1
    )
    assert (
        nba.legacy_resting_count(
            [old, new], accepted, [{"order_id": "order-v3", "ticker": "KXNBA-V3"}]
        )
        == 0
    )
    assert nba.legacy_resting_count([old, new], accepted, []) == 0
    for order in (
        {"order_id": "unknown", "ticker": "KXNBA-V2"},
        {"order_id": "order-v2", "ticker": "WRONG"},
        {"order_id": "", "ticker": "KXNBA-V2"},
    ):
        with pytest.raises(TradingError, match="HALT"):
            nba.legacy_resting_count([old, new], accepted, [order])
    unknown = {**old, "strategy_version": "unknown"}
    with pytest.raises(TradingError, match="HALT"):
        nba.legacy_resting_count(
            [unknown, new], accepted, [{"order_id": "order-v2", "ticker": "KXNBA-V2"}]
        )


def test_v3_scan_records_fills_and_waits_for_v2_expiry_without_trading(
    tmp_path, monkeypatch
):
    import live.shared_account_risk as shared_risk

    attempt = {
        "client_order_id": "cid-v2",
        "ticker": "KXNBA-V2",
        "cost": 1.4,
        "utc": NOW.isoformat(),
        "strategy_version": "nba-no-v2-opening-audit",
    }
    accepted = {"cid-v2": {"order_id": "order-v2"}}
    state = {
        "resting": [{"order_id": "order-v2", "ticker": "KXNBA-V2"}],
        "settled": set(),
        "settlements": [],
        "held": [],
        "active": [],
    }

    class Client:
        env, dry_run, can_sign = "prod", False, True

        def fills(self, **kwargs):
            return []

        def balance(self):
            return {"balance": 100}

        def place(self, order):
            raise AssertionError("v3 must not post while v2 rests")

        def cancel(self, order_id, ticker=None):
            raise AssertionError("v3 must not cancel a v2 order")

    monkeypatch.setattr(nba, "guard", lambda *args: None)
    monkeypatch.setattr(shared_risk, "dual_mode", lambda env: False)
    monkeypatch.setattr(nba, "load_journal", lambda journal: [])
    monkeypatch.setattr(nba, "records", lambda events: ([attempt], accepted))
    monkeypatch.setattr(nba, "current_production_state", lambda *args: state)
    monkeypatch.setattr(nba, "reconcile_expired_unfilled", lambda *args: ([], 0))
    monkeypatch.setattr(nba, "record_execution", lambda *args: None)
    monkeypatch.setattr(nba, "record_queue_observation", lambda *args: None)
    monkeypatch.setattr(nba, "record_markouts", lambda *args: None)

    def forbid_cancel(*args):
        raise AssertionError("No v2 cancellation allowed")

    monkeypatch.setattr(nba, "cancel_invalid_resting", forbid_cancel)

    journal = tmp_path / "journal.jsonl"
    assert not nba.pass_once(Client(), ARMED, pd.DataFrame(), NOW, journal)
    status = json.loads((tmp_path / "last_scan.json").read_text())
    assert status["strategy_version"] == nba.STRATEGY_VERSION
    assert status["decision"] == "waiting_for_legacy_v2_orders"
    assert status["legacy_v2_resting_orders"] == 1
    assert status["placed"] is False


def test_more_competitive_maker_quote_never_spends_last_3c_edge():
    good = SimpleNamespace(price=0.51, edge=0.08, yes_bid=0.40, yes_ask=0.50)
    price, edge, extra = nba.execution_quote(good)
    assert (price, edge, extra) == (0.52, 0.07, 1)
    narrow = SimpleNamespace(price=0.51, edge=0.08, yes_bid=0.48, yes_ask=0.50)
    assert nba.execution_quote(narrow)[2] == 0
    low_edge = SimpleNamespace(price=0.51, edge=0.035, yes_bid=0.40, yes_ask=0.50)
    assert nba.execution_quote(low_edge)[2] == 0
    would_cross = SimpleNamespace(price=0.51, edge=0.08, yes_bid=0.48, yes_ask=0.55)
    assert nba.execution_quote(would_cross)[2] == 0


def test_resting_edge_rule_does_not_cancel_accepted_positive_edge():
    row = priced().iloc[0].copy()
    row["p_book"] = 0.48  # positive 1 cent edge after a 51c NO quote
    intent = {
        "ticker": row.ticker,
        "price_cents": 51,
        "count": 2,
        "probability_source": "sportsbook",
    }
    market = {"status": "active", "yes_bid_dollars": 0.40, "yes_ask_dollars": 0.50}
    assert nba.RESTING_MIN_NET_EDGE == 0.0
    assert nba.resting_cancel_reason(row, intent, market, 0.0) is None


def test_explicit_minutes_restriction_blocks_player_even_with_old_news(
    tmp_path, monkeypatch
):
    import kalshi.books as books
    import live.nba_trade as trader
    import markets.nba.live as live

    monkeypatch.setattr(trader, "refresh_quotes", lambda f, now: f.copy())
    monkeypatch.setattr(books, "attach_latest", lambda f: f.copy())
    snapshot = priced()
    snapshot["historical_minutes_baseline"] = 33.0
    publish(snapshot, tmp_path, NOW - timedelta(hours=1))
    monkeypatch.setattr(
        live,
        "injuries",
        lambda: pd.DataFrame(
            [
                {
                    "player_id": 1234,
                    "team": "LAL",
                    "updated": (NOW - timedelta(hours=2)).isoformat(),
                    "out": False,
                    "comment": "Expected to play limited minutes tonight",
                }
            ]
        ),
    )
    out = nba.nba_candidates(NOW, latest=tmp_path / "latest.csv")
    assert out.injury_status.iloc[0] == "REPORTED_MINUTES_RESTRICTION"
    assert out.attrs["diagnostics"]["historical_minutes_available"] == 1
    assert nba.select_candidates(out, [], {"active": []}, NOW) == []


def test_invalid_reported_historical_minutes_fail_closed(tmp_path, monkeypatch):
    import kalshi.books as books
    import live.nba_trade as trader
    import markets.nba.live as live

    monkeypatch.setattr(trader, "refresh_quotes", lambda f, now: f.copy())
    monkeypatch.setattr(books, "attach_latest", lambda f: f.copy())
    monkeypatch.setattr(
        live,
        "injuries",
        lambda: pd.DataFrame(columns=["player_id", "team", "updated", "out"]),
    )
    frame = priced()
    frame["historical_minutes_baseline"] = 84.0
    publish(frame, tmp_path, NOW)
    out = nba.nba_candidates(NOW, latest=tmp_path / "latest.csv")
    assert out.injury_status.iloc[0] == "UNVERIFIED_HISTORICAL_MINUTES"


def test_late_window_candidates_are_shadow_only_even_if_they_qualify(tmp_path):
    row = priced()
    row.loc[0, "tip_utc"] = pd.Timestamp(NOW + timedelta(hours=1))
    row.loc[0, "hours_to_tip"] = 1.0

    # Regular production window stays at 2-6 hours. The research cohort
    # observes but can NEVER feed the production POST loop.
    assert nba.select_candidates(row, [], {"active": []}, NOW) == []
    study = nba.select_candidates(row, [], {"active": []}, NOW, window=(0.5, 2.0))
    assert len(study) == 1

    class NoTradingClient:
        def place(self, *_):
            raise AssertionError("Shadow data placed a funded NBA trade")

    assert not nba.pass_once(
        NoTradingClient(), {}, row, NOW, tmp_path / "journal.jsonl", dry=True
    )
    assert not (tmp_path / "last_scan.json").exists()


def test_single_sportsbook_cannot_be_used_as_consensus_at_entry(
    tmp_path, monkeypatch
):
    import kalshi.books as books
    import live.nba_trade as trader
    import markets.nba.live as live

    monkeypatch.setattr(trader, "refresh_quotes", lambda f, now: f.copy())
    monkeypatch.setattr(books, "attach_latest", lambda f: f.copy())
    monkeypatch.setattr(
        live,
        "injuries",
        lambda: pd.DataFrame(columns=["player_id", "team", "updated", "out"]),
    )
    frame = priced()
    frame["book_n"] = 1
    publish(frame, tmp_path, NOW)
    out = nba.nba_candidates(NOW, latest=tmp_path / "latest.csv")
    assert len(out) == 1
    assert pd.isna(out.p_book.iloc[0])
    assert out.injury_status.iloc[0] == ""
    # In-season market may use the independently modeled probability.
    assert len(nba.select_candidates(out, [], {"active": []}, NOW)) == 1

    frame["requires_book"] = True
    publish(frame, tmp_path, NOW)
    out = nba.nba_candidates(NOW, latest=tmp_path / "latest.csv")
    assert out.injury_status.iloc[0] == "SEASON_OR_ROLE_CHANGE_NEEDS_TWO_BOOKS"
    assert nba.select_candidates(out, [], {"active": []}, NOW) == []


def test_probable_teammate_update_does_not_block_whole_team(
    tmp_path, monkeypatch
):
    import kalshi.books as books
    import live.nba_trade as trader
    import markets.nba.live as live

    monkeypatch.setattr(trader, "refresh_quotes", lambda f, now: f.copy())
    monkeypatch.setattr(books, "attach_latest", lambda f: f.copy())
    monkeypatch.setattr(
        live,
        "injuries",
        lambda: pd.DataFrame(
            [
                {
                    "player_id": 999,
                    "team": "LAL",
                    "updated": NOW.isoformat(),
                    "out": False,
                    "status": "probable",
                    "comment": "Minor ankle soreness, probable",
                }
            ]
        ),
    )
    publish(priced(), tmp_path, NOW - timedelta(hours=1))
    out = nba.nba_candidates(NOW, latest=tmp_path / "latest.csv")
    assert out.injury_status.iloc[0] == ""
    assert len(nba.select_candidates(out, [], {"active": []}, NOW)) == 1


def test_questionable_teammate_update_blocks_changed_team(
    tmp_path, monkeypatch
):
    import kalshi.books as books
    import live.nba_trade as trader
    import markets.nba.live as live

    monkeypatch.setattr(trader, "refresh_quotes", lambda f, now: f.copy())
    monkeypatch.setattr(books, "attach_latest", lambda f: f.copy())
    monkeypatch.setattr(
        live,
        "injuries",
        lambda: pd.DataFrame(
            [
                {
                    "player_id": 999,
                    "team": "LAL",
                    "updated": NOW.isoformat(),
                    "out": False,
                    "status": "questionable",
                    "comment": "Game-time decision",
                }
            ]
        ),
    )
    publish(priced(), tmp_path, NOW - timedelta(hours=1))
    out = nba.nba_candidates(NOW, latest=tmp_path / "latest.csv")
    assert out.injury_status.iloc[0] == "TEAM_INJURY_CHANGE"
