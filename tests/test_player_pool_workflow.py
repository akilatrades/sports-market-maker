"""The player-pool workflow: what it may read, write and push."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / ".github/workflows/player-pool-page.yml").read_text("utf-8")
HEAD, _, BODY = TEXT.partition("\njobs:\n")
JOBS = dict(re.findall(r"^  (\w+):\n((?:(?:    .*)?\n)+)", BODY, re.M))


def test_it_has_three_jobs_and_no_secrets():
    assert set(JOBS) == {"check", "stats", "prices"}
    assert "secrets." not in TEXT
    assert "pull_request_target" not in TEXT


def test_it_starts_after_projections_and_never_on_a_push():
    triggers = HEAD[HEAD.index("\non:\n") : HEAD.index("\npermissions:")]
    assert 'workflows: ["projections"]' in triggers
    assert "workflow_dispatch:" in triggers
    assert not re.search(r"^  push:", triggers, re.M)
    # A few early starts for the watcher; nothing here runs on a tight clock.
    crons = re.findall(r'cron: "(\d+) (\d+) \* \* \*"', triggers)
    assert len(crons) == len(re.findall(r"cron:", triggers)) == 3


def test_only_the_two_publishing_jobs_can_write():
    assert re.search(r"^permissions:\n  contents: read\n", TEXT, re.M)
    assert "contents: write" not in JOBS["check"]
    assert "github.event_name == 'pull_request'" in JOBS["check"]
    for name in ("stats", "prices"):
        assert "contents: write" in JOBS[name]
        assert "if: github.event_name != 'pull_request'" in JOBS[name]
        assert "cancel-in-progress: false" in JOBS[name]


def test_stats_adds_two_files_to_main():
    job = JOBS["stats"]
    assert re.findall(r"git add (.+)", job) == [
        "outputs/player_pool/latest.json outputs/pickem_forward/summary.json"
    ]
    # The pick'em forward check reads committed files and cannot stop the job.
    assert 'python -m research.pickem_forward || echo "::warning::' in job
    assert (ROOT / "outputs/pickem_forward/summary.json").exists()
    assert "--data-only" in job
    assert "--force" not in job


def test_prices_pushes_only_to_its_own_branch():
    job = JOBS["prices"]
    pushes = re.findall(r"git push (.+?)(?: \\)?\n", job)
    assert pushes == ['--quiet --force origin "$commit:refs/heads/player-pool-live"']
    for word in ("git add", "git commit -m", "git pull", "main"):
        assert word not in job, word
    # The quotes file is never committed to main by accident either.
    ignored = (ROOT / ".gitignore").read_text("utf-8").splitlines()
    assert "/outputs/player_pool/kalshi_quotes.json" in ignored


def test_the_stat_model_pass_cannot_stop_the_quotes():
    job = JOBS["prices"]
    assert "python -m live.fetch_nba_data" in job
    model = re.search(
        r"timeout (\d+) python -m research\.player_pool_model .*\\\n\s+\|\| echo", job
    )
    assert model and int(model.group(1)) <= 900
    # Both files go out in the same single commit.
    assert "for name in kalshi_quotes.json model.json; do" in job
    ignored = (ROOT / ".gitignore").read_text("utf-8").splitlines()
    assert "/outputs/player_pool/model.json" in ignored


def test_the_watcher_stops_itself_before_github_stops_it():
    job = JOBS["prices"]
    loop = int(re.search(r"SECONDS \+ (\d+) \* 60", job).group(1))
    limit = int(re.search(r"timeout-minutes: (\d+)", job).group(1))
    pause = int(re.search(r"sleep (\d+)", job).group(1))
    assert loop + 10 <= limit < 360
    assert 120 <= pause <= 600  # every few minutes, not a hammer
    assert 'if [ "$status" -eq 3 ]; then break; fi' in job


def test_the_page_reads_the_files_this_workflow_writes():
    page = (ROOT / "research/nba_player_pool_dashboard.template.html").read_text(
        "utf-8"
    )
    assert '"../outputs/player_pool/latest.json"' in page
    assert "/sports-market-maker/player-pool-live/model.json" in page
    # The watcher still publishes Kalshi's quotes beside the model file, but
    # the page no longer reads them: Kalshi is left to the bot.
    assert "kalshi_quotes.json" not in page


def test_the_watcher_starts_the_line_workflows_about_every_10_minutes():
    """GitHub runs the line workflows' own schedules only a few times a day,
    so the page's sportsbook and app times went stale (owner, 2026-11-23)."""
    job = JOBS["prices"]
    starts = re.findall(r"gh workflow run (\S+)", job)
    assert starts == ["books.yml", "pickem-lines.yml"]
    # Only the cheap scope: games within 6.5 hours of tip-off.
    assert "gh workflow run books.yml -f scope=near" in job
    gap = int(re.search(r"\$\(\(SECONDS - lines\)\) -ge (\d+)", job).group(1))
    assert 10 * 60 <= gap <= 30 * 60  # 10 minutes since 2026-11-23, was 20
    # A failed start never stops the watcher.
    assert job.count('|| echo "::warning::could not start') == 2
    # The token is this run's own, given to that step only, and may start
    # workflows but nothing more.
    assert job.count("GH_TOKEN: ${{ github.token }}") == 1
    perms = re.search(r"permissions:\n((?:      .*\n)+)", job).group(1)
    granted = re.findall(r"^      (\w[\w-]*): (\w+)", perms, re.M)
    assert granted == [("contents", "write"), ("actions", "write")]


def test_watcher_started_pickem_pulls_keep_the_gap():
    text = (ROOT / ".github/workflows/pickem-lines.yml").read_text("utf-8")
    assert "github.triggering_actor == 'github-actions[bot]'" in text
    # Only the owner's own button skips the gap.
    forced = re.findall(r"if \[\[ (.+) \]\]; then flag=\"--force\"; fi", text)
    assert forced == ['"$EVENT" == workflow_dispatch && "$BY" == akilatrades'] * 2
    assert "secrets.ODDS_API_KEY" in text  # only the pull step, as before
    books = (ROOT / ".github/workflows/books.yml").read_text("utf-8")
    assert "workflow_dispatch:" in books and "- near" in books
