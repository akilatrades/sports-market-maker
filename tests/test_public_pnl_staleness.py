"""An expired public result must clear even when its next request fails."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_auto_refresh_clears_expired_result_when_network_fails():
    if shutil.which("node") is None:
        pytest.skip("node unavailable")
    result = subprocess.run(
        [
            "node",
            "-e",
            r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
let now = Date.parse('2026-10-25T20:00:00Z');
let fail = false;
const nodes = {};
const intervals = [];
const requests = [];
const data = {
  schema_version: 1,
  refresh_type: 'signed_live_account_settlements_30s',
  as_of_utc: new Date(now).toISOString(),
  markets: {spread: {status:'verified_fill_ledger',
    realized_profit_dollars:-1.5,filled_contracts:10,settled_markets:3}}
};
class Clock extends Date { static now() { return now; } }
const context = {
  Date: Clock, URL, AbortController, setTimeout, clearTimeout,
  setInterval: (fn, ms) => { intervals.push({fn, ms}); },
  document: {
    hidden: false,
    addEventListener() {},
    getElementById(id) {
      return nodes[id] ||= {textContent:'',dataset:{},addEventListener(){}};
    }
  },
  fetch: async (url, options) => {
    requests.push({url, options});
    if (fail) throw Error('offline');
    return {ok:true, json:async () => url.endsWith('live-pnl-source.json')
      ? {api_url:'https://feed.example/v1/pnl'} : data};
  }
};
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  vm.runInNewContext(fs.readFileSync('dashboard/spread.js','utf8'), context);
  await flush();
  assert.equal(nodes['spread-pnl'].textContent, '−$1.50');
  assert.equal(nodes['contracts'].textContent, '10');
  assert.equal(intervals.length, 1);
  assert.equal(intervals[0].ms, 15000);
  now += 91000;
  fail = true;
  intervals[0].fn();
  assert.equal(nodes['spread-pnl'].textContent, '—');
  assert.equal(nodes['contracts'].textContent, '—');
  assert.equal(nodes['feed-status'].textContent, 'Update delayed');
  await flush();
  assert.equal(nodes['spread-pnl'].textContent, '—');
  assert.equal(nodes['feed-status'].textContent, 'Update unavailable');
  for (const request of requests) {
    assert.equal(request.options.cache, 'no-store');
    assert.equal(request.options.credentials, 'omit');
    assert.ok(['./live-pnl-source.json','https://feed.example/v1/pnl']
      .includes(request.url));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
""",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
