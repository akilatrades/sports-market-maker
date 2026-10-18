"""Safety tests for the separate, disabled-by-default NBA production worker."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from kalshi.trading import TradingError
from live import prod_nba_auto as nba

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
                "yes_bid_dollars": 0.40,
                "yes_ask_dollars": 0.50,
            }
        ]
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
    (tmp_path / "latest_meta.json").write_text(
        json.dumps({"generated_utc": NOW.isoformat()})
    )
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
    (tmp_path / "latest_meta.json").write_text(
        json.dumps({"generated_utc": (NOW - timedelta(hours=1)).isoformat()})
    )
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
