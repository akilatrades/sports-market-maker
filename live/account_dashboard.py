"""Private production account dashboard. Exchange transport is GET-only.

Run on the Droplet; reach 127.0.0.1:8765 through an SSH tunnel. No credentials,
balances or journals are published to GitHub Pages. No trading endpoints exist.
"""

import argparse
import csv
import gzip
import json
import math
import os
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from kalshi.trading import TradingClient, TradingError
from live.nfl_policy import (
    MAX_ACTIVE_COST,
    MAX_GAME_COST,
    MAX_GROSS_COST,
    MAX_ORDER_COST,
    MIN_RESERVED_EDGE,
    STATE,
    STRATEGY_VERSION,
    reserve,
    settlement_accounting,
)

ASSETS = Path(__file__).resolve().parents[1] / "dashboard"
REFRESH_SECONDS = 60


def market_titles(path=None):
    """Use saved public contract titles only as labels, never as account data."""
    path = path or ASSETS.parent / "outputs/nfl/market/comparison.csv.gz"
    try:
        with gzip.open(path, "rt") as source:
            return {
                row["ticker"]: row["title"]
                for row in csv.DictReader(source)
                if row.get("ticker") and row.get("title")
            }
    except (OSError, EOFError, csv.Error):
        return {}


class ReadOnlyClient(TradingClient):
    def __init__(self):
        if os.environ.get("KALSHI_ENV") != "prod":
            raise TradingError("Production environment required for account reporting")
        super().__init__(env="prod", dry_run=True)
        if not self.can_sign:
            raise TradingError("Signed production reads required")

    def _request(self, method, path, params=None, body=None):
        if method != "GET" or body is not None or self.env != "prod":
            raise TradingError("Account dashboard permits production GET requests only")
        return super()._request(method, path, params, body)

    def place(self, order):
        raise TradingError("Account dashboard cannot place orders")

    def cancel(self, *args, **kwargs):
        raise TradingError("Account dashboard cannot cancel orders")

    def pages(self, path, key, **params):
        rows, seen = [], set()
        params["limit"] = 200
        while True:
            page = self._request("GET", path, params)
            if not isinstance(page.get(key), list):
                raise TradingError(f"Missing {key} in exchange response")
            rows.extend(page[key])
            cursor = page.get("cursor")
            if not cursor:
                return rows
            if cursor in seen:
                raise TradingError("Repeated account pagination cursor")
            seen.add(cursor)
            params["cursor"] = cursor


def number(value):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def dollars(row, dollar_key, cents_key=None):
    if row.get(dollar_key) is not None:
        return number(row[dollar_key])
    cents = number(row.get(cents_key)) if cents_key else None
    return cents / 100 if cents is not None else None


def total(values):
    values = list(values)
    return round(sum(values), 6) if all(v is not None for v in values) else None


def read_journal(path):
    if not path.exists():
        raise TradingError("Production journal is not available")
    raw = path.read_text()
    # A writer may be appending its last line. Retry on the next refresh;
    # never turn a partial journal into a reassuring zero-order snapshot.
    if raw and not raw.endswith("\n"):
        raise TradingError("Production journal update in progress")
    return [json.loads(line) for line in raw.splitlines() if line]


