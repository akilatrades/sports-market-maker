"""Public spread display and unchanged backend summary contracts."""

import json
from pathlib import Path

from live.summarize import live_status

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard" / "index.html"

def test_running_now_publishes_v2_start_margins_and_account_stops():
    from live import spread_policy
    from live.shared_account_risk import ACCOUNT_LOSS_STOPS
    from live.summarize import running_now

    r = running_now()
    assert r["spread"]["min_lead_minutes"] == spread_policy.MIN_LEAD_MINUTES
    assert r["spread"]["cancel_lead_minutes"] == spread_policy.CANCEL_LEAD_MINUTES
    assert r["account_daily_loss_stop"] == ACCOUNT_LOSS_STOPS["daily"]
    assert r["account_total_loss_stop"] == ACCOUNT_LOSS_STOPS["cumulative"]

def test_live_summary_uses_published_validation_not_fake_zeros(tmp_path):
    assert "forward_validation" not in live_status(tmp_path)
    expected = {
        "status": "collecting",
        "eligible_real_orders": 12,
        "settled_buy_fill_events": 4,
        "capture_volume_weighted": 0.34,
        "cents_per_settled_contract": -2.1,
    }
    (tmp_path / "forward_validation.json").write_text(json.dumps(expected))
    assert live_status(tmp_path)["forward_validation"] == expected

def test_invalid_validation_file_is_declared_not_silently_successful(tmp_path):
    (tmp_path / "forward_validation.json").write_text("{invalid")
    output = live_status(tmp_path)
    assert "forward_validation" not in output
    assert output.get("forward_validation_error")

def test_public_profit_file_contains_only_verified_market_aggregates():
    data = json.loads((ROOT / "outputs/dashboard/production_pnl.json").read_text())
    assert data["schema_version"] == 1
    assert {"nfl", "nba"} <= set(data["markets"]) <= {"nfl", "nba", "spread"}
    assert data["refresh_type"] in {
        "manual_verified_snapshot_not_real_time",
        "automated_signed_aggregate_snapshot_not_real_time",
    }
    for name, market in data["markets"].items():
        if name == "spread":  # realized from its own fills, not settlements
            amount = market["realized_profit_dollars"]
            if market["status"] == "verified_fill_ledger":
                assert isinstance(amount, (int, float))
            else:
                assert amount is None
        elif market["status"] == "verified_snapshot":
            assert isinstance(market["settled_profit_dollars"], (int, float))
        else:
            assert market["settled_profit_dollars"] is None
    assert data["as_of_utc"]
    assert not any(key in data for key in ("paper", "ledgers", "balance", "api_keys"))
    assert all(
        "balance" not in key and "order_id" not in key and "token" not in key
        for market in data["markets"].values()
        for key in market
    )
