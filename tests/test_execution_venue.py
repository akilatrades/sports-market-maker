"""Keep GitHub research rehearsal read-only and never cross Demo/Prod venues."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from live import nba_trade


@pytest.mark.parametrize(
    "env,data,host",
    [
        (
            "prod",
            "https://external-api.kalshi.com/trade-api/v2",
            "https://api.elections.kalshi.com",
        ),
        (
            "prod",
            "https://api.elections.kalshi.com/trade-api/v2",
            "https://external-api.kalshi.com",
        ),
        (
            "demo",
            "https://demo-api.kalshi.co/trade-api/v2",
            "https://demo-api.kalshi.co",
        ),
    ],
)
def test_accepts_host_aliases_within_same_venue(monkeypatch, env, data, host):
    monkeypatch.setattr(nba_trade, "market_data_base_url", lambda: data)
    nba_trade.verify_execution_venue(SimpleNamespace(env=env, base=host))


@pytest.mark.parametrize(
    "env,data,host",
    [
        (
            "demo",
            "https://external-api.kalshi.com/trade-api/v2",
            "https://demo-api.kalshi.co",
        ),
        (
            "prod",
            "https://demo-api.kalshi.co/trade-api/v2",
            "https://api.elections.kalshi.com",
        ),
        (
            "prod",
            "https://evil.invalid/trade-api/v2",
            "https://api.elections.kalshi.com",
        ),
    ],
)
def test_refuses_cross_venue_or_unknown_hosts(monkeypatch, env, data, host):
    monkeypatch.setattr(nba_trade, "market_data_base_url", lambda: data)
    with pytest.raises(nba_trade.TradingError, match="different venues"):
        nba_trade.verify_execution_venue(SimpleNamespace(env=env, base=host))


def test_scheduled_rehearsals_are_always_dry_and_have_no_secrets():
    repo = Path(__file__).resolve().parents[1]
    for name in ("trade-dry-run.yml", "trade-dry-run-nfl.yml"):
        workflow = (repo / ".github" / "workflows" / name).read_text()
        assert "TRADE_MODE: dry" in workflow
        assert "KALSHI_ENV: prod" in workflow
        assert "secrets." not in workflow
