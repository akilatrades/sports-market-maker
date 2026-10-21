"""One-time, unprivileged, atomic legacy-runner auto-pull migration.

Only switches the exact historical minute-runner git pull to a data-only
input refresh. No systemd, Kalshi, environment, funded-checkout, or journal
mutation. Existing shell invocations keep using the old open file descriptor;
the next invocation sees the atomically replaced script.
"""

import hashlib
import os
import stat
import tempfile
from pathlib import Path

ROOT = Path("/home/trader/sports-market-maker")
RUNNER = Path("/home/trader/run.sh")
OLD = "git pull -q --rebase origin main || true"
NEW = ".venv/bin/python -m live.legacy_input_sync"


def migrate(root=ROOT, runner=RUNNER):
    """Verify exact old runner and atomic replacement, preserving permissions."""
    root = Path(root)
    runner = Path(runner)
    if not (root / "live/legacy_input_sync.py").is_file():
        raise RuntimeError("Reviewed data-only refresher is not installed")
    if runner.is_symlink() or not runner.is_file():
        raise RuntimeError("Runner path is missing or not a regular file")
    mode = runner.stat().st_mode
    if not stat.S_ISREG(mode) or runner.stat().st_uid != os.getuid():
        raise RuntimeError("Runner is not owned by the invoking account")

    before = runner.read_text(encoding="utf-8")
    if OLD not in before and NEW in before:
        return "already_migrated"
    if before.count(OLD) != 1 or NEW in before:
        raise RuntimeError("Unexpected runner contents; do not alter")
    if "cd /home/trader/sports-market-maker" not in before:
        raise RuntimeError("Unexpected runner working directory")
    after = before.replace(OLD, NEW, 1)
    backup = runner.with_name(runner.name + ".pre_data_sync.bak")
    if backup.exists():
        raise RuntimeError("Existing pre-migration backup requires inspection")

    # Back up first; write new content to a unique file in the same directory
    # and use an atomic rename so a one-minute timer never reads half a script.
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as backup_file:
        backup_file.write(before)
        backup_file.flush()
        os.fsync(backup_file.fileno())
    fd, temp_name = tempfile.mkstemp(prefix=".run-smm-", dir=runner.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(after)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp_name, stat.S_IMODE(mode))
        os.replace(temp_name, runner)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    digest = hashlib.sha256(after.encode()).hexdigest()[:12]
    print(f"LEGACY_AUTO_PULL_DISABLED: verified runner digest {digest}")
    return "migrated"


if __name__ == "__main__":
    migrate()
