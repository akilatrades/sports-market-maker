"""Shared test setup: no test may reach the NBA's injury-report website."""

import pytest


@pytest.fixture(autouse=True)
def offline_official_injury_report(monkeypatch):
    import markets.nba.official_injuries as official

    def offline(url, timeout=15):
        raise OSError("tests are offline")

    monkeypatch.setattr(official, "download", offline)


# Tests of the live NBA limits themselves (they must see the real values).
NBA_REAL_LIMIT_TESTS = {"test_separate_risk_caps_and_state"}


@pytest.fixture(autouse=True)
def nba_logic_tests_use_the_wide_price_band(request, monkeypatch):
    """NBA rules v9 (2026-11-16) place NO orders at 65c-95c only. The logic
    tests written for v2-v8 use orders near 50c, so they keep the old 5c-95c
    band; the v9 tests and the live-limit test see the real one."""
    name = request.node.originalname or request.node.name
    if name.startswith("test_v9_") or name in NBA_REAL_LIMIT_TESTS:
        return
    import live.prod_nba_auto as nba

    monkeypatch.setattr(nba, "PRICE_BAND_CENTS", (5, 95))
