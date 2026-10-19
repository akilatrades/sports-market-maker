"""Offline, network-free tests of the funded Kalshi account P&L feed."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from live.public_pnl_feed import Cache, account_settlement_pnl, collect_public, handler_for

NOW = datetime(2026, 10, 19, 14, 40, tzinfo=UTC)


def settlement(ticker, revenue, no_cost, yes_cost="0.00", fee="0.00"):
    return {
        "ticker": ticker, "revenue_dollars": str(revenue),
        "no_total_cost_dollars": str(no_cost),
        "yes_total_cost_dollars": str(yes_cost), "fee_cost": str(fee),
    }


def test_account_includes_unrelated_manual_trades():
    records = [
        settlement("NFL", "0.00", "2.68"),
        settlement("MANUAL", "2.00", "1.00", fee="0.20"),
    ]
    total = account_settlement_pnl(records)
    assert total["status"] == "verified_settlement_snapshot"
    assert total["settled_profit_dollars"] == -1.88
    assert total["settled_markets"] == 2
    assert "MANUAL" not in json.dumps(total)


def test_duplicate_rows_are_not_double_counted():
    row = settlement("NFL", 0, "0.60")
    assert account_settlement_pnl([row, row])["settled_profit_dollars"] == -0.6
    with pytest.raises(ValueError, match="conflicting_settlement_rows"):
        account_settlement_pnl([row, settlement("NFL", 0, "0.90")])


def test_missing_revenue_or_fee_halts_account_pnl():
    row = settlement("NFL", "1.00", "0.60")
    del row["fee_cost"]
    with pytest.raises(ValueError, match="unreconciled_account_settlement"):
        account_settlement_pnl([row])


def test_zero_settlements_are_not_a_fabricated_zero_return():
    result = account_settlement_pnl([])
    assert result["status"] == "awaiting_settlement"
    assert result["settled_profit_dollars"] is None


def test_signed_data_used_and_public_report_never_contains_account_identifiers(tmp_path):
    nfl = tmp_path / "nfl.jsonl"
    nba = tmp_path / "nba.jsonl"
    # A manual winning market and independent owned losing NFL market.
    nfl.write_text(
        json.dumps({
            "event": "intent", "utc": "2026-10-18T12:00:00+00:00",
            "client_order_id": "client_secret_id", "ticker": "NFL-SECRET",
        }) + "\n" +
        json.dumps({
            "event": "accepted", "client_order_id": "client_secret_id",
            "order_id": "order_secret_id",
        }) + "\n"
    )
    nba.write_text("")
    class FakeClient:
        def __init__(self):
            self.requests = []

        def pages(self, path, key, **args):
            self.requests.append((path, key, args))
            if key == "settlements":
                return [
                    settlement("NFL-SECRET", 0, "0.60"),
                    settlement("MANUAL-PRIVATE", 2, "1.00"),
                ]
            return [{
                "ticker": "NFL-SECRET", "order_id": "order_secret_id",
                "fill_id": "fill_secret_id", "count_fp": "1",
                "no_price_dollars": "0.60", "outcome_side": "no",
                "book_side": "ask",
            }]

    c = FakeClient()
    report = collect_public(
        client=c, journal_paths={"nfl": nfl, "nba": nba}, now=NOW
    )
    assert report["account"]["settled_profit_dollars"] == 0.40
    assert report["markets"]["nfl"]["settled_profit_dollars"] == -0.60
    assert report["markets"]["nba"]["settled_profit_dollars"] is None
    assert [r[0] for r in c.requests] == [
        "/portfolio/settlements", "/portfolio/fills"
    ]
    assert c.requests[0][2] == {}  # all accessible account settlements
    data = json.dumps(report)
    for private in ("NFL-SECRET", "MANUAL-PRIVATE", "client_secret_id",
                    "order_secret_id", "fill_secret_id", "balance"):
        assert private not in data


def test_service_cache_does_not_leak_private_values():
    c = Cache()
    assert c.read()["status"] == "unavailable"
    c.update({"status": "ok", "as_of_utc": NOW.isoformat()})
    assert c.read()["status"] == "ok"
    assert callable(handler_for(c))
