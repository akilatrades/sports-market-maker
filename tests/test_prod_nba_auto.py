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
                "p_book": 0.43,
                "book_n": 2,
                "book_updated_utc": NOW.isoformat(),
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
    assert extra == 0  # historical baseline one-tick improvement, no extra tick
    assert quote == rows[0].price
    assert edge == rows[0].edge
    assert round(1 - quote, 2) > round(rows[0].yes_bid, 2)
    order, cost = nba.order_from_row(rows[0], NOW, no_price=quote)
    assert order.side == "no"
    assert order.post_only
    assert order.body()["side"] == "ask"
    assert 0 < cost <= nba.MAX_ORDER_COST
    # v7: one contract an order (v6: three).
    assert order.count == nba.MAX_CONTRACTS == 1
    assert cost == pytest.approx(round(quote, 2))


def test_separate_risk_caps_and_state():
    assert str(nba.STATE).endswith("prod-nba-auto")
    # RESEARCH_LOG.md, 2026-10-23, "NBA rules v6" (v5: 1 contract, $25 a
    # game, $2,000 lifetime, -$60 total), then 2026-10-30, "NBA rules v7"
    # (v6: 3 contracts, two books or the model, 15c edges, 120/75-minute
    # book ages). Change only through a new amendment.
    assert nba.STRATEGY_VERSION == "nba-no-v7-book-priced"
    assert {
        "nba-no-v5-one-contract-breadth",
        "nba-no-v6-three-contracts",
    } <= nba.PRIOR_VERSIONS
    assert (nba.MIN_BOOKS, nba.BOOK_MAX_AGE_MINUTES) == (1, 60)
    assert (nba.MAX_ENTRY_NET_EDGE, nba.MODEL_VETO_MIN_EDGE) == (0.08, 0.0)
    assert nba.TRANSLATE_NEARBY_LINES is True
    assert nba.MAX_GROSS_COST == 5000
    assert nba.MAX_ACTIVE_COST == 150
    assert nba.MAX_ORDER_COST == 4
    assert nba.MAX_GAME_COST == 50
    assert nba.MAX_TEAM_COST == 25
    assert nba.MAX_DAILY_COST == 150
    assert nba.MAX_GAME_ORDERS == 40
    assert nba.MAX_CONTRACTS == 1
    assert nba.MAX_NEW_ORDERS_PER_PASS == 3
    assert nba.PRICE_BAND_CENTS == (5, 95)
    assert nba.MAX_REALIZED_DAILY_LOSS == 20
    assert nba.MAX_REALIZED_CUMULATIVE_LOSS == 100
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
        "book_priced": 1,
        "passed_model_veto": 1,
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


def test_existing_nba_orders_rest_to_verified_tip_not_two_hours_early():
    from kalshi.trading import Order

    for h in (2.5, 4.0, 6.0):
        f = priced()
        f.loc[0, "tip_utc"] = pd.Timestamp(NOW + timedelta(hours=h))
        f.loc[0, "hours_to_tip"] = h
        rows = nba.select_candidates(f, [], {"active": []}, NOW)
        assert len(rows) == 1
        order, _ = nba.order_from_row(rows[0], NOW)
        expected = int((NOW + timedelta(hours=h)).timestamp())
        assert order.expiration_ts == expected
        assert order.expiration_ts > int(NOW.timestamp())
        assert order.expiration_ts - int(NOW.timestamp()) > 0
        assert order.expiration_ts - int(NOW.timestamp()) <= 6 * 3600
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
        "count": 1,
        "probability_source": "sportsbook",
    }
    market = {"status": "active", "yes_bid_dollars": 0.40, "yes_ask_dollars": 0.50}
    assert nba.resting_cancel_reason(row, intent, market, 0.0) is None


