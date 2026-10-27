"""Offline economic checks: timing, executable depth, fees and event exposure."""

import copy
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from research.spread_quality_review import review

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)


def fill(fid="a", event="EVENT", ticker="MARKET", **changes):
    return {
        "fid": fid,
        "at": NOW.isoformat(),
        "event_ticker": event,
        "ticker": ticker,
        "side": "yes",
        "quantity": "2",
        "price": "0.40",
        "fee": "0.02",
        **changes,
    }


def sample(fills, horizon=0, lag=5, depth=None):
    return {
        "valid": True,
        "at": (NOW + timedelta(seconds=horizon + lag)).isoformat(),
        "fee_multiplier": 1,
        "external_book": {"yes": depth or [["0.60", "1"], ["0.50", "1"]], "no": []},
        "lots": [
            {
                "fid": f["fid"],
                "fill_at": f["at"],
                "horizon_seconds": horizon,
                "remaining_actual": f["quantity"],
            }
            for f in fills
        ],
    }


def study(fills=(), samples=(), resolved=None):
    resolved = resolved or {}
    return {
        "generated_at": NOW.isoformat(),
        "manifest": {"start": NOW.isoformat(), "strategy_version": "fixture"},
        "fills": list(fills),
        "checkpoints": list(samples),
        "report": {
            "invalid_markets": [],
            "baseline": {"resolved_pnl": resolved, "invalid_comparison_markets": []},
            "matched_comparison_markets": list(resolved),
            "shadow_scenarios_by_slippage_cents": {
                "2": {"resolved_pnl": dict(resolved)}
            },
        },
    }


class QualityReviewTests(unittest.TestCase):
    def test_empty_cohort_and_future_horizons_are_not_failures(self):
        self.assertIsNone(review(study(), NOW)["coverage"]["ratio"])
        f = fill()
        data = study([f], [sample([f])])
        before = review(data, NOW + timedelta(seconds=60))
        self.assertEqual(before["coverage"]["due"], 0)
        after = review(data, NOW + timedelta(seconds=61))
        self.assertEqual(after["coverage"], {"due": 1, "valid": 1, "ratio": 1})

    def test_late_and_future_observations_are_not_coverage(self):
        f = fill()
        late = study([f], [sample([f], lag=61)])
        self.assertEqual(review(late, NOW + timedelta(seconds=70))["coverage"]["valid"], 0)
        future = study([f], [sample([f])])
        self.assertEqual(review(future, NOW)["checkpoint_details"], [])

    def test_fees_and_all_depth_levels_count_and_input_is_unchanged(self):
        f = fill()
        data = study([f], [sample([f])])
        original = copy.deepcopy(data)
        result = review(data, NOW + timedelta(seconds=61))
        row = result["checkpoint_details"][0]
        self.assertEqual(Decimal(row["modeled_exit_pnl"]), Decimal("0.24"))
        self.assertEqual(data, original)
        self.assertEqual(result["entry_filter_test"]["status"], "not_testable_from_this_export")

    def test_partial_depth_never_becomes_a_full_position_profit(self):
        f = fill()
        data = study([f], [sample([f], depth=[["0.60", "1"]])])
        result = review(data, NOW + timedelta(seconds=61))
        row = result["checkpoint_details"][0]
        self.assertIsNone(row["modeled_exit_pnl"])
        self.assertEqual(row["unfilled_quantity"], "1")
        self.assertEqual(result["exit_diagnostics"]["0"]["full_position_exits"], 0)

    def test_lots_cannot_reuse_the_same_snapshot_depth(self):
        a, b = fill(), fill("b")
        data = study([a, b], [sample([b, a], depth=[["0.60", "2"]])])
        result = review(data, NOW + timedelta(seconds=61))
        rows = {r["fill_ref"]: r for r in result["checkpoint_details"]}
        self.assertEqual(rows["a"]["sold_quantity"], "2")
        self.assertEqual(rows["b"]["sold_quantity"], "0")
        self.assertIsNone(rows["b"]["modeled_exit_pnl"])
        self.assertEqual(result["event_budget_sensitivity"]["status"], "unsupported_multiple_fills_in_market")

    def test_repeated_evidence_and_invalid_accounting_are_rejected(self):
        f = fill()
        cases = [
            (study([f, f]), "duplicate_fill"),
            (study([f], [sample([f]), sample([f])]), "duplicate_checkpoint"),
            (study([], [sample([f])]), "unknown_checkpoint_fill"),
        ]
        invalid = study([f])
        invalid["report"]["invalid_markets"] = ["MARKET"]
        cases.append((invalid, "invalid_study_accounting"))
        for data, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                review(data, NOW + timedelta(seconds=61))

    def test_event_budget_is_chronological_fee_inclusive_and_not_recycled(self):
        a = fill(fee="0.20")  # Exactly $1 with fees.
        b = fill("b", ticker="SECOND", at=(NOW + timedelta(seconds=1)).isoformat())
        pending = fill("c", event="OTHER", ticker="PENDING", quantity="1", fee="0")
        data = study([b, pending, a], resolved={"MARKET": "-0.80", "SECOND": "0.80"})
        result = review(data, NOW + timedelta(hours=2))["event_budget_sensitivity"]
        self.assertEqual(Decimal(result["actual_resolved_pnl"]), 0)
        self.assertEqual(Decimal(result["scaled_resolved_pnl"]), Decimal("-0.80"))
        self.assertEqual(Decimal(result["pending_entry_cost"]), Decimal("0.40"))
        self.assertEqual(result["resolved_events"], 1)
        self.assertEqual(Decimal(result["allocations"][-1]["retained_cost"]), 0)

    def test_exit_comparison_excludes_unsettled_hold_baseline(self):
        data = study([fill()], resolved={"MARKET": "-0.80"})
        data["report"]["shadow_scenarios_by_slippage_cents"]["2"]["resolved_pnl"].update(
            {"MARKET": "0.10", "UNSETTLED": "100"}
        )
        comparison = review(data, NOW)["matched_exit_comparison"]
        self.assertEqual(comparison, {"hold": "-0.80", "exits": {"2": "0.10"}})


if __name__ == "__main__":
    unittest.main()
