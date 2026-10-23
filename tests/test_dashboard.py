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
        "production-pnl",
        "live-pnl-grid",
        "checkpoints",
        "strategies",
        "prop-maker",
        "prop-rules",
        "spread-maker",
        "spread-metrics",
        "spread-rules",
        "research-section",
        "scan",
        "risk",
        "account-limits",
        "study-chart",
    ):
        assert section in parser.ids
    for label in ("Exchange-confirmed", "NFL", "NBA", "Spread maker", "in-sample"):
        assert label.lower() in page.lower()
    # Panels that could never fill in, or repeated others, stay removed, and
    # the page never reads research-runner P&L as if it were live.
    for retired in ("hero-metrics", "forward-view", "system-view", "exchange-watch"):
        assert retired not in parser.ids
    for field in ("realized_total", "s.live", "live_nfl", "forward_validation"):
        assert field not in page
    # The P&L note keeps every exclusion the live feed declares.
    for caveat in (
        "unrealized positions",
        "non-settlement exits",
        "credits",
        "archived",
    ):
        assert caveat in page


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


def _run_dashboard_js(tmp_path, exercise):
    """Run the dashboard script up to its first fetch, then ``exercise``."""
    if not shutil.which("node"):
        pytest.skip("Node.js is not installed in this environment")
    harness = tmp_path / "harness.cjs"
    harness.write_text(
        """
const fs = require("fs");
const vm = require("vm");
const html = fs.readFileSync(process.argv[2], "utf8");
const source = html.match(/<script>([\\s\\S]*?)<\\/script>/)[1];
const bootstrap = source.split('fetch("../outputs/dashboard/summary.json"')[0];
const nodes = {};
const document = {getElementById(id) { return nodes[id] || (nodes[id] = {innerHTML: "", style: {}, textContent: ""}); }};
vm.runInNewContext(bootstrap + fs.readFileSync(process.argv[3], "utf8"), {document, nodes, console});
"""
    )
    script = tmp_path / "exercise.js"
    script.write_text(exercise)
    result = subprocess.run(
        ["node", str(harness), str(DASHBOARD), str(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_checkpoints_count_days_and_never_claim_progress_they_cannot_see(tmp_path):
    _run_dashboard_js(
        tmp_path,
        """
const html = () => nodes["checkpoints"].innerHTML;
checkpoints(new Date("2026-10-20T12:00:00Z"));
if ((html().match(/Not started/g) || []).length !== 2) throw new Error("future start shown as running");
checkpoints(new Date("2026-10-25T12:00:00Z"));
if (!html().includes("Day 5 of 30") || !html().includes("Day 3 of 28")) throw new Error(html());
checkpoints(new Date("2027-01-01T00:00:00Z"));
if (!html().includes("Review due (30 days)") || !html().includes('aria-valuenow="28"')) throw new Error(html());
// Only elapsed days: no fill counts or P&L, which the public page cannot verify.
if (/[+−-]\\$|so far|contracts filled|P&amp;L/.test(html())) throw new Error("checkpoint invented progress");
""",
    )


def test_rules_panels_fill_from_code_and_admit_missing_data(tmp_path):
    _run_dashboard_js(
        tmp_path,
        """
runningNow({});
for (const id of ["prop-rules", "spread-rules"]) {
  if (!nodes[id].innerHTML.includes("Rules not in this snapshot")) throw new Error(id + " hid missing rules");
}
if (nodes["account-limits"].textContent) throw new Error("account stops invented");
const r = {
  nba_rules: "nba-no-v5", contracts_per_order: 1, entry_edge_cents: [0, 15],
  entry_hours_before_tip: [2, 6], price_band_cents: [5, 95], nba_max_open: 150,
  nba_max_daily: 150, nba_max_game: 25, nba_max_lifetime: 2000, account_max_open: 165,
  account_daily_loss_stop: 20, account_total_loss_stop: 60,
  spread: {rules: "spread-maker-v2-pregame", contracts_per_order: 5, max_net_per_market_side: 5,
    min_spread_cents: 8, hours_before_expiration: [4, 7], min_lead_minutes: 85,
    cancel_lead_minutes: 20, series: 64, max_open: 60, daily_loss_stop: 10,
    total_loss_stop: 40, order_lifetime_minutes: 65}
};
runningNow({running_now: r});
const prop = nodes["prop-rules"].innerHTML, spread = nodes["spread-rules"].innerHTML;
if (!prop.includes("1 contract, post-only NO") || !prop.includes("2–6 h before tip-off")) throw new Error(prop);
runningNow({running_now: {...r, contracts_per_order: 3}});
if (!nodes["prop-rules"].innerHTML.includes("Up to 3 contracts, post-only NO")) throw new Error("caps can shrink an order");
runningNow({running_now: r});
if (!spread.includes("New quotes 85+ min before; all cancelled 20 min before")) throw new Error(spread);
if (!spread.includes("Up to 5 contracts a side, 65-minute expiry")) throw new Error(spread);
const account = nodes["account-limits"].textContent;
if (!account.includes("after $20") || !account.includes("after $60")) throw new Error("account stops missing");
// The $165 cap covers NBA and NFL only; the spread maker has its own.
if (!account.includes("NBA and NFL share a $165 cap") || !account.includes("spread maker has its own $60")) throw new Error(account);
// An older summary without the v2 start margins still says what the rule is.
delete r.spread.min_lead_minutes;
runningNow({running_now: r});
if (!nodes["spread-rules"].innerHTML.includes("Only before a known start")) throw new Error("v2 rule not stated");
delete r.spread.order_lifetime_minutes; delete r.spread.daily_loss_stop;
runningNow({running_now: r});
const partial = nodes["spread-rules"].innerHTML;
if (/undefined|NaN|−—|short expiry/.test(partial)) throw new Error(partial);
""",
    )


def test_running_now_publishes_v2_start_margins_and_account_stops():
    from live import spread_policy
    from live.shared_account_risk import ACCOUNT_LOSS_STOPS
    from live.summarize import running_now

    r = running_now()
    assert r["spread"]["min_lead_minutes"] == spread_policy.MIN_LEAD_MINUTES
    assert r["spread"]["cancel_lead_minutes"] == spread_policy.CANCEL_LEAD_MINUTES
    assert r["account_daily_loss_stop"] == ACCOUNT_LOSS_STOPS["daily"]
    assert r["account_total_loss_stop"] == ACCOUNT_LOSS_STOPS["cumulative"]


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
if (nodes["spread-metrics"].innerHTML.includes("both halves")) throw new Error("both halves claimed without the earlier half");
spreadSection({spread_research: {all: {cents: 2.44, fills: 76694, profit_factor: 1.22}, earlier: {cents: 3.07}, later: {cents: 1.7, t: 7.8}}});
if (!nodes["spread-metrics"].innerHTML.includes("positive in both halves")) throw new Error("both halves not shown");
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
