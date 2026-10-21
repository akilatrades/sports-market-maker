"""Guard against reintroducing the security regressions from October 2026."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
OWNER_ONLY = (
    "github.actor == 'akilatrades'",
    "github.triggering_actor == 'akilatrades'",
)
SERVER_JOB_CONDITIONS = ("github.ref == 'refs/heads/main'", *OWNER_ONLY)
# Triggers that could start a server job without the owner pressing the
# button: a merge (push), a schedule, a pull request or another workflow.
UNSAFE_SERVER_TRIGGERS = (
    "push",
    "pull_request",
    "pull_request_target",
    "schedule",
    "workflow_run",
    "workflow_call",
    "repository_dispatch",
)
# A job name, optionally quoted, optionally with a YAML anchor or comment.
JOB_HEADER = re.compile(
    r"^  ([\"']?)([A-Za-z0-9_-]+)\1:[ \t]*(?:&\S+)?[ \t]*(?:#.*)?$", re.M
)
SERVER_SECRET = re.compile(r"secrets\.droplet_", re.I)
DYNAMIC_SECRETS = re.compile(
    r"secrets\s*\[|tojson\(\s*secrets|secrets:\s*inherit", re.I
)


def _triggers(text):
    """The workflow's top-level ``on:`` block."""
    match = re.search(r"^on:\n(.*?)(?=^\S)", text, re.M | re.S)
    assert match, "workflow has no on: block"
    return match.group(1)


def _split_jobs(text):
    """(text before ``jobs:``, {job name: that job's text})."""
    head, sep, body = text.partition("\njobs:\n")
    assert sep, "workflow has no jobs: block"
    headers = list(JOB_HEADER.finditer(body))
    assert headers, "no jobs found"
    # Every two-space-indented line under jobs: must be a job name we
    # recognise; anything else could hide a job inside the one above it.
    for line in body.splitlines():
        if re.match(r"^  \S", line) and not line.lstrip().startswith("#"):
            assert JOB_HEADER.match(line), f"unrecognised job header: {line!r}"
    before = [ln for ln in body[: headers[0].start()].splitlines() if ln.strip()]
    assert all(ln.lstrip().startswith("#") for ln in before), "unparsed job text"
    jobs = {}
    for i, match in enumerate(headers):
        stop = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        jobs[match.group(2)] = body[match.end() : stop]
    return head, jobs


def _jobs(text):
    return _split_jobs(text)[1]


def _job_condition(job):
    """The job-level ``if:`` expression (four-space indent), folded to one line."""
    lines = job.splitlines()
    for i, line in enumerate(lines):
        match = re.match(r"^    if:\s*(.*)$", line)
        if not match:
            continue
        value = match.group(1).strip()
        if value in (">", ">-", ">+", "|", "|-", "|+"):
            block = []
            for following in lines[i + 1 :]:
                if following.strip() and not following.startswith("      "):
                    break
                block.append(following.strip())
            value = " ".join(block)
        return value.replace("${{", "").replace("}}", "").strip()
    return ""


def _required_conjuncts(expression):
    """Split on top-level ``&&``; a top-level ``||`` could bypass every check."""
    parts, depth, current, i = [], 0, "", 0
    while i < len(expression):
        char = expression[i]
        depth += char == "("
        depth -= char == ")"
        if depth == 0 and expression.startswith("||", i):
            raise AssertionError(f"top-level || in job condition: {expression}")
        if depth == 0 and expression.startswith("&&", i):
            parts.append(current.strip())
            current, i = "", i + 2
            continue
        current += char
        i += 1
    parts.append(current.strip())
    return parts


def test_secrets_are_always_named_explicitly():
    # secrets['X'], toJSON(secrets) and secrets: inherit would hide which
    # secrets a job reads from the checks below.
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        assert not DYNAMIC_SECRETS.search(text), workflow.name


def test_server_secrets_only_reach_owner_run_main_branch_jobs():
    seen = 0
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        head, jobs = _split_jobs(text)
        assert not SERVER_SECRET.search(head), f"{workflow.name}: workflow-level env"
        for name, job in jobs.items():
            if not SERVER_SECRET.search(job):
                continue
            seen += 1
            where = f"{workflow.name}:{name}"
            # The environment only releases its secrets to main (see
            # deploy/GITHUB_ACCESS.md); the job also refuses anyone else.
            assert re.search(r"^    environment: funded-droplet[ \t]*$", job, re.M), (
                where
            )
            conjuncts = _required_conjuncts(_job_condition(job))
            for check in SERVER_JOB_CONDITIONS:
                assert check in conjuncts, where
            triggers = _triggers(text)
            for unsafe in UNSAFE_SERVER_TRIGGERS:
                assert not re.search(rf"^\s+{unsafe}\b", triggers, re.M), where
    assert seen >= 5


def test_pull_request_workflows_get_no_secrets():
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        assert "pull_request_target" not in text, workflow.name
        if "pull_request" not in _triggers(text):
            continue
        found = re.findall(r"secrets\.([A-Za-z0-9_]+)", text, re.I)
        used = {name.upper() for name in found} - {"GITHUB_TOKEN"}
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
