"""Public dashboard must never mistake paper results for settled account P&L."""

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard" / "index.html"


def test_public_research_has_no_private_account_or_demo_balance_panel():
    source = DASHBOARD.read_text()
    assert "DEMO_REFERENCE" not in source
    assert "Current Demo balance" not in source
    assert "ssh -N" not in source
    assert 'src="account.js"' not in source
    assert "HISTORICAL REPLAY" in source
    assert "not live performance" in source


def test_hypothetical_profit_section_was_removed():
    html = DASHBOARD.read_text()
    assert 'id="production-pnl"' in html
    assert 'id="live-pnl-grid"' in html
    assert '"../outputs/dashboard/production_pnl.json"' in html
    for retired in (
        'id="paper"',
        'id="profit-scenarios"',
        'id="scenario-contracts"',
        "function hypotheticalProfit(",
        'id="strategy-summary"',
    ):
        assert retired not in html


@pytest.mark.parametrize("verified", [True, False])
def test_browser_production_pnl_uses_verified_snapshots_only(tmp_path, verified):
    if not shutil.which("node"):
        pytest.skip("Node.js is not available")
    harness = tmp_path / "check-live-pnl.cjs"
    harness.write_text(
        r"""
const fs = require("fs");
const vm = require("vm");
const html = fs.readFileSync(process.argv[2], "utf8");
const matched = html.match(/<script>([\s\S]*?)<\/script>/);
if (!matched) throw Error("Public dashboard has no inline script");
const script = matched[1];
const start = script.indexOf("function renderProductionPnl(");
const end = script.indexOf("let latestDashboard = null;", start);
if (start < 0 || end < 0) throw Error("No verified P&L renderer");
const nodes = {
  "live-pnl-grid": {innerHTML: ""},
  "live-pnl-asof": {textContent: ""}
};
const context = {
  input: JSON.parse(process.argv[3]),
  document: {getElementById: key => nodes[key]},
  esc: value => String(value),
  money: value => "$" + value.toFixed(2),
  Date, Number
};
vm.runInNewContext(
  script.slice(start, end) + "\nrenderProductionPnl(input);",
  context
);
console.log(JSON.stringify(nodes));
""".strip()
        + "\n"
    )
    report = (
        {
            "schema_version": 1,
            "as_of_utc": datetime.now(UTC).isoformat(),
            "markets": {
                "nfl": {
                    "status": "verified_snapshot",
                    "settled_profit_dollars": 1.99,
                    "settled_markets": 2,
                },
                "nba": {
                    "status": "awaiting_verified_report",
                    "settled_profit_dollars": None,
                },
            },
        }
        if verified
        else None
    )
    run = subprocess.run(
        ["node", str(harness), str(DASHBOARD), json.dumps(report)],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(run.stdout)
    pnl_html = data["live-pnl-grid"]["innerHTML"]
    assert "NFL / settled P&amp;L" in pnl_html
    assert "NBA / settled P&amp;L" in pnl_html
    assert "—" in pnl_html
    assert 'NBA / settled P&amp;L</span><div class="metric-value ">—' in pnl_html
    assert "$0.00" not in pnl_html
    if verified:
        assert "+$1.99" in pnl_html
        assert (
            "Last verified published snapshot" in data["live-pnl-asof"]["textContent"]
        )
    else:
        assert "$1.99" not in pnl_html
        assert (
            "Live account P&L feed unavailable" in data["live-pnl-asof"]["textContent"]
        )
