"""Serialize production workers sharing the primary account on this host."""

import fcntl
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def account_lock():
    with Path("/home/trader/production-execution.lock").open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
