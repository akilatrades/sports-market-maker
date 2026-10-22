"""Dashboard contract tests: data classification, resilient missing values, and JS syntax."""

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from live.summarize import live_status


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard" / "index.html"


class Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])


def test_dashboard_has_unique_essential_sections_and_education():
    page = DASHBOARD.read_text()
    parser = Ids()
    parser.feed(page)
    assert len(parser.ids) == len(set(parser.ids))
    for section in (
        "overview",
        "forward",
        "production-pnl",
        "live-pnl-grid",
        "risk",
        "research-section",
        "methodology",
        "study-chart",
        "hero-metrics",
        "forward-view",
        "system-view",
        "live",
    ):
        assert section in parser.ids
    for label in ("Exchange-confirmed", "Volume capture", "NFL", "NBA"):
        assert label.lower() in page.lower()


def test_dashboard_inline_javascript_parses(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node.js is not installed in this environment")
    page = DASHBOARD.read_text()
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", page, re.S)
    assert len(scripts) == 1
    script = tmp_path / "dashboard.js"
    script.write_text(scripts[0])
    result = subprocess.run(
        ["node", "--check", str(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_overview_never_invents_live_profit_when_no_exchange_data(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node.js is not installed in this environment")
    harness = tmp_path / "smoke.cjs"
    harness.write_text(
        """
const fs = require("fs");
const vm = require("vm");
const html = fs.readFileSync(process.argv[2], "utf8");
const source = html.match(/<script>([\\s\\S]*?)<\\/script>/)[1];
const bootstrap = source.split('fetch("../outputs/dashboard/summary.json"')[0];
const nodes = {};
const document = {
  getElementById(id) {
    return nodes[id] || (nodes[id] = {innerHTML: "", style: {}});
  }
};
const exercise = `
overview({live: {}, live_nfl: {}, limits: {max_open: 150}});
if (!nodes["hero-metrics"].innerHTML.includes("—") ||
    !nodes["forward-view"].innerHTML.includes("Not started")) {
  throw new Error("Missing data was not represented honestly");
}
overview({live: {mode: "dry", realized_total: 9}, live_nfl: {realized_total: 7}});
if (nodes["hero-metrics"].innerHTML.includes("$9.00") ||
    nodes["hero-metrics"].innerHTML.includes("$16.00")) {
  throw new Error("Research or separate-market totals became NBA live performance");
}
overview({
  live: {forward_validation: {
    status: "collecting", eligible_real_orders: 8,
    settled_buy_fill_events: 2, elapsed_days: 3,
    capture_volume_weighted: 0.32, qualifying_contracts: 25,
    settled_contracts: 3, cents_per_settled_contract: -2.5
  }},
  live_nfl: {},
  limits: {max_open: 150, max_order: 5, max_per_game: 25}
});
if (!nodes["hero-metrics"].innerHTML.includes("32%") ||
    !nodes["forward-view"].innerHTML.includes("2 / 1,900")) {
  throw new Error("Forward evidence not displayed correctly");
}
`;
vm.runInNewContext(bootstrap + exercise, {document, nodes, console});
"""
    )
    result = subprocess.run(
        ["node", str(harness), str(DASHBOARD)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_live_summary_uses_published_validation_not_fake_zeros(tmp_path):
    assert "forward_validation" not in live_status(tmp_path)
    expected = {
        "status": "collecting",
        "eligible_real_orders": 12,
        "settled_buy_fill_events": 4,
        "capture_volume_weighted": 0.34,
        "cents_per_settled_contract": -2.1,
    }
    (tmp_path / "forward_validation.json").write_text(json.dumps(expected))
    assert live_status(tmp_path)["forward_validation"] == expected


def test_invalid_validation_file_is_declared_not_silently_successful(tmp_path):
    (tmp_path / "forward_validation.json").write_text("{invalid")
    output = live_status(tmp_path)
    assert "forward_validation" not in output
    assert output.get("forward_validation_error")


def test_public_profit_file_contains_only_verified_market_aggregates():
    data = json.loads((ROOT / "outputs/dashboard/production_pnl.json").read_text())
    assert data["schema_version"] == 1
    assert {"nfl", "nba"} <= set(data["markets"]) <= {"nfl", "nba", "spread"}
    assert data["refresh_type"] in {
        "manual_verified_snapshot_not_real_time",
        "automated_signed_aggregate_snapshot_not_real_time",
    }
    for name, market in data["markets"].items():
        if name == "spread":  # realized from its own fills, not settlements
            amount = market["realized_profit_dollars"]
            if market["status"] == "verified_fill_ledger":
                assert isinstance(amount, (int, float))
            else:
                assert amount is None
        elif market["status"] == "verified_snapshot":
            assert isinstance(market["settled_profit_dollars"], (int, float))
        else:
            assert market["settled_profit_dollars"] is None
    assert data["as_of_utc"]
    assert not any(key in data for key in ("paper", "ledgers", "balance", "api_keys"))
    assert all(
        "balance" not in key and "order_id" not in key and "token" not in key
        for market in data["markets"].values()
        for key in market
    )


def test_spread_maker_card_shows_only_verified_fresh_results(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node.js is not installed in this environment")
    page = DASHBOARD.read_text()
    assert 'id="spread-maker"' in page and 'id="spread-metrics"' in page
    assert "Spread maker / realized P&amp;L" in page
    harness = tmp_path / "spread.cjs"
    harness.write_text(
        """
const fs = require("fs");
const vm = require("vm");
const html = fs.readFileSync(process.argv[2], "utf8");
const source = html.match(/<script>([\\s\\S]*?)<\\/script>/)[1];
const bootstrap = source.split('fetch("../outputs/dashboard/summary.json"')[0];
const nodes = {};
const document = {getElementById(id) { return nodes[id] || (nodes[id] = {innerHTML: "", style: {}, textContent: ""}); }};
const exercise = `
const now = new Date().toISOString();
const base = {schema_version: 1, refresh_type: "signed_live_account_settlements_30s", as_of_utc: now};
renderProductionPnl({...base, markets: {spread: {status: "verified_fill_ledger", realized_profit_dollars: 0.5, filled_contracts: 10}}});
if (!nodes["live-pnl-grid"].innerHTML.includes("+$0.50")) throw new Error("verified spread P&L not shown");
renderProductionPnl({...base, markets: {spread: {status: "awaiting_first_fill", realized_profit_dollars: null, exchange_accepted_orders: 4}}});
if (!nodes["live-pnl-grid"].innerHTML.includes("4 orders accepted")) throw new Error("waiting state not shown");
renderProductionPnl({...base, as_of_utc: "2026-01-01T00:00:00Z", markets: {spread: {status: "verified_fill_ledger", realized_profit_dollars: 9.99}}});
if (nodes["live-pnl-grid"].innerHTML.match(/metric-value[^>]*>\\+\\$9\\.99/)) throw new Error("stale spread P&L shown as current");
renderProductionPnl({...base, markets: {spread: {status: "unreconciled", realized_profit_dollars: 3}}});
if (nodes["live-pnl-grid"].innerHTML.includes("$3.00")) throw new Error("unreconciled spread P&L shown");
spreadSection({});
if (!nodes["spread-metrics"].innerHTML.includes("not in this snapshot")) throw new Error("missing research not declared");
spreadSection({spread_research: {all: {cents: 2.44, fills: 76694, profit_factor: 1.22}, later: {cents: 1.7, t: 7.8}}, running_now: {spread: {contracts_per_order: 5, max_open: 60}}});
if (!nodes["spread-metrics"].innerHTML.includes("+2.44")) throw new Error("research not shown");
`;
vm.runInNewContext(bootstrap + exercise, {document, nodes, console});
"""
    )
    result = subprocess.run(
        ["node", str(harness), str(DASHBOARD)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
