"""Read-only, sanitized, near-live Kalshi account P&L feed.

For the user's PUBLIC GitHub Pages site: localhost HTTP only, to be
published through a separately configured HTTPS reverse proxy. No Kalshi
keys, account balances, positions, market tickers or orders are returned.
Trading methods are unavailable through ReadOnlyClient.

Account-wide amount is the sum of currently API-available SETTLED
markets, NOT account cash and NOT all-time realized cash-outs.
"""

import argparse
import json
import threading
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from live.account_dashboard import ReadOnlyClient, read_journal
from live.nfl_policy import settlement_accounting
from tools.publish_production_pnl import JOURNALS, build_report

PUBLIC_ORIGIN = "https://akilatrades.github.io"
INTERVAL = 30
MAX_AGE_SECONDS = 90


def account_settlement_pnl(rows):
    """Aggregate all accessible Kalshi account settlement rows once per ticker.

    Do not quietly turn unknown accounting fields or conflicting duplicate
    rows into a green profit. Settlements do NOT capture every early cash-out,
    rebate or archived position. Scope is intentionally 'settled markets
    currently available to the Kalshi REST API'.
    """
    if not isinstance(rows, list):
        raise ValueError("settlement_data_unavailable")
    unique = {}
    for row in rows:
        ticker = row.get("market_ticker") or row.get("ticker")
        exchange = row.get("exchange_index", 0)
        if not isinstance(ticker, str) or not ticker:
            raise ValueError("settlement_identity_missing")
        key = (exchange, ticker)
        result = settlement_accounting(row)
        amount = result.get("net_profit_dollars")
        if amount is None or not result.get("accounting_complete"):
            raise ValueError("unreconciled_account_settlement")
        try:
            profit = Decimal(str(amount))
        except (InvalidOperation, ValueError):
            raise ValueError("invalid_settlement_amount") from None
        if key in unique and unique[key] != profit:
            raise ValueError("conflicting_settlement_rows")
        unique[key] = profit
    pnl = sum(unique.values(), Decimal("0"))
    return {
        "status": "verified_settlement_snapshot" if unique else "awaiting_settlement",
        "settled_profit_dollars": round(float(pnl), 2) if unique else None,
        "settled_markets": len(unique),
        "scope": "all accessible account settlements (includes bot and manual orders)",
        "limitations": (
            "Excludes open/unrealized positions, early exits without settlement, "
            "account credits, and settlements already moved to historical storage."
        ),
    }


def collect_public(client=None, journal_paths=None, now=None):
    """Fetch actual account settlements and strategy cohorts via signed GETs."""
    now = now or datetime.now(UTC)
    client = client or ReadOnlyClient()
    paths = journal_paths or JOURNALS
    cohorts = {
        m: read_journal(paths[m]) if paths[m].exists() else None for m in ("nfl", "nba")
    }
    # Account-level collection MUST NOT be limited by the bot's first order.
    # All visible account settlements, including manual markets, are included.
    settlements = client.pages("/portfolio/settlements", "settlements")
    intents = [
        datetime.fromisoformat(e["utc"]).timestamp()
        for events in cohorts.values()
        if events is not None
        for e in events
        if e.get("event") == "intent"
    ]
    fills = (
        client.pages("/portfolio/fills", "fills", min_ts=int(min(intents)) - 60)
        if intents
        else []
    )
    report = build_report(cohorts, fills, settlements, now)
    report["account"] = account_settlement_pnl(settlements)
    report["refresh_type"] = "signed_live_account_settlements_30s"
    return report


class Cache:
    def __init__(self):
        self.lock = threading.Lock()
        self.value = {"schema_version": 1, "status": "unavailable"}

    def update(self, value):
        with self.lock:
            self.value = value

    def read(self):
        with self.lock:
            return dict(self.value)


def handler_for(cache):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if urlsplit(self.path).path != "/v1/pnl":
                self.send_error(404)
                return
            origin = self.headers.get("Origin")
            if origin and origin != PUBLIC_ORIGIN:
                self.send_error(403)
                return
            result = cache.read()
            stamp = result.get("as_of_utc")
            if stamp:
                age = (
                    datetime.now(UTC)
                    - datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                ).total_seconds()
            else:
                age = float("inf")
            if age > MAX_AGE_SECONDS or age < -60:
                result = {"schema_version": 1, "status": "unavailable"}
            body = json.dumps(result, allow_nan=False).encode()
            self.send_response(200 if result.get("status") != "unavailable" else 503)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", PUBLIC_ORIGIN)
            self.send_header("Vary", "Origin")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--once", action="store_true", help="Redacted GET-only diagnostic")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--interval", type=int, default=INTERVAL)
    args = p.parse_args()
    if not 15 <= args.interval <= 60:
        p.error("interval must be 15 to 60 seconds")
    client = ReadOnlyClient()
    if args.once:
        print(json.dumps(collect_public(client), indent=2, allow_nan=False))
        return
    cache = Cache()

    def update_loop():
        while True:
            try:
                value = collect_public(client)
                cache.update(value)
            except Exception as error:
                # A missing/failed Kalshi call invalidates the entire current
                # snapshot; never keep yesterday's profit on the LIVE surface.
                cache.update({"schema_version": 1, "status": "unavailable"})
                print(
                    "Public P&L refresh unavailable:", type(error).__name__, flush=True
                )
            time.sleep(args.interval)

    threading.Thread(target=update_loop, daemon=True).start()
    print(f"Redacted account P&L on 127.0.0.1:{args.port}; GET-only", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(cache)).serve_forever()


if __name__ == "__main__":
    main()
