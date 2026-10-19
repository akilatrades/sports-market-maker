"""Public profit screen must reject stale +P&L and keep negative settlements."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[1] / "dashboard" / "index.html"


def test_published_aggregate_is_polled_without_cache_and_stale_values_hidden(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("node unavailable")
    page = PAGE.read_text()
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", page, re.S)
    assert len(scripts) == 1
    source = scripts[0]
    start = source.index("function renderProductionPnl(")
    end = source.index("let latestDashboard = null;", start)
    assert start >= 0 and end > start
    bootstrap = source[start:end]
    script = tmp_path / "verify-public-pnl.cjs"
    script.write_text(
        """
const money = v => v < 0 ? "-$" + Math.abs(v).toFixed(2) : "$" + v.toFixed(2);
const esc = v => String(v);
"""
        + bootstrap
        + """
const nodes = {};
const documentStub = {
  getElementById(id) {
    return nodes[id] || (nodes[id] = {textContent:"",innerHTML:""});
  }
};
globalThis.document = documentStub;
let snapshot = {
  schema_version:1,
  as_of_utc:new Date(Date.now()-16*60*1000).toISOString(),
  markets:{
    nfl:{status:"verified_snapshot",settled_profit_dollars:1.99,settled_markets:2},
    nba:{status:"awaiting_first_order",settled_profit_dollars:null,settled_markets:0}
  }
};
renderProductionPnl(snapshot);
if (!nodes["live-pnl-grid"].innerHTML.includes("stale") ||
    nodes["live-pnl-grid"].innerHTML.includes("+\u00241.99")) {
  throw new Error("Stale positive P&L was still shown");
}
snapshot.as_of_utc = new Date().toISOString();
snapshot.markets.nfl.settled_profit_dollars = -1.50;
snapshot.markets.nfl.settled_markets = 3;
renderProductionPnl(snapshot);
if (!nodes["live-pnl-grid"].innerHTML.includes("-\u00241.50") ||
    !nodes["live-pnl-grid"].innerHTML.includes("negative")) {
  throw new Error("Current losing NFL settlement was not displayed");
}
console.log("stale-hidden / negative-settlement-displayed");
"""
    )
    result = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_page_repolls_public_pnl_once_per_minute():
    s = PAGE.read_text()
    assert "setInterval(refreshVerifiedPnl, 60000)" in s
    assert 'fetch("../outputs/dashboard/production_pnl.json", {cache:"no-store"})' in s
