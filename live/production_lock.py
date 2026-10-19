"""Serialize production workers sharing the primary account on this host.

Wait for the other sport's scan instead of failing with BlockingIOError when
both systemd timers happen to start at the same instant. The OS releases the
advisory lock if a worker exits or crashes. The worker's systemd timeout
remains the upper bound on a stalled scan.
"""

import fcntl
from contextlib import contextmanager
from pathlib import Path

LOCK_PATH = Path("/home/trader/production-execution.lock")


@contextmanager
def account_lock():
    with LOCK_PATH.open("a+") as stream:
        # Blocking exclusive lock: two production scans serialize on one host.
        # LOCK_NB caused spurious failures when NFL and NBA fired together.
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
