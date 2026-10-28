"""Install an isolated paper/cash observer while funded spread stays halted."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from deploy.repair_spread_export import PRODUCTION, STUDY, install_candidate
from research.spread_forward_recorder import STATE, policy
from research.spread_forward_core import digest
from research.spread_paper_recorder import FILES, HOME, cycle

TAG = "# spread-paper-execution-v1"
EXPORT_BASE = "6088edd9c49358771d86e44ff6cf9561bf639821cae38d8d3eec87c97a07069a"


def cron(prior, command):
    lines = [line for line in prior.splitlines() if not line.endswith(TAG)]
    return "\n".join(lines + [command + " " + TAG]) + "\n"


def main():
    os.umask(0o077)
    if os.getuid() == 0 or Path.home() != Path("/home/trader"):
        raise ValueError("existing_trader_user_required")
    policy()
    stop = STATE / "KILL"
    if stop.is_symlink() or not stop.is_file():
        raise ValueError("funded_spread_pause_required")
    frozen = (STUDY / "manifest.json").read_bytes()
    manifest = json.loads(frozen)
    if (
        manifest["start"] != "2026-10-25T21:47:54.024216+00:00"
        or manifest["end"] != "2026-11-24T21:47:54.024216+00:00"
    ):
        raise ValueError("unexpected_frozen_window")
    frozen_sources = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (STUDY / "code/research").glob("spread_forward*.py")
    }
    if not frozen_sources:
        raise ValueError("original_observer_missing")
    if (
        digest({p.name: h for p, h in frozen_sources.items()})
        != "72d4d3951bbbf0de89c018c62e530ecc635e85e03c0d6240dc09d0ceee32800a"
    ):
        raise ValueError("original_observer_identity_changed")
    source = Path(__file__).resolve().parents[1]
    HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (HOME / "STOP").exists():
        raise ValueError("paper_study_stopped")
    active = HOME / "code"
    if active.exists():
        if any(
            (active / "research" / name).read_bytes()
            != (source / "research" / name).read_bytes()
            for name in FILES
        ):
            raise ValueError("new_paper_study_version_required")
    elif (HOME / "manifest.json").exists():
        raise ValueError("paper_release_missing")
    else:
        active.symlink_to(source, target_is_directory=True)
    prior = subprocess.run(["crontab", "-l"], text=True, capture_output=True)
    if prior.returncode not in (0, 1) or (
        prior.returncode == 1 and "no crontab for" not in prior.stderr.lower()
    ):
        raise ValueError("crontab_read_failed")
    install_candidate(
        source / "tools/export_private_fills.py",
        PRODUCTION / "tools/export_private_fills.py",
        HOME / "exporter-before-paper.py",
        expected_old=EXPORT_BASE,
    )
    python = PRODUCTION / ".venv/bin/python"
    command = f"* * * * * cd {active} && {python} -m research.spread_paper_recorder > /dev/null 2>&1"
    subprocess.run(
        ["crontab", "-"], input=cron(prior.stdout, command), text=True, check=True
    )
    cycle()
    if (STUDY / "manifest.json").read_bytes() != frozen or any(
        hashlib.sha256(p.read_bytes()).hexdigest() != h
        for p, h in frozen_sources.items()
    ):
        raise ValueError("original_study_changed")
    if not stop.is_file():
        raise ValueError("funded_pause_changed")
    health = json.loads((HOME / "health.json").read_text())
    print("PAPER_RESEARCH_STATE=" + health["state"])
    print("FUNDED_SPREAD_REMAINS_HALTED=PASS")
    print("FROZEN_STUDY_UNCHANGED=PASS")
    if health["state"] == "error":
        print(
            "PAPER_ERROR=" + str(health.get("error_code") or health.get("error_class"))
        )
        raise ValueError("paper_recorder_unhealthy")
    report = json.loads((HOME / "reconciliation.json").read_text())["report"]
    print("CASH_RECONCILIATION=" + report["status"])


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("PAUSED_RESEARCH_INSTALL_FAILED=" + type(error).__name__)
        raise SystemExit(1) from None