@pytest.mark.parametrize(
    "change, expected",
    [
        ({"injury_status": "NEW_INJURY_NEWS"}, "unverified_roster_injury_or_model"),
        ({"hours_to_tip": -0.01}, "outside_verified_pretip_window"),
        ({"book_n": 1}, None),  # v7: one fresh book prices a line
        (
            {"book_n": 1, "requires_book": True},
            "fresh_two_book_consensus_missing",
        ),
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
        "count": 1,
        "probability_source": "sportsbook",
    }
    market = {"status": "active", "yes_bid_dollars": 0.40, "yes_ask_dollars": 0.50}
    assert nba.resting_cancel_reason(row, intent, market, 0.0) == expected


def test_resting_market_or_fee_change_forces_cancel():
    row = priced().iloc[0]
    intent = {
        "ticker": row.ticker,
        "price_cents": 51,
        "count": 1,
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
            "count": 1,
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
            "count": 1,
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
    import live.nfl_policy as nfl
    import live.shared_account_risk as shared_risk

    assert nba.reserve(4.0) <= nba.MAX_ACTIVE_COST
    # The shared caps hold both sports' own caps; neither can exceed them.
    limits = shared_risk.LIMITS
    assert nba.MAX_ACTIVE_COST + nfl.MAX_ACTIVE_COST <= limits["active"]
    assert nba.MAX_DAILY_COST + nfl.MAX_DAILY_COST <= limits["daily"]
    assert nba.MAX_GROSS_COST + nfl.MAX_GROSS_COST <= limits["lifetime"]


def test_game_and_team_budget_reasons_are_distinct():
    row = SimpleNamespace(game_id=20261020, team="LAL")
    # Same team, other games today: only the per-team cap binds.
    team_filled = [_past_attempt(i, 20261021 + i, "LAL", 6.0) for i in range(4)]
    reasons = nba.budget_blockers(team_filled, [], row, 1.0, NOW)
    assert "nba_per_team_submissions" in reasons
    assert "nba_per_game_submissions" not in reasons
    assert "nba_game_order_count" not in reasons

    # Just under the per-game cap, so a $2 order no longer fits it.
    n = int(nba.MAX_GAME_COST // nba.reserve(5.5))
    game_filled = [_past_attempt(i, 20261020, "OTHER" + str(i), 5.5) for i in range(n)]
    reasons = nba.budget_blockers(game_filled, [], row, 2.0, NOW)
    assert "nba_per_game_submissions" in reasons
    assert "nba_per_team_submissions" not in reasons


def test_order_count_and_remaining_submission_allowance_still_bind():
    row = SimpleNamespace(game_id=20261020, team="LAL")
    past = [
        _past_attempt(i, 20261020, "OTHER" + str(i), 0.5)
        for i in range(nba.MAX_GAME_ORDERS)
    ]
    reasons = nba.budget_blockers(past, [], row, 0.5, NOW)
    assert "nba_game_order_count" in reasons
    assert "nba_per_game_submissions" not in reasons

    n = int(nba.MAX_GROSS_COST // nba.reserve(4.0)) + 1  # just past the allowance
    many_games = [_past_attempt(i, i + 100, "OTHER" + str(i), 4.0) for i in range(n)]
    for a in many_games:
        a["utc"] = (NOW - timedelta(days=7)).isoformat()
    reasons = nba.budget_blockers(many_games, [], row, 0.5, NOW)
    assert "nba_lifetime_submissions" in reasons
    assert "nba_daily_submissions" not in reasons


def test_active_and_shared_risk_limits_cannot_be_overridden():
    row = SimpleNamespace(game_id=20261020, team="LAL")
    active = [_past_attempt(i, i + 100, "OTHER" + str(i), 3.5) for i in range(40)]
    reasons = nba.budget_blockers(active, active, row, 2.0, NOW)
    assert "nba_active_exposure" in reasons

    import live.shared_account_risk as shared_risk

    # These caps remain independent, even when the NBA cohort enlarges.
    assert shared_risk.LIMITS == {"lifetime": 5050, "daily": 180, "active": 165}


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
    monkeypatch.setattr(
        nba, "reconcile_expired_unfilled", lambda *args, **kwargs: ([], 0)
    )
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
    assert status["decision"] == "waiting_for_prior_version_orders"
    assert status["legacy_prior_version_resting_orders"] == 1
    assert status["placed"] is False


def test_more_competitive_maker_quote_never_spends_last_3c_edge():
    good = SimpleNamespace(price=0.51, edge=0.08, yes_bid=0.40, yes_ask=0.50)
    price, edge, extra = nba.execution_quote(good)
    assert (price, edge, extra) == (0.51, 0.08, 0)
    narrow = SimpleNamespace(price=0.51, edge=0.08, yes_bid=0.48, yes_ask=0.50)
    assert nba.execution_quote(narrow)[2] == 0
    low_edge = SimpleNamespace(price=0.51, edge=0.035, yes_bid=0.40, yes_ask=0.50)
    assert nba.execution_quote(low_edge)[2] == 0
    would_cross = SimpleNamespace(price=0.51, edge=0.08, yes_bid=0.48, yes_ask=0.55)
    assert nba.execution_quote(would_cross)[2] == 0


def test_resting_edge_rule_does_not_cancel_accepted_positive_edge():
    row = priced().iloc[0].copy()
    row["p_book"] = 0.45  # positive 4 cent edge after a 51c NO quote
    intent = {
        "ticker": row.ticker,
        "price_cents": 51,
        "count": 1,
        "probability_source": "sportsbook",
    }
    market = {"status": "active", "yes_bid_dollars": 0.40, "yes_ask_dollars": 0.50}
    assert nba.RESTING_MIN_NET_EDGE == nba.ENTRY_MIN_NET_EDGE == 0.0
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


def test_one_book_prices_a_line_but_flagged_players_need_two(tmp_path, monkeypatch):
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
    # v7: one fresh book on the exact line prices it (v6: model fallback).
    assert out.p_book.iloc[0] == pytest.approx(0.43)
    assert out.book_source.iloc[0] == "exact"
    assert out.injury_status.iloc[0] == ""
    assert len(nba.select_candidates(out, [], {"active": []}, NOW)) == 1

    frame["requires_book"] = True
    publish(frame, tmp_path, NOW)
    out = nba.nba_candidates(NOW, latest=tmp_path / "latest.csv")
    assert out.injury_status.iloc[0] == "SEASON_OR_ROLE_CHANGE_NEEDS_TWO_BOOKS"
    assert nba.select_candidates(out, [], {"active": []}, NOW) == []


def test_probable_teammate_update_does_not_block_whole_team(tmp_path, monkeypatch):
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


def test_questionable_teammate_update_blocks_changed_team(tmp_path, monkeypatch):
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


def test_daily_team_cap_resets_without_resetting_game_or_lifetime():
    row = SimpleNamespace(game_id="new-game", team="LAL")
    yesterday = NOW - timedelta(days=1)
    past = [_past_attempt(i, "old-game", "LAL", 7.3) for i in range(3)]
    for a in past:
        a["utc"] = yesterday.isoformat()
    assert nba.room_for(past, [], row, 1.0, NOW)
    for a in past:
        a["utc"] = NOW.isoformat()
    assert "nba_per_team_submissions" in nba.budget_blockers(past, [], row, 1.0, NOW)


def test_v4_handback_waits_for_v3_resting_orders():
    v3 = {
        "client_order_id": "cid-v3",
        "ticker": "KXNBA-V3",
        "strategy_version": "nba-no-v3-long-resting-throughput",
    }
    accepted = {"cid-v3": {"order_id": "oid-v3"}}
    assert (
        nba.legacy_resting_count(
            [v3], accepted, [{"order_id": "oid-v3", "ticker": "KXNBA-V3"}]
        )
        == 1
    )
    assert nba.legacy_resting_count([v3], accepted, []) == 0


@pytest.mark.parametrize("hours_to_tip", [1.95, 1.0, 0.5, 0.05])
def test_accepted_nba_order_may_stay_resting_near_tip(hours_to_tip):
    # These quotes could never be new *entries* this close to tip,
    # but already-accepted orders must not be auto-canceled solely because
    # the 2h entry cutoff passed.
    row = priced().iloc[0].copy()
    row["hours_to_tip"] = hours_to_tip
    intent = {
        "ticker": row.ticker,
        "price_cents": 51,
        "count": 1,
        "probability_source": "sportsbook",
    }
    market = {
        "status": "active",
        "yes_bid_dollars": 0.40,
        "yes_ask_dollars": 0.50,
    }
    assert nba.resting_cancel_reason(row, intent, market, 0.0) is None
    frame = pd.DataFrame([row])
    assert nba.select_candidates(frame, [], {"active": []}, NOW) == []


@pytest.mark.parametrize("hours_to_tip", [0.0, -0.01])
def test_expired_nba_order_no_longer_valid_at_or_after_tip(hours_to_tip):
    row = priced().iloc[0].copy()
    row["hours_to_tip"] = hours_to_tip
    intent = {
        "ticker": row.ticker,
        "price_cents": 51,
        "count": 1,
        "probability_source": "sportsbook",
    }
    market = {
        "status": "active",
        "yes_bid_dollars": 0.40,
        "yes_ask_dollars": 0.50,
    }
    assert (
        nba.resting_cancel_reason(row, intent, market, 0.0)
        == "outside_verified_pretip_window"
    )


def test_day_to_day_player_is_not_priced_as_confirmed_available(tmp_path, monkeypatch):
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
                    "player_id": 1234,
                    "team": "LAL",
                    "updated": (NOW - timedelta(hours=2)).isoformat(),
                    "out": False,
                    "status": "Day-To-Day",
                    "comment": "Ankle",
                }
            ]
        ),
    )
    publish(priced(), tmp_path, NOW)
    result = nba.nba_candidates(NOW, latest=tmp_path / "latest.csv")
    assert result.injury_status.iloc[0] == "UNCERTAIN_PLAYER_AVAILABILITY"
    assert not nba.select_candidates(result, [], {"active": []}, NOW)


