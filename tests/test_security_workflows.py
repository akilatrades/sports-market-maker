"""Guard against reintroducing the security regressions from October 2026."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_kalshi_trading_credentials_in_github_actions():
    workflows = ROOT / ".github" / "workflows"
    for workflow in workflows.glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        assert "secrets.KALSHI_PRIVATE_KEY" not in text, workflow.name
        assert "secrets.KALSHI_KEY_ID" not in text, workflow.name


def test_dispatch_parameters_are_passed_as_data_not_shell_code():
    backtest = (ROOT / ".github/workflows/bookline-backtest.yml").read_text()
    assert "type: choice" in backtest
    assert "REQUESTED_COMMAND: ${{ inputs.command }}" in backtest
    assert 'python -m research.bookline_backtest "$REQUESTED_COMMAND"' in backtest
    scan = (ROOT / ".github/workflows/scan.yml").read_text()
    assert "SELECTED_SERIES: ${{ inputs.series }}" in scan
    assert 'python -m research.scan_markets list --skip-done --series "$SELECTED_SERIES"' in scan


def test_sensitive_local_files_are_not_default_tracked():
    patterns = (ROOT / ".gitignore").read_text().splitlines()
    for entry in (".env", ".env.*", "*.pem", "*.key", "*.p8", "*.p12", "*.pfx"):
        assert entry in patterns


def test_private_account_dashboard_binds_to_loopback():
    source = (ROOT / "live/account_dashboard.py").read_text()
    assert '("127.0.0.1", args.port)' in source