def summarize(balance, positions, resting, fills, settlements, events, scan, now):
    cash = dollars(balance, "balance_dollars", "balance")
    value = dollars(balance, "portfolio_value_dollars", "portfolio_value")
    if cash is None or value is None or cash < 0 or value < 0:
        raise TradingError("Exchange balance is missing or invalid")
    intents = {e["client_order_id"]: e for e in events if e.get("event") == "intent"}
    accepted = {
        e["order_id"]: intents[e["client_order_id"]]
        for e in events
        if e.get("event") == "accepted" and e.get("client_order_id") in intents
    }
    attempts_by_ticker = {e["ticker"]: e for e in intents.values()}
    owned = set(accepted)
    unique_fills = {}
    for event in events:
        if event.get("event") == "fill" and event.get("order_id") in owned:
            unique_fills[str(event["fill_id"])] = {
                "order_id": event["order_id"],
                "count_fp": event.get("count"),
                "no_price_dollars": event.get("no_price"),
                "fee_cost": event.get("fee"),
                "is_taker": event.get("is_taker"),
                # Journal fills are tied to an accepted NO-only worker order.
                # Exchange payload fields take precedence when available.
                "outcome_side": "no",
                "book_side": "ask",
            }
    for fill in fills:
        if fill.get("order_id") not in owned:
            continue
        fid = fill.get("fill_id") or fill.get("trade_id")
        if not fid:
            raise TradingError("Owned fill is missing its identity")
        unique_fills[str(fid)] = fill
    executed = list(unique_fills.values())
    quantity = total(number(f.get("count_fp", f.get("count"))) for f in executed)
    costs = []
    for fill in executed:
        # This strategy only buys NO; an unexpected buy/sell must not be
        # silently interpreted as the entry cost of a NO contract.
        # V2 asks/sells YES to buy NO. Legacy fill fields may therefore be
        # action=sell, side=yes even though the exposure is long NO.
        # Validate all available representations; never treat a YES-direction
        # fill as NO just because the order ID is owned.
        outcome = fill.get("outcome_side")
        book_side = fill.get("book_side")
        action = fill.get("action")
        side = fill.get("side")
        # Canonical outcome/book are authoritative; legacy action/side fields
        # have been observed to disagree in real Kalshi production fill data.
        # Do not reject an exchange-verified NO fill on deprecated fields.
        if outcome is not None or book_side is not None:
            if (outcome not in (None, "no")) or (book_side not in (None, "ask")):
                raise TradingError("Unexpected canonical strategy fill direction")
        elif (action, side) not in {("buy", "no"), ("sell", "yes")}:
            raise TradingError("Unverified legacy strategy fill direction")
        n = number(fill.get("count_fp", fill.get("count")))
        p = dollars(fill, "no_price_dollars", "no_price")
        costs.append(n * p if n is not None and p is not None else None)
    filled_cost = total(costs)
    fees = total(number(f.get("fee_cost")) for f in executed)
    results = {
        e["ticker"]: e
        for e in events
        if e.get("event") == "settlement" and e.get("ticker") in attempts_by_ticker
    }
    for result in settlements:
        ticker = result.get("ticker") or result.get("market_ticker")
        if ticker in attempts_by_ticker:
            results[ticker] = settlement_accounting(result)
    profit = (
        total(r.get("net_profit_dollars") for r in results.values())
        if results
        else None
    )
    held = []
    for position in positions:
        n = number(position.get("position_fp", position.get("position")))
        if n is None:
            raise TradingError("Position quantity missing")
        if n == 0:
            continue
        ticker = position.get("ticker") or position.get("market_ticker")
        attempt = attempts_by_ticker.get(ticker, {})
        held.append(
            {
                "ticker": ticker,
                "player": attempt.get("player") or ticker,
                "side": "YES" if n > 0 else "NO",
                "contracts": abs(n),
                "cost_dollars": dollars(
                    position, "market_exposure_dollars", "market_exposure"
                ),
                "fees_dollars": dollars(position, "fees_paid_dollars", "fees_paid"),
                "strategy_version": attempt.get("strategy_version", "Earlier version"),
                "probability_source": attempt.get("probability_source", "Not recorded"),
                "kickoff_utc": attempt.get("tip_utc"),
                "owned": bool(attempt),
            }
        )
    resting_rows = []
    for order in resting:
        oid = order.get("order_id")
        attempt = accepted.get(oid, {})
        remaining = number(
            order.get("remaining_count_fp", order.get("remaining_count"))
        )
        price = dollars(order, "no_price_dollars", "no_price")
        if price is None and attempt:
            price = number(attempt.get("price_cents"))
            price = price / 100 if price is not None else None
        resting_rows.append(
            {
                "ticker": order.get("ticker"),
                "player": attempt.get("player") or order.get("ticker"),
                "contracts": remaining,
                "price_dollars": price if attempt else None,
                "owned": bool(attempt),
            }
        )
    submitted = round(sum(reserve(e["cost"]) for e in intents.values()), 2)
    return {
        "schema_version": 1,
        "status": "ok",
        "environment": "production",
        "updated_utc": now.isoformat(),
        "refresh_seconds": REFRESH_SECONDS,
        "account": {
            "cash_dollars": cash,
            "position_value_dollars": value,
            "equity_dollars": round(cash + value, 6),
            "exchange_updated_ts": balance.get("updated_ts"),
            "open_markets": len(held),
            "resting_orders": len(resting),
        },
        "strategy": {
            "name": "NFL passive NO entries",
            "version": STRATEGY_VERSION,
            "accepted_orders": len(accepted),
            "filled_orders": len({f["order_id"] for f in executed}),
            "fill_records": len(executed),
            "contracts_filled": quantity,
            "fill_cost_dollars": filled_cost,
            "fill_fees_dollars": fees,
            "settled_markets": len(results),
            "settled_profit_dollars": profit,
            "submitted_reserved_dollars": submitted,
            "submission_limit_dollars": MAX_GROSS_COST,
            "remaining_submission_budget_dollars": round(
                max(0, MAX_GROSS_COST - submitted), 2
            ),
            "limits": {
                "per_order": MAX_ORDER_COST,
                "per_game": MAX_GAME_COST,
                "active": MAX_ACTIVE_COST,
            },
            "min_reserved_edge": MIN_RESERVED_EDGE,
            "unconfirmed_intents": len(intents) - len(accepted),
        },
        "positions": held,
        "orders": resting_rows,
        "scan": scan,
    }