def test_uncertain_teammate_requires_independent_books(tmp_path, monkeypatch):
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
                    "player_id": 9999,
                    "team": "LAL",
                    "updated": (NOW - timedelta(hours=2)).isoformat(),
                    "out": False,
                    "status": "Day-To-Day",
                    "comment": "Knee",
                }
            ]
        ),
    )
    snapshot = priced()
    snapshot["book_n"] = 0
    snapshot["p_book"] = float("nan")
    publish(snapshot, tmp_path, NOW)
    result = nba.nba_candidates(NOW, latest=tmp_path / "latest.csv")
    assert result.injury_status.iloc[0] == "UNCERTAIN_TEAM_REQUIRES_TWO_BOOKS"
    snapshot["book_n"] = 2
    snapshot["p_book"] = 0.4
    publish(snapshot, tmp_path, NOW)
    verified = nba.nba_candidates(NOW, latest=tmp_path / "latest.csv")
    assert verified.injury_status.iloc[0] == ""


def test_old_sportsbook_consensus_is_not_used_to_retain_nba_orders(
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
    q = priced()
    q["book_updated_utc"] = (NOW - timedelta(hours=3)).isoformat()
    publish(q, tmp_path, NOW)
    result = nba.nba_candidates(NOW, latest=tmp_path / "latest.csv")
    assert pd.isna(result.p_book.iloc[0])
    assert result.book_n.iloc[0] == 0
    assert result.attrs["diagnostics"]["sportsbook_age_rejected"] == 1

    q["book_updated_utc"] = (NOW - timedelta(minutes=30)).isoformat()
    publish(q, tmp_path, NOW)
    fresh = nba.nba_candidates(NOW, latest=tmp_path / "latest.csv")
    assert fresh.book_n.iloc[0] == 2
    assert fresh.p_book.iloc[0] == 0.43
    # v7: older than 60 minutes is stale at any time before tip (v6: 120).
    q["book_updated_utc"] = (NOW - timedelta(minutes=61)).isoformat()
    publish(q, tmp_path, NOW)
    old = nba.nba_candidates(NOW, latest=tmp_path / "latest.csv")
    assert pd.isna(old.p_book.iloc[0]) and old.book_n.iloc[0] == 0


def _one_resting_order_world(monkeypatch, tmp_path, *, dual=False, shared=None):
    import live.shared_account_risk as shared_risk

    attempt = {
        "client_order_id": "cid-now",
        "ticker": "KXNBAPTS-NOW",
        "cost": 1.0,
        "utc": NOW.isoformat(),
        "strategy_version": nba.STRATEGY_VERSION,
        "game_id": "g",
        "team": "LAL",
    }
    accepted = {"cid-now": {"order_id": "order-now"}}
    state = {
        "resting": [{"order_id": "order-now", "ticker": "KXNBAPTS-NOW"}],
        "settled": set(),
        "settlements": [],
        "held": [],
        "active": [attempt],
    }

    class Client:
        env, dry_run, can_sign = "prod", False, True

        def fills(self, **kwargs):
            return []

        def balance(self):
            return {"balance": 250}

        def place(self, order):
            raise AssertionError("no new orders in these scenarios")

    calls = []
    monkeypatch.setattr(nba, "guard", lambda *args: None)
    monkeypatch.setattr(shared_risk, "dual_mode", lambda env: dual)
    if dual:
        monkeypatch.setattr(shared_risk, "state_for", lambda *a: (state, shared))
    monkeypatch.setattr(nba, "load_journal", lambda journal: [])
    monkeypatch.setattr(nba, "records", lambda events: ([attempt], accepted))
    monkeypatch.setattr(nba, "current_production_state", lambda *args: state)
    monkeypatch.setattr(
        nba, "reconcile_expired_unfilled", lambda *args, **kwargs: ([attempt], 0)
    )
    monkeypatch.setattr(nba, "record_execution", lambda *args: None)
    monkeypatch.setattr(nba, "record_queue_observation", lambda *args: None)
    monkeypatch.setattr(nba, "record_markouts", lambda *args: None)
    monkeypatch.setattr(
        nba, "cancel_invalid_resting", lambda *args: calls.append(args) or 1
    )
    return Client(), calls, tmp_path / "journal.jsonl"


def _blocked_frame(reason="URLError"):
    frame = pd.DataFrame()
    frame.attrs["diagnostics"] = {"blocked": reason}
    return frame


def test_short_input_outage_holds_resting_orders(monkeypatch, tmp_path):
    client, calls, journal = _one_resting_order_world(monkeypatch, tmp_path)
    nba.note_good_inputs(tmp_path, NOW - timedelta(minutes=5))
    assert not nba.pass_once(client, ARMED, _blocked_frame(), NOW, journal)
    assert calls == []  # nothing cancelled during a short outage
    status = json.loads((tmp_path / "last_scan.json").read_text())
    assert status["decision"] == "inputs_unavailable_holding_resting"


def test_long_or_unknown_outage_still_cancels(monkeypatch, tmp_path):
    client, calls, journal = _one_resting_order_world(monkeypatch, tmp_path)
    assert nba.minutes_since_good_inputs(tmp_path, NOW) == float("inf")
    nba.pass_once(client, ARMED, _blocked_frame(), NOW, journal)
    assert len(calls) == 1  # no record of good inputs: fail closed
    calls.clear()
    nba.note_good_inputs(tmp_path, NOW - timedelta(minutes=40))
    nba.pass_once(client, ARMED, _blocked_frame(), NOW, journal)
    assert len(calls) == 1  # outage longer than the hold window


def test_good_inputs_are_recorded_and_rechecked_normally(monkeypatch, tmp_path):
    client, calls, journal = _one_resting_order_world(monkeypatch, tmp_path)
    nba.pass_once(client, ARMED, priced(), NOW, journal)
    assert nba.minutes_since_good_inputs(tmp_path, NOW) < 1
    assert len(calls) == 1  # per-order recheck still runs on good inputs


def test_account_loss_stop_blocks_new_nba_orders(monkeypatch, tmp_path):
    shared = {"account_pnl": {"loss_stop": True}, "ownership": {}}
    client, calls, journal = _one_resting_order_world(
        monkeypatch, tmp_path, dual=True, shared=shared
    )
    monkeypatch.setattr(nba, "cancel_invalid_resting", lambda *args: 0)
    assert not nba.pass_once(client, ARMED, priced(), NOW, journal)
    status = json.loads((tmp_path / "last_scan.json").read_text())
    assert status["decision"] == "account_loss_stop"


def test_data_integrity_failures_still_cancel_immediately(monkeypatch, tmp_path):
    client, calls, journal = _one_resting_order_world(monkeypatch, tmp_path)
    nba.note_good_inputs(tmp_path, NOW - timedelta(minutes=2))
    for reason in (
        "unidentifiable_or_undated_injury",
        "future_injury_timestamp",
        "duplicate_projection_ticker",
        "no_priced_markets",
    ):
        calls.clear()
        nba.pass_once(client, ARMED, _blocked_frame(reason), NOW, journal)
        assert len(calls) == 1, reason


def test_unverifiable_account_pnl_still_lets_cancels_run(monkeypatch, tmp_path):
    shared = {"account_pnl": {"unavailable": "Incomplete settlement"}, "ownership": {}}
    client, calls, journal = _one_resting_order_world(
        monkeypatch, tmp_path, dual=True, shared=shared
    )
    nba.pass_once(client, ARMED, priced(), NOW, journal)
    assert len(calls) == 1  # the unsafe-order cancel ran first
    monkeypatch.setattr(nba, "cancel_invalid_resting", lambda *args: 0)
    with pytest.raises(TradingError, match="unverifiable"):
        nba.pass_once(client, ARMED, priced(), NOW, journal)  # then: no new orders


def test_v6_three_contracts_fit_every_per_order_and_per_game_cap():
    # The dearest allowed NO price still fits $4 an order at 3 contracts.
    high = nba.PRICE_BAND_CENTS[1] / 100
    assert nba.reserve(round(nba.MAX_CONTRACTS * high, 2)) <= nba.MAX_ORDER_COST
    row = SimpleNamespace(game_id=20261020, team="LAL")
    # $45 already in this game (other teams): a $3 order fits under $50, a $6 one does not.
    game = [_past_attempt(i, 20261020, "OTHER" + str(i), 4.5) for i in range(9)]
    assert "nba_per_game_submissions" not in nba.budget_blockers(
        game, [], row, 3.0, NOW
    )
    assert "nba_per_game_submissions" in nba.budget_blockers(game, [], row, 6.0, NOW)


def test_v5_orders_resting_at_the_switch_are_drained_not_halted():
    v5 = {
        "client_order_id": "v5",
        "ticker": "KXNBA-V5",
        "strategy_version": "nba-no-v5-one-contract-breadth",
    }
    v6 = {
        "client_order_id": "v6",
        "ticker": "KXNBA-V6",
        "strategy_version": nba.STRATEGY_VERSION,
    }
    accepted = {"v5": {"order_id": "order-v5"}, "v6": {"order_id": "order-v6"}}
    resting = [{"order_id": "order-v5", "ticker": "KXNBA-V5"}]
    # Counted as a prior-version order (new orders wait), never a HALT.
    assert nba.legacy_resting_count([v5, v6], accepted, resting) == 1


def test_fee_reserve_shrinks_a_cheap_order_instead_of_skipping_it():
    from kalshi.trading import Order

    calls = []

    def one_cent_a_contract(ticker, price, count, cache):
        calls.append(count)
        return round(0.01 * count, 2), {"fee_type": "quadratic_with_maker_fees"}

    def order(cents):
        return Order(
            ticker="KXNBAPTS-X",
            side="no",
            count=3,  # the shrinking logic, independent of the live size
            price_cents=cents,
            expiration_ts=int(NOW.timestamp()) + 3600,
        )

    # 5c with a 1c fee: 3 and 2 contracts exceed the 10% reserve, 1 fits.
    cheap = order(5)
    fee, _, cost = nba.fit_fee_reserve(cheap, 0.05, {}, one_cent_a_contract)
    assert (cheap.count, cost, fee) == (1, 0.05, 0.01) and calls == [3, 2, 1]
    # Dearer orders keep their full size; fee-free series are never shrunk.
    full = order(51)
    assert nba.fit_fee_reserve(full, 0.51, {}, one_cent_a_contract)[2] == 1.53
    assert full.count == 3
    free = order(5)
    nba.fit_fee_reserve(free, 0.05, {}, lambda *a: (0.0, {}))
    assert free.count == 3


def test_a_resting_one_contract_order_is_valid_and_two_is_not():
    row = priced().iloc[0]
    market = {"status": "active", "yes_bid_dollars": 0.40, "yes_ask_dollars": 0.50}
    intent = {
        "ticker": row.ticker,
        "price_cents": 51,
        "count": 1,
        "probability_source": "sportsbook",
    }
    assert nba.resting_cancel_reason(row, intent, market, 0.0) is None
    too_big = {**intent, "count": nba.MAX_CONTRACTS + 1}
    assert (
        nba.resting_cancel_reason(row, too_big, market, 0.0) == "invalid_original_order"
    )


def test_v7_never_prices_from_the_model():
    f = priced()
    f["p_book"] = float("nan")
    f["book_n"] = 0
    stats = {}
    assert nba.select_candidates(f, [], {"active": []}, NOW, diagnostics=stats) == []
    assert stats["book_priced"] == 0


def test_v7_model_can_only_veto_and_edges_are_capped():
    f = priced()
    f["p_model"] = 0.60  # the model thinks NO is worth 40c, under the 51c price
    stats = {}
    assert nba.select_candidates(f, [], {"active": []}, NOW, diagnostics=stats) == []
    assert stats["book_priced"] == 1 and stats["passed_model_veto"] == 0
    g = priced()
    g["p_book"] = 0.38  # book edge about 10.6c: above the 8c cap
    stats = {}
    assert nba.select_candidates(g, [], {"active": []}, NOW, diagnostics=stats) == []
    assert stats["passed_model_veto"] == 1 and stats["passed_edge_sanity"] == 0


def test_v7_translated_price_fills_a_line_no_book_quotes(tmp_path):
    from kalshi.line_translation import attach_translated

    frame = priced().assign(player_key="test player", p_book=float("nan"), book_n=0)
    tip = frame.tip_utc.iloc[0].isoformat()
    book = pd.DataFrame(
        {
            "player_key": ["test player"] * 3,
            "stat": ["points"] * 3,
            "line": [27.5, 28.5, 31.5],
            "p_book": [0.55, 0.50, 0.36],
            "book_n": [2, 3, 1],
            "updated_utc": [NOW.isoformat()] * 3,
            "commence_utc": [tip] * 3,
        }
    )
    out = attach_translated(frame, book)
    assert out.book_source.iloc[0] == "translated" and out.book_n.iloc[0] == 6
    assert 0.36 < out.p_book.iloc[0] < 0.50  # between the nearby lines
    far = book.assign(line=book.line - 10)  # nothing within 3 points
    assert attach_translated(frame, far).book_source.iloc[0] == ""


def test_v7_pipeline_prices_an_unquoted_line_from_fresh_nearby_lines(
    tmp_path, monkeypatch
):
    import kalshi.books as books
    import live.nba_trade as trader
    import markets.nba.live as live

    monkeypatch.setattr(trader, "refresh_quotes", lambda f, now: f.copy())
    monkeypatch.setattr(books, "attach_latest", lambda f, path=None: f.copy())
    monkeypatch.setattr(
        live,
        "injuries",
        lambda: pd.DataFrame(columns=["player_id", "team", "updated", "out"]),
    )
    frame = priced()
    frame["p_book"] = float("nan")
    frame["book_n"] = 0
    publish(frame, tmp_path, NOW)
    tip = frame.tip_utc.iloc[0].isoformat()

    def write_book(minutes_old):
        pd.DataFrame(
            {
                "player_key": ["test player"] * 3,
                "stat": ["points"] * 3,
                "line": [27.5, 28.5, 31.5],
                "p_book": [0.55, 0.50, 0.36],
                "book_n": [2, 3, 1],
                "updated_utc": [(NOW - timedelta(minutes=minutes_old)).isoformat()] * 3,
                "commence_utc": [tip] * 3,
                "snapshot_utc": [NOW.isoformat()] * 3,
            }
        ).to_csv(tmp_path / "nba_books.csv", index=False)

    write_book(10)
    out = nba.nba_candidates(NOW, latest=tmp_path / "latest.csv")
    assert out.book_source.iloc[0] == "translated"
    assert 0.36 < out.p_book.iloc[0] < 0.50
    assert out.attrs["diagnostics"]["book_translated"] == 1
    write_book(90)  # every nearby line older than 60 minutes: no price
    stale = nba.nba_candidates(NOW, latest=tmp_path / "latest.csv")
    assert pd.isna(stale.p_book.iloc[0])
