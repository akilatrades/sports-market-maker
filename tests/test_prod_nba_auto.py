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
    assert extra == 0
    assert quote == rows[0].price
    assert edge == rows[0].edge
    order, cost = nba.order_from_row(rows[0], NOW, no_price=quote)
    assert order.side == "no"
    assert order.post_only
    assert order.body()["side"] == "ask"
    assert 0 < cost <= nba.MAX_ORDER_COST


def test_separate_risk_caps_and_state():
    assert str(nba.STATE).endswith("prod-nba-auto")
    assert nba.MAX_GROSS_COST == 50
    assert nba.MAX_ACTIVE_COST == 15
    assert nba.MAX_ORDER_COST == 3
    assert nba.MAX_DAILY_COST == 30
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
    assert not nba.pass_once(
        None, {}, pd.DataFrame(), NOW, journal, dry=True
    )
    assert json.loads(report.read_text()) == {
        "decision": "exchange_accepted", "mode": "live"
    }
    assert not journal.exists()
