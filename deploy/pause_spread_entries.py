"""Set the spread-only stop switch; verify with GETs, never start a worker."""

import fcntl
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

STATE = Path("/home/trader/prod-spread-auto")
PRODUCTION = Path("/home/trader/sports-market-maker-prod-auto")
STUDY = Path("/home/trader/spread-forward-study")
REVISION = "fe7a5e7a8cfff8eeb5018d5d047f549f8a7f7cbd"
OBSERVER_HASH = "72d4d3951bbbf0de89c018c62e530ecc635e85e03c0d6240dc09d0ceee32800a"


def utcnow():
    return datetime.now(UTC).isoformat()


def set_stop(path):
    """Preserve existing owner halts; never follow a link or clear a stop."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("invalid_existing_stop_file") from None
        return False
    with os.fdopen(fd, "w") as handle:
        handle.write("Owner requested a pause of funded spread entries.\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def wait_idle(lock_path, timeout=300):
    """Drain an already-running pass so no submission can trail verification."""
    fd = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(fd, "r+") as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("current_pass_not_finished") from None
                time.sleep(1)


def owned_ids(journal):
    identities = set()
    with journal.open() as handle:
        for line in handle:
            if not line.endswith("\n"):
                raise ValueError("incomplete_journal")
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event") == "accepted" and row.get("order_id"):
                identities.add(str(row["order_id"]))
    return identities


def owned_resting(rows, identities):
    result = []
    for row in rows:
        if not row.get("order_id") or row.get("status") != "resting":
            raise ValueError("invalid_resting_order_response")
        if str(row["order_id"]) in identities or str(
            row.get("client_order_id") or ""
        ).startswith("smm-spread-"):
            result.append(row)
    return result


def readonly_client():
    root = STUDY / "code/research"
    files = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.glob("spread_forward_*.py"))
    }
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(encoded).hexdigest() != OBSERVER_HASH:
        raise ValueError("unreviewed_readonly_client")
    sys.path.insert(0, str(root.parent))
    from research.spread_forward_recorder import (
        ENVIRONMENT,
        ReadOnlyAPI,
        environment,
    )

    return ReadOnlyAPI(environment(ENVIRONMENT))


def main():
    os.umask(0o077)
    if os.getuid() == 0 or Path.home() != Path("/home/trader"):
        raise ValueError("existing_trader_user_required")
    if STATE.is_symlink() or not STATE.is_dir() or STATE.stat().st_uid != os.getuid():
        raise ValueError("unexpected_spread_state_directory")
    revision = subprocess.check_output(
        ["git", "-C", str(PRODUCTION), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != REVISION:
        raise ValueError("unreviewed_worker_revision")
    subprocess.run(
        [
            "git",
            "-C",
            str(PRODUCTION),
            "diff",
            "--quiet",
            "HEAD",
            "--",
            "live/prod_spread_auto.py",
            "live/spread_policy.py",
        ],
        check=True,
    )
    frozen = (STUDY / "manifest.json").read_bytes()
    requested = utcnow()
    set_stop(STATE / "KILL")
    print("SPREAD_STOP_SWITCH=present", flush=True)
    wait_idle(STATE / "lock")
    if not (STATE / "KILL").is_file() or (STATE / "KILL").is_symlink():
        raise ValueError("stop_switch_changed")
    paused = utcnow()
    print("NEW_SPREAD_ENTRIES_HALTED=PASS", flush=True)
    print("PAUSE_VERIFIED_UTC=" + paused, flush=True)
    # Stop evidence lives outside the frozen observer. The original cohort's
    # dates/identity stay intact; final analysis must disclose this interruption.
    evidence = {
        "requested_utc": requested,
        "entries_halted_verified_utc": paused,
        "reason": "owner_requested_pause_pending_edge_validation",
        "production_revision": revision,
        "existing_positions_not_closed": True,
        "original_study_window_unchanged": True,
    }
    path = STATE / "owner-pause.json"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps(evidence, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    api = readonly_client()
    identities = owned_ids(STATE / "journal.jsonl")
    # The already-scheduled worker sees KILL and only cancels its owned quotes.
    # Do not start, restart, arm or directly invoke a trading/cancel worker here.
    deadline = time.monotonic() + 720
    while True:
        try:
            rows = api.pages("/portfolio/orders", "orders", {"status": "resting"})
            clear = not owned_resting(rows, identities)
        except Exception:
            clear = False
        if clear:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("resting_order_clearance_not_verified")
        print("WAITING_FOR_SCHEDULED_CANCEL_OR_EXPIRY", flush=True)
        time.sleep(20)
    if (STUDY / "manifest.json").read_bytes() != frozen:
        raise ValueError("study_manifest_changed")
    print("RESTING_SPREAD_ORDERS_CLEAR=PASS")
    print("EXISTING_POSITIONS_NOT_CLOSED=PASS")
    print("FROZEN_STUDY_UNCHANGED=PASS")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print account data, responses, credentials or exception text.
        print("SPREAD_PAUSE_INCOMPLETE=" + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None