def cohort_settled_pnl(events, settlements, exchange_fills=None):
    """Report owned market settlement only if authenticated fill cost reconciles.

    Exchange market settlements can contain another order's positions for the
    same ticker. Ownership of *one* order is not proof the entire market cost
    belongs to this strategy. Never claim verified strategy P&L if the
    settlement's NO cost does not match all owned exchange fill costs.
    """
    owned_orders = {}
    intents = {
        e["client_order_id"]: e
        for e in events
        if e.get("event") == "intent" and e.get("client_order_id")
    }
    for event in events:
        if event.get("event") != "accepted":
            continue
        intent = intents.get(event.get("client_order_id"))
        if intent and event.get("order_id"):
            owned_orders[event["order_id"]] = intent["ticker"]
    tickers = set(owned_orders.values())
    results = {
        e["ticker"]: e
        for e in events
        if e.get("event") == "settlement" and e.get("ticker") in tickers
    }
    for item in settlements:
        ticker = item.get("market_ticker") or item.get("ticker")
        if ticker in tickers:
            results[ticker] = settlement_accounting(item)
    values = [r.get("net_profit_dollars") for r in results.values()]
    complete = bool(values) and all(number(v) is not None for v in values)

    cost_matches = exchange_fills is not None
    fill_costs = {}
    counted_ids = set()
    if exchange_fills is not None:
        for fill in exchange_fills:
            ticker = fill.get("market_ticker") or fill.get("ticker")
            if ticker not in results:
                continue
            oid = fill.get("order_id")
            fid = fill.get("fill_id") or fill.get("trade_id")
            if oid not in owned_orders or owned_orders[oid] != ticker or not fid:
                cost_matches = False
                continue
            if fid in counted_ids:
                continue
            counted_ids.add(fid)
            count = number(fill.get("count_fp", fill.get("count")))
            price = dollars(fill, "no_price_dollars", "no_price")
            if count is None or count <= 0 or price is None or not 0 <= price <= 1:
                cost_matches = False
                continue
            outcome = fill.get("outcome_side")
            book = fill.get("book_side")
            if outcome not in (None, "no") or book not in (None, "ask"):
                cost_matches = False
                continue
            fill_costs[ticker] = fill_costs.get(ticker, 0) + count * price
        for ticker, result in results.items():
            no_cost = number(result.get("no_cost_dollars"))
            yes_cost = number(result.get("yes_cost_dollars"))
            if (
                no_cost is None
                or yes_cost is None
                or abs(yes_cost) > 0.005
                or abs(no_cost - fill_costs.get(ticker, 0)) > 0.015
            ):
                cost_matches = False
    else:
        cost_matches = False

    status = "awaiting_first_order"
    if owned_orders:
        status = "awaiting_settlement"
    if values:
        status = "incomplete_settlement"
    if complete:
        status = "verified" if cost_matches else "cost_or_ownership_mismatch"
    return {
        "status": status,
        "settled_profit_dollars": total(values) if status == "verified" else None,
        "settled_markets": len(results),
        "accepted_orders": len(owned_orders),
        "source": "authenticated_exchange_settlements_and_owned_fill_ids",
    }


