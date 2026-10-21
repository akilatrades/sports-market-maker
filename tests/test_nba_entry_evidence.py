"""Future NBA orders must record as-of signal provenance, including unknowns."""

from types import SimpleNamespace

import numpy as np

from live.prod_nba_auto import entry_evidence


def test_verified_licensed_minutes_and_confirmed_role_are_separate():
    row = SimpleNamespace(
        projected_minutes=32.4,
        projected_minutes_source="rotowire_licensed",
        historical_minutes_baseline=27.1,
        minutes_forecast_internal=27.1,
        lineup_confirmation_status="confirmed",
        confirmed_starter=np.bool_(False),
        pregame_context_fetch_utc="2026-10-20T18:55:00+00:00",
        book_updated_utc="2026-10-20T19:00:00+00:00",
        p_model=0.49,
        p_book=0.51,
        yes_bid=0.45,
        yes_ask=0.49,
    )
    evidence = entry_evidence(row)
    assert evidence["projected_minutes_at_entry"] == 32.4
    assert evidence["projected_minutes_source_at_entry"] == "rotowire_licensed"
    assert evidence["lineup_confirmation_status_at_entry"] == "confirmed"
    assert evidence["confirmed_starter_at_entry"] is False
    assert evidence["vendor_context_fetch_utc_at_entry"].startswith("2026-10-20")
    assert evidence["sportsbook_probability_yes_at_entry"] == 0.51


def test_history_is_never_labeled_independent_minutes():
    row = SimpleNamespace(
        historical_minutes_baseline=32.1,
        projected_minutes=31.2,
        projected_minutes_source="prior_only_uncalibrated",
        lineup_confirmation_status="expected",
        confirmed_starter=True,
    )
    evidence = entry_evidence(row)
    assert evidence["projected_minutes_at_entry"] is None
    assert evidence["projected_minutes_source_at_entry"] == "unverified"
    assert evidence["historical_minutes_baseline_at_entry"] == 32.1
    assert evidence["confirmed_starter_at_entry"] is None
    assert evidence["lineup_confirmation_status_at_entry"] == "unverified"


def test_missing_and_invalid_context_are_explicit_nulls():
    evidence = entry_evidence(SimpleNamespace(projected_minutes=float("nan")))
    assert evidence["projected_minutes_at_entry"] is None
    assert evidence["lineup_confirmation_status_at_entry"] == "unverified"
    assert evidence["vendor_context_fetch_utc_at_entry"] is None
    assert evidence["book_updated_utc_at_entry"] is None
    assert evidence["sportsbook_probability_yes_at_entry"] is None


def test_vendor_minute_outliers_are_not_verified():
    evidence = entry_evidence(
        SimpleNamespace(
            projected_minutes=60,
            projected_minutes_source="rotowire_licensed",
            lineup_confirmation_status="confirmed",
            confirmed_starter="true",
        )
    )
    assert evidence["projected_minutes_at_entry"] is None
    assert evidence["confirmed_starter_at_entry"] is None
