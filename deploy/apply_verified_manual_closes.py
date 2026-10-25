"""Owner-console application of the verified manual-close repair; never resume.

This root-owned, hash-checked entry point runs repository code ONLY as trader.
Private logs stay under /root. Signed reads use the existing systemd environment.
"""

import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

BASE = "0500b006d5d223bb2accef32ca265f931c98fcbe"
TARGET = "fe7a5e7a8cfff8eeb5018d5d047f549f8a7f7cbd"
ROOT = Path("/home/trader/sports-market-maker-prod-auto")
HOME = Path("/home/trader")
TIMERS = tuple(f"market-maker-prod-{s}-auto.timer" for s in ("nba", "nfl", "spread"))
SERVICES = tuple(
    f"market-maker-prod-{s}-auto.service" for s in ("nba", "nfl", "spread")
)
ALLOWED = {
    "live/shared_account_risk.py",
    "live/external_spread_closes.py",
    "tools/account_reconciliation_snapshot.py",
    "tools/reconcile_external_spread_closes.py",
    "tools/stage_verified_manual_closes.py",
    "tests/test_external_spread_closes.py",
    "tests/test_reconcile_external_spread_closes.py",
    "tests/test_stage_verified_manual_closes.py",
}
HASHES = {
    "live/shared_account_risk.py": "d89f074a92f7d9266b70e4127acc8fa5f9f5a2423a7d4fce99e1566bddbbb07f",
    "live/external_spread_closes.py": "e5631858d653cc151b5c858856ef27e7978639a3e484f03845469b806be51318",
    "tools/account_reconciliation_snapshot.py": "211ac1f328c1629f7a31b4d2dd99010dfcb4740c54923df47b81f5f8713bc013",
    "tools/reconcile_external_spread_closes.py": "6497251472835d353d0293e7d7bd4a4cdee9f394d37eb4d099e537e1f4a23579",
}
ENV = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/home/trader",
    "PYTHONNOUSERSITE": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
}


def checked(command):
    return (
        subprocess.run(command, check=True, capture_output=True, env=ENV, cwd="/")
        .stdout.decode()
        .strip()
    )


def git(*args):
    return checked(["runuser", "-u", "trader", "--", "git", "-C", str(ROOT), *args])


def systemctl(action, *args, check=True):
    if action not in ("show", "is-active", "is-enabled", "disable"):
        raise ValueError("No service start or risk-changing control permitted")
    result = subprocess.run(
        ["systemctl", action, *args],
        check=False,
        capture_output=True,
        text=True,
        env=ENV,
        cwd="/",
    )
    if check and result.returncode:
        raise ValueError("Service control check failed")
    return result.stdout.strip()


def validate_stage(path):
    stage = Path(path)
    if (
        stage.parent != HOME
        or not re.fullmatch(r"recon-stage\.[A-Za-z0-9_]+", stage.name)
        or stage.resolve() != stage
    ):
        raise ValueError("Invalid private stage")
    if not stage.is_dir() or stage.stat().st_mode & 0o077:
        raise ValueError("Stage must remain private")
    for relative, expected in HASHES.items():
        source = stage / relative
        if (
            source.is_symlink()
            or hashlib.sha256(source.read_bytes()).hexdigest() != expected
        ):
            raise ValueError("Staged source integrity check failed")
    results = list((stage / "evidence").glob("result-*.json"))
    if len(results) != 1:
        raise ValueError("Exactly one verified dry-run result required")
    result = json.loads(results[0].read_text())
    confirmation = json.loads((stage / "confirmation.json").read_text())
    if (
        result.get("positions_verified") is not True
        or result.get("safe_to_resume") is not False
    ):
        raise ValueError("Private plan was not verified")
    if len(result.get("events_to_append", [])) != len(
        confirmation["normalized_fill_sha256"]
    ):
        raise ValueError("Private confirmation disagrees with plan")
    return stage


def allowed_diff(paths):
    if not paths or not set(paths) <= ALLOWED:
        raise ValueError("Unexpected change outside the reviewed repair")


def publish(stage, result):
    code = 'import json,os,sys; p=sys.argv[1]; fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600); f=os.fdopen(fd,"w"); json.dump(json.load(sys.stdin),f); f.write("\\n"); f.close()'
    path = stage / ("root-status-" + uuid.uuid4().hex + ".json")
    subprocess.run(
        [
            "runuser",
            "-u",
            "trader",
            "--",
            "/usr/bin/python3",
            "-I",
            "-c",
            code,
            str(path),
        ],
        input=json.dumps(result).encode(),
        check=True,
        capture_output=True,
        env=ENV,
        cwd="/",
    )


