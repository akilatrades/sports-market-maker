"use strict";
const assert = require("node:assert/strict");
const {classify, endpoint, money, count} = require("../dashboard/spread.js");
const now = Date.parse("2026-10-25T20:00:00Z");
const base = {schema_version: 1, refresh_type: "signed_live_account_settlements_30s", as_of_utc: new Date(now).toISOString(), markets: {
  spread: {status: "verified_fill_ledger", realized_profit_dollars: 17.0486, filled_contracts: 102.59, settled_markets: 21},
  nba: {settled_profit_dollars: 999}, nfl: {settled_profit_dollars: 888}
}, account: {settled_profit_dollars: 777}};
assert.equal(classify(base, now).item.realized_profit_dollars, 17.0486);
assert.equal(money(17.0486), "+$17.05");
assert.equal(money(-1.23), "−$1.23");
assert.equal(money(0), "$0.00");
assert.equal(count(102.59), "102.59");
for (const x of [null, undefined, "0", NaN, Infinity, -1]) assert.equal(count(x), "—");
for (const value of [null, "17.05", NaN, Infinity, undefined]) {
  assert.equal(classify({...base, markets:{spread:{...base.markets.spread, realized_profit_dollars:value}}}, now).state,"unavailable");
}
for (const status of ["unreconciled", "unavailable", "awaiting_first_fill", "verified_snapshot"]) {
  const view=classify({...base,markets:{spread:{...base.markets.spread,status}}},now);
  assert.equal(view.state,"unavailable"); assert.equal(view.item,undefined);
}
assert.equal(classify({...base,markets:{nba:base.markets.nba}},now).state,"unavailable");
for (const as_of_utc of ["garbage", "2026-10-25T20:00:00", null]) assert.equal(classify({...base,as_of_utc},now).state,"unavailable");
for (const delta of [-91_000, 61_000]) assert.equal(classify({...base,as_of_utc:new Date(now+delta).toISOString()},now).state,"stale");
assert.equal(classify(base,now+90_000).state,"verified");
assert.equal(classify(base,now+90_001).item,undefined);
for (const change of [{schema_version:2},{status:"unavailable"},{refresh_type:"manual_verified_snapshot_not_real_time"}]) assert.equal(classify({...base,...change},now).state,"unavailable");
for (const api_url of ["http://example.com", "https://user:password@example.com", "javascript:alert(1)", ""]) assert.throws(()=>endpoint({api_url}));
assert.equal(endpoint({api_url:"https://example.com/v1/pnl"}),"https://example.com/v1/pnl");
console.log("Spread display: verified values, fees, missing data, freshness and HTTPS passed");
