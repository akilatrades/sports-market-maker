"""Keep the public research evidence separate from account and scenario data."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard" / "index.html"


def test_public_research_has_no_private_account_or_demo_balance_panel():
    source = DASHBOARD.read_text()
    assert "DEMO_REFERENCE" not in source
    assert "Current Demo balance" not in source
    assert "ssh -N" not in source
    assert 'src="account.js"' not in source
    assert "HISTORICAL REPLAY" in source
    assert "not live performance" in source
    assert "Each strategy runs on a separate $500 paper bankroll" in source


@pytest.mark.parametrize(
    ("contracts", "edge", "expected_dollars"),
    [
        (0, 2.93, 0.0),
        (100, 2.93, 2.93),
        (300, 2.93, 8.79),
        (1000, 2.93, 29.30),
        (300, -5, -15.0),
        (300, 0, 0.0),
    ],
)
def test_scenario_math_uses_filled_contracts_not_deposit(
    tmp_path, contracts, edge, expected_dollars
):
    if not shutil.which("node"):
        pytest.skip("Node.js not installed")
    html = DASHBOARD.read_text()
    script = re.search(r"<script>(.*?)</script>", html, flags=re.S).group(1)
    extract = script.split('fetch("../outputs/dashboard/summary.json"')[0]
    harness = tmp_path / "scenario.cjs"
    harness.write_text(
        """
const vm = require("vm");
const fs = require("fs");
const source = fs.readFileSync(process.argv[2], "utf8");
const inline = source.match(/<script>([\\s\\S]*?)<\\/script>/)[1];
const code = inline.split('fetch("../outputs/dashboard/summary.json"')[0];
const input = {value: process.argv[3]};
const nodes = {
  "scenario-contracts": input,
  "scenario-count": {textContent:""},
  "scenario-loss": {textContent:""},
  "scenario-even": {textContent:""},
  "scenario-backtest": {textContent:""}
};
const document = {getElementById:(id) => nodes[id] || {innerHTML:"",style:{}}};
const exercise = [
  "const result = hypotheticalProfit(Number(" + JSON.stringify(process.argv[3]) +
  "), Number(" + JSON.stringify(process.argv[4]) + "));",
  "console.log(result);"
].join("\\n");
vm.runInNewContext(code + exercise, {document, console, Object});
""".strip()
        + "\n"
    )
    # Also ensure the source prefix actually contains the pure JS calculation.
    assert "function hypotheticalProfit(" in extract
    out = subprocess.run(
        ["node", str(harness), str(DASHBOARD), str(contracts), str(edge)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert float(out.stdout.strip()) == pytest.approx(expected_dollars, abs=1e-10)


def test_no_unverified_live_profit_is_invented():
    source = DASHBOARD.read_text()
    assert 'card("Realized P&L",realized==null?"—"' in source
    assert 'const realized=observed&&typeof live.realized_total==="number"' in source
    assert 'row("Missing observations","Unknown; never replaced with zero")' in source
