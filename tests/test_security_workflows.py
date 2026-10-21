"""Guard against reintroducing the security regressions from October 2026."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
OWNER_ONLY = (
    "github.actor == 'akilatrades'",
    "github.triggering_actor == 'akilatrades'",
)


def _triggers(text):
    """The workflow's top-level ``on:`` block."""
    match = re.search(r"^on:\n(.*?)(?=^\S)", text, re.M | re.S)
    assert match, "workflow has no on: block"
    return match.group(1)


def _jobs(text):
    """Map job name -> that job's text (two-space-indented keys under jobs:)."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([A-Za-z0-9_-]+):\s*$", body, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


def test_server_secrets_only_reach_owner_run_main_branch_jobs():
    seen = 0
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        for name, job in _jobs(text).items():
            if "secrets.DROPLET_" not in job:
                continue
            seen += 1
            where = f"{workflow.name}:{name}"
            # The environment only releases its secrets to main (see
            # deploy/GITHUB_ACCESS.md); the job also refuses anyone else.
            assert "environment: funded-droplet" in job, where
            assert "github.ref == 'refs/heads/main'" in job, where
            for check in OWNER_ONLY:
                assert check in job, where
            triggers = _triggers(text)
            for unsafe in ("pull_request", "schedule:", "workflow_run"):
                assert unsafe not in triggers, where
    assert seen >= 5


def test_pull_request_workflows_get_no_secrets():
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        assert "pull_request_target" not in text, workflow.name
        if "pull_request" not in _triggers(text):
            continue
        used = set(re.findall(r"secrets\.([A-Z0-9_]+)", text)) - {"GITHUB_TOKEN"}
        assert not used, f"{workflow.name} exposes {sorted(used)} to pull requests"


def test_manual_credit_spending_workflows_are_owner_only():
    for name in ("bookline-backtest.yml", "odds-check.yml"):
        text = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        for check in OWNER_ONLY:
            assert check in text, name


def test_every_workflow_declares_token_permissions():
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        assert re.search(r"^permissions:", text, re.M), workflow.name


def test_owner_reviews_every_change():
    owners = (ROOT / ".github/CODEOWNERS").read_text(encoding="utf-8")
    assert re.search(r"^\* @akilatrades$", owners, re.M)


def test_retired_server_workflows_stay_removed():
    for name in ("legacy-runner-migration.yml", "stage-legacy-refresh.yml"):
        assert not (ROOT / ".github/workflows" / name).exists()


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
    assert (
        'python -m research.scan_markets list --skip-done --series "$SELECTED_SERIES"'
        in scan
    )


def test_sensitive_local_files_are_not_default_tracked():
    patterns = (ROOT / ".gitignore").read_text().splitlines()
    for entry in (".env", ".env.*", "*.pem", "*.key", "*.p8", "*.p12", "*.pfx"):
        assert entry in patterns


def test_private_account_dashboard_binds_to_loopback():
    source = (ROOT / "live/account_dashboard.py").read_text()
    assert '("127.0.0.1", args.port)' in source
