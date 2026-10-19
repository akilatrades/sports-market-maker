"""The two production timers must queue behind a single account lock."""

import threading
from concurrent.futures import ThreadPoolExecutor

from live import production_lock


def test_second_sport_waits_instead_of_crashing(monkeypatch, tmp_path):
    monkeypatch.setattr(production_lock, "LOCK_PATH", tmp_path / "account.lock")
    trying = threading.Event()
    acquired = threading.Event()

    def competing_scan():
        trying.set()
        with production_lock.account_lock():
            acquired.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with production_lock.account_lock():
            future = executor.submit(competing_scan)
            assert trying.wait(2)
            assert not acquired.wait(0.15)
        assert acquired.wait(3)
        future.result(timeout=3)