def main():
    state = {
        "status": "HALTED_NO_RESTART",
        "timers_paused": False,
        "code_updated": False,
        "journal_verified": False,
        "workers_restarted": 0,
    }
    stage = None
    logdir = None
    try:
        if os.geteuid() != 0:
            raise ValueError("Root console required")
        os.umask(0o077)
        self_path = Path(__file__).resolve()
        if (
            self_path.parent != Path("/root")
            or self_path.stat().st_uid != 0
            or self_path.stat().st_mode & 0o022
        ):
            raise ValueError("Use a root-owned immutable helper copy")
        helper_hash = hashlib.sha256(self_path.read_bytes()).hexdigest()
        pointer = HOME / ("reconciliation-active-" + helper_hash[:12] + ".json")
        if pointer.is_symlink():
            raise ValueError("Invalid case pointer")
        case = json.loads(pointer.read_text())
        if (
            set(case) != {"stage", "helper_sha256"}
            or case["helper_sha256"] != helper_hash
        ):
            raise ValueError("Helper identity does not match the prepared case")
        stage = validate_stage(case["stage"])
        head = git("rev-parse", "HEAD")
        if head not in (BASE, TARGET):
            raise ValueError("Unexpected deployed revision")
        if git(
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "live",
            "kalshi",
            "markets",
            "tools",
        ):
            raise ValueError("Production code is not clean")
        for unit in (*TIMERS, *SERVICES):
            if systemctl("show", unit, "-p", "LoadState", "--value") != "loaded":
                raise ValueError("Expected production unit unavailable")
        private_root = Path("/root/reconciliation")
        if private_root.is_symlink():
            raise ValueError("Invalid log directory")
        private_root.mkdir(mode=0o700, exist_ok=True)
        logdir = private_root / uuid.uuid4().hex
        logdir.mkdir(mode=0o700)
        lock_fd = os.open(
            "/run/lock/smm-production-release.lock",
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(lock_fd, "a+") as lock:
            if os.fstat(lock.fileno()).st_uid != 0:
                raise ValueError("Release lock must be root-owned")
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            systemctl("disable", "--now", *TIMERS)
            state["timers_paused"] = True
            deadline = time.monotonic() + 260
            for unit in SERVICES:
                while systemctl("is-active", unit, check=False) not in (
                    "inactive",
                    "failed",
                ):
                    if time.monotonic() > deadline:
                        raise ValueError("Worker did not become idle")
                    time.sleep(2)
            git(
                "fetch",
                "--quiet",
                "--no-tags",
                "origin",
                "fix/verified-manual-spread-closes",
            )
            allowed_diff(git("diff", "--name-only", BASE, TARGET).splitlines())
            git("checkout", "--detach", "--quiet", TARGET)
            state["code_updated"] = True
            for relative, expected in HASHES.items():
                if (
                    hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                    != expected
                ):
                    raise ValueError("Deployed source integrity check failed")
            before = set((stage / "evidence").glob("result-*.json"))
            command = [
                "systemd-run",
                "--quiet",
                "--wait",
                "--pipe",
                "--collect",
                "--uid=trader",
                "-p",
                f"WorkingDirectory={ROOT}",
                "-p",
                "EnvironmentFile=/etc/market-maker-prod-nba-auto.env",
                "-p",
                "Environment=OPENBLAS_NUM_THREADS=1",
                "-p",
                "Environment=OMP_NUM_THREADS=1",
                "-p",
                "NoNewPrivileges=true",
                "-p",
                "MemoryMax=512M",
                str(ROOT / ".venv/bin/python"),
                "-m",
                "tools.reconcile_external_spread_closes",
                "apply",
                "--confirmation",
                str(stage / "confirmation.json"),
                "--evidence-dir",
                str(stage / "evidence"),
            ]
            fd = os.open(
                logdir / "apply.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(fd, "wb") as log:
                subprocess.run(
                    command, check=True, stdout=log, stderr=log, env=ENV, cwd="/"
                )
            after = set((stage / "evidence").glob("result-*.json")) - before
            if (
                len(after) != 1
                or json.loads(after.pop().read_text()).get("positions_verified")
                is not True
            ):
                raise ValueError("Repair result was not verified")
            for timer in TIMERS:
                if (
                    systemctl("is-active", timer, check=False) != "inactive"
                    or systemctl("is-enabled", timer, check=False) != "disabled"
                ):
                    raise ValueError("Timer did not remain off")
            state.update(
                status="RECONCILIATION_APPLIED_NO_RESTART", journal_verified=True
            )
    except Exception as error:
        state["reason_class"] = type(error).__name__
        if isinstance(error, ValueError):
            state["reason"] = str(error)
        if logdir is not None:
            with (logdir / "error.txt").open("x") as handle:
                handle.write(str(error))
    if logdir is not None:
        with (logdir / "status.json").open("x") as handle:
            json.dump(state, handle)
    if stage is not None:
        try:
            publish(stage, state)
        except Exception:
            state["status_publication_failed"] = True
    print(json.dumps(state, sort_keys=True))
    if not state["journal_verified"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
