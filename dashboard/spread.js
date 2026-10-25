/* Public display only. Reads the existing aggregate feed; no account controls. */
(() => {
  "use strict";
  const MAX_AGE_MS = 90_000;
  const POLL_MS = 15_000;
  const TIMEOUT_MS = 8_000;
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const count = value => finite(value) && value >= 0 ? value.toLocaleString("en-US", {maximumFractionDigits: 2}) : "—";
  const money = value => `${value < 0 ? "−" : value > 0 ? "+" : ""}$${Math.abs(value).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  const stamp = raw => {
    if (typeof raw !== "string" || !/(Z|[+-]\d{2}:\d{2})$/.test(raw)) return NaN;
    return Date.parse(raw);
  };
  function classify(data, now = Date.now()) {
    const item = data?.markets?.spread;
    const asOf = stamp(data?.as_of_utc);
    const valid = data?.schema_version === 1 && data?.status !== "unavailable"
      && data?.refresh_type === "signed_live_account_settlements_30s"
      && item?.status === "verified_fill_ledger" && finite(item?.realized_profit_dollars)
      && Number.isFinite(asOf);
    if (!valid) return {state: "unavailable", label: "Update unavailable", message: item?.status === "unreconciled"
      ? "The reporting feed is reconciling. A verified result will appear when it is ready."
      : item?.status === "awaiting_first_fill" ? "Awaiting the first verified fill."
      : "The verified feed is temporarily unavailable. Refreshing automatically."};
    if (now - asOf > MAX_AGE_MS || asOf - now > 60_000) return {state: "stale", label: "Update delayed", message: "The latest report has expired. Waiting for a fresh verified result."};
    return {state: "verified", label: "Verified P&L", item, asOf};
  }
  function endpoint(config) {
    if (typeof config?.api_url !== "string" || !config.api_url.trim()) throw Error("Missing feed");
    const url = new URL(config.api_url.trim());
    if (url.protocol !== "https:" || url.username || url.password) throw Error("Invalid feed");
    return url.href;
  }
  // Export pure display rules for regression tests; no browser startup in Node.
  if (typeof module !== "undefined" && module.exports) { module.exports = {classify, endpoint, count, money}; return; }
  const node = id => document.getElementById(id);
  let snapshot = null;
  let connected = false;
  let busy = false;
  function render() {
    const view = classify(connected ? snapshot : null);
    node("feed-status").textContent = view.label;
    node("feed-status").dataset.state = view.state;
    node("feed-notice").hidden = !view.message;
    node("feed-notice").textContent = view.message || "";
    const amount = view.item?.realized_profit_dollars;
    node("spread-pnl").textContent = view.state === "verified" ? money(amount) : "—";
    node("spread-pnl").className = "pnl" + (view.state !== "verified" ? "" : amount > 0 ? " positive" : amount < 0 ? " negative" : "");
    node("contracts").textContent = count(view.item?.filled_contracts);
    node("settled").textContent = count(view.item?.settled_markets);
    node("updated").textContent = view.state === "verified"
      ? `Updated ${new Date(view.asOf).toISOString().slice(0, 19).replace("T", " ")} UTC · Auto-refresh`
      : "Current result unavailable · Auto-refresh on";
  }
  async function json(url) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const response = await fetch(url, {cache: "no-store", signal: controller.signal, credentials: "omit"});
      if (!response.ok) throw Error("Feed unavailable");
      return await response.json();
    } finally { clearTimeout(timer); }
  }
  async function refresh() {
    if (busy) return;
    busy = true;
    node("refresh").disabled = true;
    try {
      const config = await json("./live-pnl-source.json");
      const result = await json(endpoint(config));
      snapshot = result;
      connected = true;
    } catch (_) { connected = false; snapshot = null; }
    finally { busy = false; node("refresh").disabled = false; render(); }
  }
  node("refresh").addEventListener("click", refresh);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { render(); refresh(); } });
  refresh();
  setInterval(() => { render(); if (!document.hidden) refresh(); }, POLL_MS);
})();