def collect(client, state=STATE):
    events = read_journal(state / "journal.jsonl")
    # Both journals feed the P&L cards, irrespective of which market controls
    # the execution/positions panel. Missing staging is unknown, not $0.
    cohort_paths = {
        "nfl": STATE / "journal.jsonl",
        "nba": Path("/home/trader/prod-nba-auto/journal.jsonl"),
    }
    cohort_events = {}
    for market, journal in cohort_paths.items():
        if journal == state / "journal.jsonl":
            cohort_events[market] = events
        elif journal.exists():
            try:
                cohort_events[market] = read_journal(journal)
            except (OSError, ValueError, TradingError, json.JSONDecodeError):
                cohort_events[market] = None
        else:
            cohort_events[market] = None
    balance = client._request("GET", "/portfolio/balance")
    positions = client.pages("/portfolio/positions", "market_positions")
    resting = client.pages("/portfolio/orders", "orders", status="resting")
    # GET /portfolio/orders without status includes executed/canceled history.
    # Fetch separately from resting so we can see accepted-but-unfilled orders.
    # This cannot mutate the exchange or create an order.
    try:
        exchange_orders = client.pages("/portfolio/orders", "orders")
    except Exception:
        exchange_orders = None
    starts = [
        e["utc"]
        for cohort in cohort_events.values()
        if cohort is not None
        for e in cohort
        if e.get("event") == "intent"
    ]
    params = (
        {"min_ts": int(datetime.fromisoformat(min(starts)).timestamp()) - 60}
        if starts
        else {}
    )
    fills = client.pages("/portfolio/fills", "fills", **params) if starts else []
    settlements = (
        client.pages("/portfolio/settlements", "settlements", **params)
        if starts
        else []
    )
    scan_path = state / "last_scan.json"
    scan = json.loads(scan_path.read_text()) if scan_path.exists() else None
    result = summarize(
        balance, positions, resting, fills, settlements, events, scan, datetime.now(UTC)
    )
    if state.name == "prod-nba-auto":
        from live import prod_nba_auto as nba

        used = result["strategy"]["submitted_reserved_dollars"]
        result["strategy"].update(
            name="NBA passive NO entries",
            version=nba.STRATEGY_VERSION,
            min_reserved_edge=None,
            submission_limit_dollars=nba.MAX_GROSS_COST,
            remaining_submission_budget_dollars=round(
                max(0, nba.MAX_GROSS_COST - used), 2
            ),
            limits={
                "per_order": nba.MAX_ORDER_COST,
                "per_game": nba.MAX_GAME_COST,
                "per_team": nba.MAX_TEAM_COST,
                "active": nba.MAX_ACTIVE_COST,
                "daily": nba.MAX_DAILY_COST,
                "lifetime": nba.MAX_GROSS_COST,
            },
        )
        if scan:
            scan["run_utc"] = scan.get("utc")
            scan["filters"] = scan.get("selection_funnel", {}) or {
                "open_markets": scan.get("inputs", {}).get("rows"),
                "passed_book_or_model_and_spread": scan.get("candidate_count"),
            }
            scan["skip_reasons"] = scan.get("skipped", {})
    result["live_pnl"] = {
        market: (
            cohort_settled_pnl(cohort, settlements, fills)
            if cohort is not None
            else {
                "status": "unavailable",
                "settled_profit_dollars": None,
                "settled_markets": None,
                "accepted_orders": None,
            }
        )
        for market, cohort in cohort_events.items()
    }
    # Private, exchange-grounded unfilled/partial/resting audit for BOTH
    # production cohorts, irrespective of which cohort the dashboard selects.
    # A failed status/print read must not turn unknown orders into zero fills
    # or erase independently verified P&L from this account snapshot.
    from live.order_opportunity_audit import (
        audit_cohort,
        backfill_owned_orders,
        trade_through_samples,
    )

    if exchange_orders is not None:
        exchange_orders = backfill_owned_orders(client, cohort_events, exchange_orders)

    result["order_audit"] = {}
    for sport, cohort in cohort_events.items():
        if cohort is None or exchange_orders is None:
            result["order_audit"][sport] = {"status": "unavailable", "orders": []}
            continue
        try:
            samples = trade_through_samples(
                client, cohort, exchange_orders, datetime.now(UTC)
            )
            result["order_audit"][sport] = audit_cohort(
                cohort,
                exchange_orders,
                fills,
                sport=sport,
                now=datetime.now(UTC),
                prints_by_order=samples,
            )
        except Exception:
            result["order_audit"][sport] = {"status": "unavailable", "orders": []}
    from live.execution_scorecard import observed_execution

    result["execution_scorecard"] = {
        sport: (
            observed_execution(result["order_audit"].get(sport, {}), cohort)
            if cohort is not None
            else {"status": "unavailable"}
        )
        for sport, cohort in cohort_events.items()
    }
    # Account-only forward test: never exported to the recruiter-facing site.
    from live.nba_validation import summarize_nba_validation

    if cohort_events["nba"] is None:
        result["nba_validation"] = {"status": "unavailable"}
    else:
        try:
            result["nba_validation"] = summarize_nba_validation(
                cohort_events["nba"],
                result["order_audit"]["nba"],
                result["live_pnl"]["nba"],
                datetime.now(UTC),
            )
        except TradingError:
            result["nba_validation"] = {"status": "invalid_or_unreconciled"}
    result["kill_switch"] = (state / "KILL").exists()
    titles = market_titles()
    if state.name == "prod-nba-auto":
        try:
            with (state / "inputs" / "latest.csv").open() as source:
                titles.update(
                    {
                        row["ticker"]: f"{row['player']} · {row['stat']} {row['line']}"
                        for row in csv.DictReader(source)
                    }
                )
        except (OSError, KeyError, csv.Error):
            pass  # labels only; the exchange still supplies every account amount
    for row in result["positions"] + result["orders"]:
        row["player"] = titles.get(row["ticker"], row["player"])
    return result


