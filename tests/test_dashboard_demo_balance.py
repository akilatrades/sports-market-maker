"""The public spread display must fail closed on invalid or stale accounting."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_spread_dashboard_data_contract():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    subprocess.run([node, str(ROOT / "tests/spread_dashboard.cjs")], check=True)


def test_no_private_or_hypothetical_results_in_public_page():
    html = (ROOT / "dashboard/index.html").read_text()
    script = (ROOT / "dashboard/spread.js").read_text()
    for forbidden in ("DEMO_REFERENCE", 'src="account.js"', 'id="paper"'):
        assert forbidden not in html
    for forbidden in ("account.settled", "markets.nba", "markets.nfl", "summary.json"):
        assert forbidden not in script
