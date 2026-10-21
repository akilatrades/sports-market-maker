"""Shared test setup: no test may reach the NBA's injury-report website."""

import pytest


@pytest.fixture(autouse=True)
def offline_official_injury_report(monkeypatch):
    import markets.nba.official_injuries as official

    def offline(url, timeout=15):
        raise OSError("tests are offline")

    monkeypatch.setattr(official, "download", offline)