class Snapshot:
    def __init__(self):
        self.value = {"status": "loading", "updated_utc": None}
        self.lock = threading.Lock()

    def read(self):
        with self.lock:
            return dict(self.value)

    def refresh(self, client, state):
        try:
            value = collect(client, state)
        except Exception as error:
            with self.lock:
                value = {
                    **self.value,
                    "status": "error",
                    "error_type": type(error).__name__,
                }
            # Error text can contain exchange/account details; keep it off logs.
            print("Account snapshot unavailable:", type(error).__name__, flush=True)
        with self.lock:
            self.value = value


def handler_for(snapshot, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            host = self.headers.get("Host", "")
            allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            origin = self.headers.get("Origin")
            if host not in allowed_hosts or (origin and origin != "http://" + host):
                self.send_error(403)
                return
            if self.headers.get("Sec-Fetch-Site", "none") not in {
                "none",
                "same-origin",
            }:
                self.send_error(403)
                return
            path = self.path.split("?", 1)[0]
            assets = {
                "/": ("account.html", "text/html"),
                "/account.js": ("account.js", "text/javascript"),
                "/account.css": ("account.css", "text/css"),
            }
            if path == "/api/account":
                data = json.dumps(snapshot.read(), allow_nan=False).encode()
                content_type = "application/json"
            elif path in assets:
                name, content_type = assets[path]
                data = (ASSETS / name).read_bytes()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            )
            self.end_headers()
            self.wfile.write(data)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print a private account snapshot, then exit",
    )
    args = parser.parse_args()
    market = os.environ.get("ACCOUNT_DASHBOARD_MARKET", "nfl")
    if market not in {"nfl", "nba"}:
        raise TradingError("Unknown account dashboard cohort")
    state = Path("/home/trader/prod-nba-auto") if market == "nba" else STATE
    client = ReadOnlyClient()
    if args.once:
        print(json.dumps(collect(client, state), indent=2, allow_nan=False))
        return
    snapshot = Snapshot()

    def worker():
        while True:
            snapshot.refresh(client, state)
            time.sleep(REFRESH_SECONDS)

    threading.Thread(target=worker, daemon=True).start()
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), handler_for(snapshot, args.port)
    )
    print(
        f"Private account dashboard: 127.0.0.1:{args.port}; GET-only production reads",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
