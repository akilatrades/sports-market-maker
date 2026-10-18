"""Render private account fixtures at phone and desktop sizes; no exchange access."""

import json
import threading
from datetime import UTC, datetime, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    root = Path(__file__).resolve().parents[1]
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(root))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fixture = {
        "schema_version": 1,
        "environment": "production",
        "status": "ok",
        "updated_utc": datetime.now(UTC).isoformat(),
        "account": {
            "cash_dollars": 100.0,
            "position_value_dollars": 2.64,
            "equity_dollars": 102.64,
            "resting_orders": 1,
        },
        "strategy": {
            "accepted_orders": 8,
            "filled_orders": 1,
            "contracts_filled": 4,
            "fill_cost_dollars": 2.64,
            "fill_fees_dollars": None,
            "settled_markets": 0,
            "settled_profit_dollars": None,
            "submitted_reserved_dollars": 14.0,
            "remaining_submission_budget_dollars": 36.0,
            "submission_limit_dollars": 50.0,
        },
        "positions": [
            {
                "player": "Fixture player",
                "ticker": "KXNFLRECYDS-FIXTURE-PLAYER-100",
                "owned": True,
                "side": "NO",
                "contracts": 4,
                "cost_dollars": 2.64,
                "probability_source": "Not recorded",
                "strategy_version": "Earlier version",
            }
        ],
        "orders": [
            {
                "player": "Second fixture player",
                "ticker": "FIXTURE",
                "owned": True,
                "contracts": 3,
                "price_dollars": 0.79,
            }
        ],
        "scan": {
            "run_utc": datetime.now(UTC).isoformat(),
            "decision": "all_candidates_blocked",
            "filters": {"open_markets": 1139, "in_entry_window": 279},
            "skip_reasons": {
                "game_budget": 32,
                "insufficient_edge_after_fee_buffer": 5,
            },
        },
    }
    screenshots = root / "test-artifacts"
    screenshots.mkdir(exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for width in (320, 375, 768, 1440):
                page = browser.new_page(viewport={"width": width, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route(
                    "**/api/account",
                    lambda route: route.fulfill(
                        content_type="application/json", body=json.dumps(fixture)
                    ),
                )
                page.goto(
                    f"http://127.0.0.1:{server.server_port}/dashboard/account.html",
                    wait_until="networkidle",
                )
                assert page.locator("#cash").inner_text() == "$100.00"
                assert page.locator("#profit").inner_text() == "—"
                assert page.locator("#filled").inner_text() == "1"
                assert page.locator("#contracts").inner_text() == "4"
                assert page.locator("#fees").inner_text() == "—"
                assert page.locator("#connect-help").is_hidden()
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth + 1"
                )
                assert not errors, errors
                page.screenshot(
                    path=str(screenshots / f"account-{width}.png"), full_page=True
                )
                fixture["updated_utc"] = (
                    datetime.now(UTC) - timedelta(minutes=10)
                ).isoformat()
                page.locator("#refresh").click()
                page.wait_for_function(
                    "document.querySelector('#connection').textContent === 'Snapshot stale'"
                )
                assert page.locator("#cash").inner_text() == "$100.00"
                fixture["updated_utc"] = datetime.now(UTC).isoformat()
                page.unroute("**/api/account")
                page.route(
                    "**/api/account",
                    lambda route: route.fulfill(status=503, body="unavailable"),
                )
                page.reload(wait_until="networkidle")
                assert page.locator("#cash").inner_text() == "—"
                assert page.locator("#connect-help").is_visible()
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth + 1"
                )
                assert not errors, errors
                print(
                    f"PASS account {width}px: balances, missing fees, stale data, disconnected view, no overflow"
                )
                page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
