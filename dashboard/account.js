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
    set("notice", state === "live" ? "Connected to Kalshi production. NFL and NBA realized P&L use separate authenticated settlement records, not simulated ledgers." : state === "stale" ? "The account feed is stale or unavailable. Values shown are from the last successful snapshot; do not treat them as current." : "No verified production data is available. Missing balances are shown as —, never as zero.");
    const a = data.account || {}, s = data.strategy || {};
    set("cash", money(a.cash_dollars)); set("value", money(a.position_value_dollars)); set("equity", money(a.equity_dollars));
    const livePnl = data.live_pnl || {};
    [["nfl","profit","settled-note"],["nba","nba-profit","nba-settled-note"]].forEach(([key,amountId,noteId]) => {
      const cohort = livePnl[key] || {};
      const verified = cohort.status === "verified" && finite(cohort.settled_profit_dollars);
      // A failed/old account read cannot be represented as current green P&L.
      const show = state === "live" && verified;
      const profit = show ? cohort.settled_profit_dollars : null;
      set(amountId, money(profit));
      node(amountId).className = show ? (profit < 0 ? "negative" : "positive") : "";
      const note = state !== "live" ? "Account report stale or disconnected; current P&L hidden" :
        verified ? `${count(cohort.settled_markets)} verified settled markets · net of fees` :
        cohort.status === "incomplete_settlement" ? "Settlement accounting incomplete; P&L not reported" :
        cohort.status === "awaiting_first_order" ? "No live orders accepted yet" :
        cohort.status === "awaiting_settlement" ? "Live orders exist; awaiting completed settlements" :
        "No authenticated production report available";
      set(noteId, note);
    });
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
    node("orders-list").innerHTML = !orders ? "Connect to load resting orders." : !orders.length ? "No resting orders reported by the exchange." : orders.map(o => `<div class="order-row"><span>${escape(o.player)}<small>${o.owned ? escape(s.name || "Strategy buy NO") : "Outside selected strategy"}</small></span><span class="order-amount">${count(o.contracts)} × ${money(o.price_dollars)}</span></div>`).join("");
    const scan = data.scan;
    const scanAge = scan?.run_utc ? now - Date.parse(scan.run_utc) : Infinity;
    set("scan-title", data.kill_switch ? "Kill switch is active" : scan ? decisions[scan.decision] || "Scan status available" : "No scan loaded");
    set("scan-stamp", scan ? `${time(scan.run_utc)}${scanAge > 300000 ? " · Scan is over 5 minutes old; trader status unknown." : " · Last completed scan; account freshness is separate."}` : "A recent account snapshot does not prove the trader is running.");
    const filters = scan?.filters || {};
    const summary = [["Open markets scanned",filters.open_markets],["Within entry window",filters.in_entry_window],["Passed model / book check",filters.passed_book_or_model_and_spread]];
    const skips = Object.entries(scan?.skip_reasons || {}).sort((a,b) => b[1]-a[1]);
    node("scan-details").innerHTML = [...summary.filter(([,v]) => finite(v)), ...skips.map(([k,v]) => [reasons[k] || k.replaceAll("_"," "),v])].map(([label,v]) => `<div><span>${escape(label)}</span><b>${count(v)}</b></div>`).join("");
    const pilot = state === "live" ? data.nba_validation || {} : {};
    const pilotReady = ["collecting_live_outcomes", "30_day_review_due", "needs_exchange_reconciliation"].includes(pilot.status);
    const pilotStates = {
      awaiting_first_accepted_order:"Waiting for first accepted NBA order",
      awaiting_exchange_audit:"Authenticated NBA order history unavailable",
      incomplete_exchange_order_history:"NBA exchange order history incomplete",
      needs_exchange_reconciliation:"Some NBA orders require reconciliation",
      collecting_live_outcomes:"Live NBA observations · not proof of profitability",
      "30_day_review_due":"30-day checkpoint due · review results before increasing risk",
      invalid_or_unreconciled:"NBA journal validation unavailable"
    };
    set("nba-study-status", state !== "live" ? "Authenticated report unavailable or stale" : pilotStates[pilot.status] || "NBA validation report unavailable");
    set("nba-study-day", pilotReady && finite(pilot.days_elapsed) ? count(Math.min(30,pilot.days_elapsed+1)) : "—");
    set("nba-study-games", pilotReady ? count(pilot.independent_games_accepted) : "—");
    set("nba-study-filled-games", pilotReady ? count(pilot.independent_games_filled) : "—");
    set("nba-study-orders", pilotReady ? count(pilot.accepted_orders) : "—");
    set("nba-study-zero", pilotReady ? count(pilot.confirmed_zero_fill_orders) : "—");
    set("nba-study-fill-rate", pilotReady && finite(pilot.closed_order_fill_rate) ? (pilot.closed_order_fill_rate*100).toFixed(1) + "%" : "—");
    set("nba-study-maker", pilotReady && finite(pilot.maker_share) ? (pilot.maker_share*100).toFixed(1) + "%" : "—");
    set("nba-study-pnl", pilotReady ? money(pilot.settled_profit_dollars) : "—");
    set("nba-study-budget", pilotReady ? money(pilot.lifetime_allowance_remaining_dollars) : "—");
    set("nba-study-note", pilotReady
      ? "First accepted order: " + time(pilot.start_utc) + ". Review due: " + time(pilot.review_due_utc) +
        ". Filled-contract estimates are separate from net settlements. The $50 lifetime cap does not reset automatically."
      : "No complete, current NBA order audit. Missing or unsettled data never count as profit or confirmed zero fills.");
    const orderAudits = data.order_audit || {};
    const nflAudit = orderAudits.nfl || {}, nbaAudit = orderAudits.nba || {};
    const auditReady = state === "live" && nflAudit.status === "verified_snapshot" && nbaAudit.status === "verified_snapshot";
    const quality = data.execution_scorecard || {};
    const observed = ["nfl", "nba"].map(sport => ({sport, report: quality[sport] || {}}));
    node("execution-quality").innerHTML = observed.map(({sport,report}) => {
      if (state !== "live" || report.status !== "observed_not_backtested") {
        return `<div><span>${escape(sport.toUpperCase())} fill metrics</span><b>Not verified</b></div>`;
      }
      const percentage = x => finite(x) ? (100*x).toFixed(1) + "%" : "—";
      return `<div><span>${escape(sport.toUpperCase())} · closed-order fill rate</span><b>${escape(percentage(report.closed_order_fill_rate))}</b></div>
      <div><span>Maker share of verified filled contracts</span><b>${escape(percentage(report.maker_share))}</b></div>
      <div><span>Mean time to first fill</span><b>${finite(report.mean_minutes_to_first_fill) ? count(report.mean_minutes_to_first_fill) + " min" : "—"}</b></div>
      <div><span>Quote-time model edge on orders that filled (not profit)</span><b>${escape(percentage(report.model_estimated_net_edge_on_filled))}</b></div>`;
    }).join("");
    set("unfilled-nfl", auditReady ? count(nflAudit.confirmed_unfilled) : "—");
    set("unfilled-nba", auditReady ? count(nbaAudit.confirmed_unfilled) : "—");
    set("unfilled-unknown", auditReady ? count((nflAudit.unknown_or_unreconciled || 0) + (nbaAudit.unknown_or_unreconciled || 0)) : "—");
    const outstanding = ["nfl", "nba"].flatMap(sport => {
      const view = orderAudits[sport];
      return view?.status === "verified_snapshot" && Array.isArray(view.orders) ?
        view.orders.map(order => ({...order, sport})) : [];
    }).sort((a,b) => (b.submitted_utc || "").localeCompare(a.submitted_utc || ""));
    const orderLabels = {confirmed_unfilled:"Closed · 0 fills",resting_no_fill:"Resting · 0 fills",
      partially_filled_resting:"Resting · partial",partially_filled_closed:"Closed · partial",
      unconfirmed_unfilled:"Closed · unconfirmed",exchange_order_unavailable:"Missing from recent Kalshi history",
      unreconciled_fill_count:"Fill discrepancy",exchange_status_unknown:"Unknown exchange status",
      pending:"Pending exchange status", fully_filled:"Filled completely"};
    set("unfilled-note", !auditReady ? "Authenticated order audit unavailable or stale. No unfilled status is assumed." :
      `Kalshi order/fill history: NFL ${count(nflAudit.accepted_orders)} accepted, NBA ${count(nbaAudit.accepted_orders)} accepted. Displaying ${count(Math.min(outstanding.length, 50))} accepted orders, including historical complete and partial fills.`);
    node("unfilled-body").innerHTML = !auditReady ?
      '<tr><td colspan="6" class="empty">Exchange order history is unavailable or stale.</td></tr>' :
      !outstanding.length ? '<tr><td colspan="6" class="empty">No exchange-accepted orders recorded yet.</td></tr>' :
      outstanding.slice(0, 50).map(o => `<tr><td><strong>${escape(o.sport.toUpperCase())}</strong> · ${escape(o.player)}<small>${escape(o.ticker)} · ${escape(time(o.submitted_utc))}</small></td>
      <td>${escape(orderLabels[o.state] || o.state)}<small>Kalshi: ${escape(o.exchange_status)}</small></td>
      <td>${count(o.filled_contracts)} / ${count(o.ordered_contracts)}<small>${o.first_fill_utc ? "First fill: " + escape(time(o.first_fill_utc)) : "No confirmed fill"}</small></td>
      <td>${money(o.vwap_no_price_dollars)}<small>Fees: ${money(o.fill_fees_dollars)} · Maker contracts: ${count(o.maker_filled_contracts)}</small></td>
      <td>${count(o.queue_ahead_initial)} → ${count(o.queue_ahead_latest)}</td>
      <td>${finite(o.public_contra_contracts) ? count(o.public_contra_contracts) + " contracts (not guaranteed)" : "Not verified"}</td></tr>`).join("");
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
