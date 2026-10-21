"""Regression coverage for independent-context proof on shadow NBA signals.

The late window is a research cohort, NEVER an implicit live trade switch.
"""

from types import SimpleNamespace

import numpy as np
import pandas as pd

from live.prod_nba_auto import late_context_diagnostics


def _frame(minutes=29.0, source="rotowire_licensed", status="confirmed", starter=True):
    return pd.DataFrame(
        [
            {
                "ticker": "A",
                "projected_minutes": minutes,
                "projected_minutes_source": source,
                "lineup_confirmation_status": status,
                "confirmed_starter": starter,
            }
        ]
    )


def test_late_shadow_reports_both_independent_context_gates():
    result = late_context_diagnostics(
        _frame(starter=np.bool_(False)), [SimpleNamespace(ticker="A")]
    )
    assert result == {
        "shadow_candidates": 1,
        "licensed_projected_minutes": 1,
        "confirmed_starting_five": 1,
        "both_verified": 1,
        "execution_enabled": False,
    }


def test_predicted_lineup_and_historical_minutes_never_count_as_confirmed():
    candidates = [SimpleNamespace(ticker="A")]
    assert (
        late_context_diagnostics(_frame(source="prior_only_uncalibrated"), candidates)[
            "both_verified"
        ]
        == 0
    )
    assert (
        late_context_diagnostics(_frame(status="expected", starter=True), candidates)[
            "both_verified"
        ]
        == 0
    )
    assert late_context_diagnostics(_frame(minutes=7), candidates)["both_verified"] == 0
    assert (
        late_context_diagnostics(_frame(starter="true"), candidates)[
            "confirmed_starting_five"
        ]
        == 0
    )
    assert (
        late_context_diagnostics(_frame(starter=None), candidates)[
            "confirmed_starting_five"
        ]
        == 0
    )


def test_shadow_without_row_or_vendor_context_does_not_authorize_execution():
    empty = pd.DataFrame()
    missing = [SimpleNamespace(ticker="NO_MATCH")]
    assert late_context_diagnostics(empty, missing)["both_verified"] == 0
    assert not late_context_diagnostics(_frame(), missing)["execution_enabled"]
