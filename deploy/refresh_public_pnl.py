"""Refresh only the owned, read-only public reporting process over pinned SSH.

The existing systemd unit restarts on an unhandled SIGUSR1. This needs no root
permissions and cannot start a stopped unit. A pidfd pins the verified process
identity. No bot timers, journals, environment files or trading APIs are touched.
"""

import json
import os
import pwd
import signal
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

UNIT = "market-maker-live-pnl.service"
COMMAND = [
    "/home/trader/sports-market-maker-prod-auto/.venv/bin/python",
    "-m",
    "live.public_pnl_feed",
    "--port",
    "8766",
    "--interval",
    "30",
]


def service():
    result = subprocess.run(
        [
            "systemctl",
            "show",
            UNIT,
            "--no-pager",
            "--property=MainPID,User,ActiveState,SubState,Restart,"
            "SuccessExitStatus,RestartPreventExitStatus",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=8,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def validate(state, pid, owner, expected_owner, command, handled):
    required = {
        "User": "trader",
        "ActiveState": "active",
        "SubState": "running",
        "Restart": "on-failure",
        "SuccessExitStatus": "",
        "RestartPreventExitStatus": "",
    }
    if any(state.get(key) != value for key, value in required.items()):
        raise RuntimeError("Unexpected reporting service configuration")
    if pid <= 1 or str(pid) != state.get("MainPID"):
        raise RuntimeError("Reporting process identity changed")
    if owner != expected_owner or command != COMMAND or handled:
        raise RuntimeError("Reporting process identity or signal policy mismatch")


def main():
    owner = pwd.getpwnam("trader").pw_uid
    if os.geteuid() != owner:
        raise RuntimeError("Run as the unprivileged trader user")
    state = service()
    pid = int(state.get("MainPID", "0"))
    if pid <= 1:
        raise RuntimeError("The reporting service is not running")
    fd = os.pidfd_open(pid)
    try:
        proc = Path("/proc") / str(pid)
        command = proc.joinpath("cmdline").read_bytes().decode().strip("\0").split("\0")
        status = dict(
            line.split(":", 1)
            for line in proc.joinpath("status").read_text().splitlines()
            if ":" in line
        )
        bit = 1 << (signal.SIGUSR1 - 1)
        handled = (int(status["SigCgt"], 16) | int(status["SigIgn"], 16)) & bit
        validate(state, pid, proc.stat().st_uid, owner, command, handled)
        validate(service(), pid, proc.stat().st_uid, owner, command, handled)
        signal.pidfd_send_signal(fd, signal.SIGUSR1)
    finally:
        os.close(fd)
    print("Public reporting process refresh requested; trading controls untouched")
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        current = service()
        if current.get("ActiveState") == "active" and current.get("MainPID") != str(pid):
            try:
                with urlopen("http://127.0.0.1:8766/v1/pnl", timeout=5) as response:
                    report = json.load(response)
                spread = report.get("markets", {}).get("spread", {})
                if spread.get("status") == "verified_fill_ledger":
                    print(
                        json.dumps(
                            {
                                "status": "REPORTING_REFRESH_VERIFIED",
                                "spread_status": "verified_fill_ledger",
                                "as_of_utc": report.get("as_of_utc"),
                                "spread_realized_profit_dollars": spread.get(
                                    "realized_profit_dollars"
                                ),
                            }
                        )
                    )
                    return
            except (OSError, ValueError):
                pass
        time.sleep(3)
    raise RuntimeError("Reporting refresh requested but verified P&L not yet available")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Reporting refresh did not verify: {type(error).__name__}")
        raise SystemExit(1) from None
