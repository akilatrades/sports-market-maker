"""Refresh legacy paper/demo *data*, never executable code, without git pull.

The old once-per-minute runner used to rebase its own checkout from main on
EVERY scan, making a research log commit into an unsupervised code deployment.
Instead, sync only source-stamped, checksum-validated NBA projections and
bounded sportsbook snapshots on a 10-minute cadence. Funded-account workers
already use the separate live.nba_inputs pipeline and are not affected.

This module does not place, cancel, or read private Kalshi account orders.
"""
from datetime import UTC, datetime
from pathlib import Path

from live.nba_inputs import REPOSITORY, atomic_write, download, sync

STAMP = Path("/home/trader/.cache/smm-legacy-input-refresh")
INTERVAL_SECONDS = 600


def refresh(now=None, root=Path("."), stamp=STAMP):
    """Return whether a data-only refresh happened; failure means no trading pass."""
    now = now or datetime.now(UTC)
    stamp = Path(stamp)
    root = Path(root)
    if stamp.exists():
        try:
            recorded = datetime.fromisoformat(stamp.read_text())
            age = (now - recorded).total_seconds()
        except (OSError, ValueError, TypeError):
            age = float("inf")
        # A clock jump or malformed stamp is not proof of fresh data.
        if 0 <= age < INTERVAL_SECONDS:
            return False

    projection_dir = root / "outputs/projections"
    # Reads one immutable GitHub commit, verifies projection timestamp, row
    # count, checksum and model version, and never touches source code.
    meta = sync(projection_dir, now)
    sha = meta["source_commit"]
    base = f"https://raw.githubusercontent.com/{REPOSITORY}/{sha}/outputs/books"
    book_dir = root / "outputs/books"
    for sport in ("nba", "nfl"):
        if sport == "nba":
            data = (projection_dir / "nba_books.csv").read_bytes()
        else:
            try:
                data = download(f"{base}/nfl_latest.csv")
            except Exception:
                data = b""
        dest = book_dir / f"{sport}_latest.csv"
        if data:
            atomic_write(dest, data)
        else:
            # Do not mistake yesterday's odds for current books.
            dest.unlink(missing_ok=True)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(stamp, now.isoformat().encode())
    return True


if __name__ == "__main__":
    refresh()
