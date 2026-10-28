"""Install only an isolated research sidecar and the private reporting hook."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from deploy.repair_spread_export import PRODUCTION, REVISION, STUDY, install_candidate

HOME = Path("/home/trader/spread-entry-quality")
TAG = "# spread-entry-readonly-v1"
EXPORT_BASE = "e1dd5c37836b9d29e936c0a782370ca4794d2000bab86b778fdd88d22367cb66"
PYTHON = PRODUCTION / ".venv/bin/python"


def cron(existing, command):
    # Preserve every existing line, including the frozen observer's cron tag.
    lines = [line for line in existing.splitlines() if not line.endswith(TAG)]
    return "\n".join(lines + [command + " " + TAG]) + "\n"


def main():
    os.umask(0o077)
    if os.getuid() == 0 or Path.home() != Path("/home/trader"):
        raise ValueError("existing_trader_user_required")
    source = Path(__file__).resolve().parents[1]
    frozen = (STUDY / "manifest.json").read_bytes()
    manifest = json.loads(frozen)
    if (
        manifest["production_revision"] != REVISION
        or manifest["start"] != "2026-10-25T21:47:54.024216+00:00"
        or manifest["end"] != "2026-11-24T21:47:54.024216+00:00"
    ):
        raise ValueError("unexpected_frozen_study")
    if (
        subprocess.check_output(
            ["git", "-C", str(PRODUCTION), "rev-parse", "HEAD"], text=True
        ).strip()
        != REVISION
    ):
        raise ValueError("production_revision_changed")
    subprocess.run(
        [
            "git",
            "-C",
            str(PRODUCTION),
            "diff",
            "--quiet",
            "HEAD",
            "--",
            "live",
            "kalshi",
        ],
        check=True,
    )
    original_files = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (STUDY / "code/research").glob("spread_forward*.py")
    }
    if not original_files:
        raise ValueError("frozen_observer_source_missing")
    prior = subprocess.run(["crontab", "-l"], text=True, capture_output=True)
    if prior.returncode not in (0, 1) or (
        prior.returncode == 1 and "no crontab for" not in prior.stderr.lower()
    ):
        raise ValueError("crontab_read_failed")
    HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (HOME / "STOP").exists():
        raise ValueError("entry_study_is_stopped")
    active = HOME / "code"
    if active.exists():
        for name in (
            "spread_entry_recorder.py",
            "spread_entry_quality.py",
            "spread_forward_core.py",
            "spread_forward_recorder.py",
            "spread_forward_candidates.py",
        ):
            if (active / "research" / name).read_bytes() != (
                source / "research" / name
            ).read_bytes():
                raise ValueError("new_study_version_required")
    elif (HOME / "manifest.json").exists():
        raise ValueError("study_release_missing")
    else:
        active.symlink_to(source, target_is_directory=True)
    install_candidate(
        source / "tools/export_private_fills.py",
        PRODUCTION / "tools/export_private_fills.py",
        HOME / "exporter-before-entry-study.py",
        expected_old=EXPORT_BASE,
    )
    command = f"* * * * * cd {active} && {PYTHON} -m research.spread_entry_recorder > /dev/null 2>&1"
    subprocess.run(
        ["crontab", "-"], input=cron(prior.stdout, command), text=True, check=True
    )
    subprocess.run(
        [str(PYTHON), "-m", "research.spread_entry_recorder"],
        cwd=active,
        check=True,
        timeout=240,
    )
    if (STUDY / "manifest.json").read_bytes() != frozen or any(
        hashlib.sha256(p.read_bytes()).hexdigest() != h
        for p, h in original_files.items()
    ):
        raise ValueError("original_study_changed")
    health = json.loads((HOME / "health.json").read_text())
    print("ENTRY_RESEARCH_STATE=" + health["state"])
    print("FROZEN_STUDY_UNCHANGED=PASS")
    print("PRODUCTION_REVISION_UNCHANGED=PASS")
    if health["state"] not in ("recording", "settlement_followup", "complete"):
        print(
            "ENTRY_RESEARCH_ERROR="
            + str(health.get("error_code") or health.get("error_class"))
        )
        raise ValueError("research_not_healthy")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("ENTRY_RESEARCH_INSTALL_FAILED=" + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None
