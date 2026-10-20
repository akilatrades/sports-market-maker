"""Execution KPIs must use exchange fills, never simulated bookmaker edges."""

from live.execution_scorecard import observed_execution


def test_fill_metrics_are_conditioned_on_terminal_orders_only():
    rows = [
        {"ticker": "A", "state": "fully_filled", "filled_contracts": 2.0,
         "fill_fees_dollars": .02, "maker_filled_contracts": 2.0,
         "submitted_utc": "2026-10-20T12:00:00+00:00",
         "first_fill_utc": "2026-10-20T12:10:00+00:00"},
        {"ticker": "B", "state": "confirmed_unfilled", "filled_contracts": 0.0},
        {"ticker": "C", "state": "resting_no_fill", "filled_contracts": 0.0},
    ]
    events = [{"event": "intent", "ticker": "A",
               "net_edge_after_fee_bound": .07}]
    report = observed_execution(
        {"status": "verified_snapshot", "orders": rows,
         "unknown_or_unreconciled": 0}, events
    )
    assert report["accepted_orders"] == 3
    assert report["closed_orders_with_known_outcome"] == 2
    assert report["closed_order_fill_rate"] == .5
    assert report["maker_share"] == 1.0
    assert report["mean_minutes_to_first_fill"] == 10
    assert report["model_estimated_net_edge_on_filled"] == .07


def test_missing_maker_fees_and_time_never_invent_zero():
    report = observed_execution(
        {"status": "verified_snapshot",
         "orders": [{"ticker": "A", "state": "fully_filled",
                     "filled_contracts": 1, "maker_filled_contracts": None,
                     "fill_fees_dollars": None}],
         "unknown_or_unreconciled": 0},
        [{"event": "intent", "ticker": "A"}],
    )
    assert report["maker_share"] is None
    assert report["total_reported_fees_dollars"] is None
    assert report["mean_minutes_to_first_fill"] is None
    assert report["model_estimated_net_edge_on_filled"] is None
