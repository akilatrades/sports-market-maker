"""Keep staging incapable of activating funded trading or rewriting v3."""

import ast
from pathlib import Path

from live import prod_spread_v4 as worker

ROOT = Path(__file__).resolve().parents[1]


def test_stage_uses_only_the_read_only_execution_path():
    tree = ast.parse((ROOT / "deploy/stage_spread_v4.py").read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    client = next(
        n
        for n in calls
        if isinstance(n.func, ast.Name) and n.func.id == "TradingClient"
    )
    assert any(
        k.arg == "dry_run"
        and isinstance(k.value, ast.Constant)
        and k.value.value is True
        for k in client.keywords
    )
    preview = next(
        n
        for n in calls
        if isinstance(n.func, ast.Attribute) and n.func.attr == "run_once"
    )
    assert not any(k.arg in ("live", "authorize") for k in preview.keywords)
    assert not any(
        isinstance(n.func, ast.Attribute)
        and n.func.attr in ("place", "cancel", "unlink", "symlink_to")
        for n in calls
    )


def test_staging_workflow_never_installs_or_arms_a_service():
    text = (ROOT / ".github/workflows/spread-v4-candidate.yml").read_text()
    assert "-m deploy.stage_spread_v4" in text
    for forbidden in (
        "systemctl",
        "--live",
        "SPREAD_V4_ARM=YES",
        "setup_spread_maker",
        "smm-prod-release",
    ):
        assert forbidden not in text
    assert "set -eu; umask 077" in text
    assert "test ! -e '$release'" in text


def test_units_require_independent_gate_and_bound_runtime():
    service = (ROOT / "deploy/market-maker-spread-v4.service").read_text()
    timer = (ROOT / "deploy/market-maker-spread-v4.timer").read_text()
    assert "ConditionPathExists=/etc/market-maker-spread-v4.json" in service
    assert "WorkingDirectory=/home/trader/spread-v4/approved" in service
    assert "TimeoutStartSec=180" in service
    assert "ProtectSystem=strict" in service
    assert "OnUnitInactiveSec=30s" in timer


def test_release_digest_changes_for_imported_market_code(tmp_path):
    for folder in ("live", "kalshi", "research", "markets"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "one.py").write_text("a = 1\n")
    before = worker.source_digest(tmp_path)
    (tmp_path / "markets/one.py").write_text("a = 2\n")
    assert worker.source_digest(tmp_path) != before
