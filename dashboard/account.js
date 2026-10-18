"use strict";
const AccountView = (() => {
  const finite = x => typeof x === "number" && Number.isFinite(x);
  const money = x => finite(x) ? new Intl.NumberFormat("en-US", {style:"currency", currency:"USD"}).format(x) : "—";
  const count = x => finite(x) ? new Intl.NumberFormat("en-US", {maximumFractionDigits:2}).format(x) : "—";
  const escape = x => String(x ?? "—").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const time = x => x && Number.isFinite(Date.parse(x)) ? new Date(x).toLocaleString([], {month:"short", day:"numeric", hour:"numeric", minute:"2-digit", timeZoneName:"short"}) : "Not available";
  function freshness(data, now=Date.now()) {
    const stamp = Date.parse(data?.updated_utc);
    if (!Number.isFinite(stamp)) return "unavailable";
    const age = now - stamp;
    return data.status === "ok" && age >= -30000 && age <= 180000 ? "live" : "stale";
  }
  const decisions = {exchange_accepted:"Order accepted by exchange",accepted:"Order accepted by exchange",unsafe_resting_canceled:"Unsafe resting orders withdrawn",no_eligible_candidates:"No eligible entries this scan",all_candidates_blocked:"Entries blocked by safety checks",availability_cancellation:"Unsafe resting orders withdrawn"};
  const reasons = {game_budget:"Game allowance used",team_budget:"Team allowance used",active_exposure:"Active exposure limit",daily_submission_budget:"Daily submission allowance",lifetime_submission_budget:"Lifetime submission allowance",game_order_count:"Game order limit",insufficient_edge_after_fee_buffer:"Estimated edge below 3¢ after buffer",model_timestamp_missing_or_stale:"Missing or stale model timestamp",fresh_quote_check:"Quote changed before submission",invalid_order_or_price:"Invalid order or price",kickoff_cutoff:"Too close to kickoff",baseline_budget:"Baseline quote exceeds budget",invalid_probability:"Invalid probability"};
  function render(data, doc=document, now=Date.now()) {
    const node = id => doc.getElementById(id);
    const set = (id, value) => { node(id).textContent = value; };
    const state = freshness(data, now);
    node("connection").className = "connection " + state;
    set("connection", state === "live" ? "● Production connected" : state === "stale" ? "Snapshot stale" : "Not connected");
    set("updated", data.updated_utc ? "Account snapshot: " + time(data.updated_utc) : "No production snapshot loaded");
    node("connect-help").hidden = state !== "unavailable";
    node("notice").className = "notice " + (state === "live" ? "ok" : "warning");
    set("notice", state === "live" ? "Connected to production. Account snapshots refresh every 60 seconds. Profit below includes settled positions from the selected strategy only." : state === "stale" ? "The account feed is stale or unavailable. Values shown are from the last successful snapshot; do not treat them as current." : "No verified production data is available. Missing balances are shown as —, never as zero.");
    const a = data.account || {}, s = data.strategy || {};
    set("cash", money(a.cash_dollars)); set("value", money(a.position_value_dollars)); set("equity", money(a.equity_dollars));
    set("profit", money(s.settled_profit_dollars));
    node("profit").className = finite(s.settled_profit_dollars) ? (s.settled_profit_dollars < 0 ? "negative" : "positive") : "";
    set("settled-note", !finite(s.settled_markets) ? "Waiting for verified settlement accounting" : s.settled_markets === 0 ? "No settled strategy markets yet" : !finite(s.settled_profit_dollars) ? "Settlement cost or fee data incomplete" : `${count(s.settled_markets)} settled markets · after reported fees · all entry versions`);
    set("accepted", count(s.accepted_orders)); set("filled", count(s.filled_orders)); set("contracts", count(s.contracts_filled));
    set("fill-cost", money(s.fill_cost_dollars)); set("fees", money(s.fill_fees_dollars)); set("resting", count(a.resting_orders));
    set("budget", money(s.remaining_submission_budget_dollars));
    node("budget-bar").value = s.submitted_reserved_dollars ?? 0;
    node("budget-bar").max = s.submission_limit_dollars ?? 50;
    node("budget-bar").hidden = !finite(s.submitted_reserved_dollars);
    set("version", s.name || "Strategy data unavailable");
    const positions = Array.isArray(data.positions) ? data.positions : null;
    set("position-count", positions ? `${positions.length} open markets` : "Awaiting connection");
    node("positions-body").innerHTML = !positions ? '<tr><td colspan="5" class="empty">Connect to load open positions.</td></tr>' : !positions.length ? '<tr><td colspan="5" class="empty">No open positions reported by the exchange.</td></tr>' : positions.map(p => `<tr><td>${escape(p.player)}${p.player !== p.ticker ? `<small>${escape(p.ticker)}</small>` : ""}<small>${p.owned ? escape(p.strategy_version) : "Outside selected strategy"}</small></td><td><span class="pill">${escape(p.side)}</span></td><td>${count(p.contracts)}</td><td>${money(p.cost_dollars)}</td><td>${escape(p.probability_source)}</td></tr>`).join("");
    const orders = Array.isArray(data.orders) ? data.orders : null;
    node("orders-list").innerHTML = !orders ? "Connect to load resting orders." : !orders.length ? "No resting orders reported by the exchange." : orders.map(o => `<div class="order-row"><span>${escape(o.player)}<small>${o.owned ? "NFL · buy NO" : "Outside selected strategy"}</small></span><span class="order-amount">${count(o.contracts)} × ${money(o.price_dollars)}</span></div>`).join("");
    const scan = data.scan;
    const scanAge = scan?.run_utc ? now - Date.parse(scan.run_utc) : Infinity;
    set("scan-title", data.kill_switch ? "Kill switch is active" : scan ? decisions[scan.decision] || "Scan status available" : "No scan loaded");
    set("scan-stamp", scan ? `${time(scan.run_utc)}${scanAge > 300000 ? " · Scan is over 5 minutes old; trader status unknown." : " · Last completed scan; account freshness is separate."}` : "A recent account snapshot does not prove the trader is running.");
    const filters = scan?.filters || {};
    const summary = [["Open markets scanned",filters.open_markets],["Within entry window",filters.in_entry_window],["Passed model / book check",filters.passed_book_or_model_and_spread]];
    const skips = Object.entries(scan?.skip_reasons || {}).sort((a,b) => b[1]-a[1]);
    node("scan-details").innerHTML = [...summary.filter(([,v]) => finite(v)), ...skips.map(([k,v]) => [reasons[k] || k.replaceAll("_"," "),v])].map(([label,v]) => `<div><span>${escape(label)}</span><b>${count(v)}</b></div>`).join("");
    if (s.unconfirmed_intents > 0 || data.kill_switch) {
      node("notice").className = "notice warning";
      set("notice", s.unconfirmed_intents > 0 ? "An order submission lacks a confirmed receipt. Automatic entries must remain halted until the exchange is reconciled." : "The production kill switch is present. Review outstanding orders and positions in Kalshi.");
    }
  }
  return {money,count,escape,freshness,render};
})();
if (typeof module !== "undefined") module.exports = AccountView;
if (typeof window !== "undefined") {
  let previous = null, busy = false;
  const local = ["127.0.0.1","localhost"].includes(location.hostname);
  async function refresh() {
    if (busy) return;
    if (!local) {
      AccountView.render({status:"unavailable"});
      document.getElementById("notice").textContent = "This public page contains no account balances. Open the private server view below to see your production account.";
      return;
    }
    busy = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch("/api/account", {cache:"no-store",signal:controller.signal});
      if (!response.ok) throw new Error("Account snapshot unavailable");
      const data = await response.json();
      if (data.schema_version !== 1 || data.environment !== "production") throw new Error("No production account snapshot");
      previous = data;
      AccountView.render(data);
    } catch (_) {
      AccountView.render({...previous,status:"error"});
    } finally { clearTimeout(timer); busy = false; }
  }
  document.getElementById("refresh").addEventListener("click", refresh);
  refresh();
  setInterval(refresh,60000);
  setInterval(() => { if (previous && AccountView.freshness(previous) === "stale") AccountView.render(previous); },15000);
}
