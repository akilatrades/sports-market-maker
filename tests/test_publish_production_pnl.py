"""Read-only sanitized public profit publisher; no API network calls."""

import json
from datetime import UTC, datetime

import pytest

from tools.publish_production_pnl import build_report, collect_report

NOW = datetime(2026, 10, 19, 14, 30, tzinfo=UTC)


def events(market, order):
    return [
        {
            "event": "intent",
            "client_order_id": f"client-{market}",
            "ticker": f"{market}-GOLDEN-EXAMPLE",
            "utc": "2026-10-18T18:00:00+00:00",
        },
        {
            "event": "accepted",
            "client_order_id": f"client-{market}",
            "order_id": order,
        },
    ]


def fills(market, order, cost, amount):
    return [
        {
            "ticker": f"{market}-GOLDEN-EXAMPLE",
            "order_id": order,
            "fill_id": f"fill-{order}",
            "count_fp": str(amount),
            "no_price_dollars": str(cost / amount),
            "outcome_side": "no",
            "book_side": "ask",
        },
    ]


def settlement(market, cost, revenue):
    return {
        "market_ticker": f"{market}-GOLDEN-EXAMPLE",
        "no_total_cost_dollars": str(cost),
        "yes_total_cost_dollars": "0.00",
        "fee_cost": "0.00",
        "revenue_dollars": str(revenue),
    }


def test_negative_losing_nfl_settlement_replaces_stale_positive_report():
    cohorts = {"nfl": events("NFL", "n1"), "nba": []}
    payload = build_report(cohorts, fills("NFL", "n1", 1.50, 3),
                           [settlement("NFL", 1.50, 0)], NOW)
    assert payload["markets"]["nfl"]["status"] == "verified_snapshot"
    assert payload["markets"]["nfl"]["settled_profit_dollars"] == -1.50
    assert payload["markets"]["nba"]["settled_profit_dollars"] is None
    assert payload["schema_version"] == 1
    output = json.dumps(payload)
    for secret in ("GOLDEN", "client-", "n1", "fill-n1", "balance", "api_key"):
        assert secret not in output


def test_separate_nfl_and_nba_aggregate_results_do_not_cross():
    cohorts = {"nfl": events("NFL", "n1"), "nba": events("NBA", "b2")}
    payload = build_report(
        cohorts, fills("NFL", "n1", 1.50, 3) + fills("NBA", "b2", 1.20, 2),
        [settlement("NFL", 1.50, 0), settlement("NBA", 1.20, 2)], NOW
    )
    assert payload["markets"]["nfl"]["settled_profit_dollars"] == -1.50
    assert payload["markets"]["nba"]["settled_profit_dollars"] == 0.80


def test_foreign_same_market_fill_blocks_publishing():
    cohorts = {"nfl": events("NFL", "n1"), "nba": []}
    filled = fills("NFL", "n1", 1.50, 3)
    filled += fills("NFL", "foreign-order", 0.50, 1)
    with pytest.raises(ValueError, match="reconciliation_incomplete"):
        build_report(cohorts, filled, [settlement("NFL", 2.00, 0)], NOW)


def test_mismatched_settlement_cost_blocks_publishing():
    cohorts = {"nfl": events("NFL", "n1"), "nba": []}
    with pytest.raises(ValueError, match="reconciliation_incomplete"):
        build_report(
            cohorts, fills("NFL", "n1", 1.50, 3),
            [settlement("NFL", 2.0, 0)], NOW
        )


def test_no_journal_is_unknown_and_not_a_fake_zero():
    result = build_report({"nfl": None, "nba": []}, [], [], NOW)
    assert result["markets"]["nfl"]["status"] == "unavailable"
    assert result["markets"]["nfl"]["settled_profit_dollars"] is None
    assert result["markets"]["nba"]["status"] == "awaiting_first_order"


def test_only_signed_exchange_read_and_private_journals(tmp_path):
    class FakeClient:
        def __init__(self):
            self.calls = []

        def pages(self, path, key, **params):
            self.calls.append((path, key, params))
            return fills("NFL", "n1", 1.50, 3) if key == "fills" else [
                settlement("NFL", 1.50, 0)
            ]

    n = tmp_path / "nfl.jsonl"
    b = tmp_path / "nba.jsonl"
    n.write_text("".join(json.dumps(x) + "\n" for x in events("NFL", "n1")))
    b.write_text("")
    client = FakeClient()
    report = collect_report(now=NOW, client=client, journals={"nfl": n, "nba": b})
    assert report["markets"]["nfl"]["settled_profit_dollars"] == -1.50
    assert [x[0] for x in client.calls] == [
        "/portfolio/fills", "/portfolio/settlements"
    ]
    assert not any("balance" in x[0] for x in client.calls)
