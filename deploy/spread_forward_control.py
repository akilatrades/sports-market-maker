#!/usr/bin/env python3
"""Install/start/status only the unprivileged read-only observer."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HOME = Path("/home/trader/spread-forward-study")
PYTHON = "/home/trader/sports-market-maker-prod-auto/.venv/bin/python"
TAG = "# spread-forward-readonly-v1"
EXPORT_BASE = "992f885fc57a03ca92d6395ef0bde856a59fb73d0e691c65fa4fac2429aa08de"


def cron(existing, command):
    lines = [line for line in existing.splitlines() if not line.endswith(TAG)]
    return "\n".join(lines + ([command + " " + TAG] if command else [])) + "\n"


def install_export(source, target, backup):
    """Update only the data exporter, conditional on the reviewed source hash."""
    old, new = target.read_bytes(), source.read_bytes()
    if old == new:
        return
    if hashlib.sha256(old).hexdigest() != EXPORT_BASE:
        raise SystemExit("Private exporter differs from reviewed baseline")
    if not backup.exists():
        backup.write_bytes(old)
        backup.chmod(0o600)
    temporary = target.with_name(".export_private_fills.forward.tmp")
    temporary.write_bytes(new)
    temporary.chmod(target.stat().st_mode & 0o777)
    os.replace(temporary, target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "status", "stop"))
    args = parser.parse_args()
    os.umask(0o077)
    if os.getuid() == 0 or Path.home() != Path("/home/trader"):
        raise SystemExit("Observer must run as the existing trader user")
    HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
    active = HOME / "code"
    if args.action in ("start", "stop"):
        prior = subprocess.run(["crontab", "-l"], text=True, capture_output=True)
        if prior.returncode not in (0, 1) or (
            prior.returncode == 1 and "no crontab for" not in prior.stderr.lower()
        ):
            raise SystemExit("Cannot read existing user crontab safely")
        command = (
            f"* * * * * cd {active} && {PYTHON} -m "
            "research.spread_forward_recorder run > /dev/null 2>&1"
        )
        if args.action == "start":
            install_export(
                active / "tools/export_private_fills.py",
                Path("/home/trader/sports-market-maker-prod-auto")
                / "tools/export_private_fills.py",
                HOME / "exporter-before-study.py",
            )
            # Idempotent start never replaces the study manifest or resets dates.
            (HOME / "STOP").unlink(missing_ok=True)
        else:
            (HOME / "STOP").touch(mode=0o600)
        subprocess.run(
            ["crontab", "-"],
            input=cron(prior.stdout, command if args.action == "start" else None),
            text=True,
            check=True,
        )
        if args.action == "start":
            subprocess.Popen(
                [PYTHON, "-m", "research.spread_forward_recorder", "run"],
                cwd=active,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
    sys.path.insert(0, str(active))
    from research.spread_forward_recorder import status

    print("SPREAD_FORWARD_HEALTH=" + json.dumps(status(HOME), sort_keys=True))


if __name__ == "__main__":
    main()
