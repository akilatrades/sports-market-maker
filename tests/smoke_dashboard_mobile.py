"""Browser checks for the spread-only page, including truthful failure states."""

import threading
from datetime import UTC, datetime, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


def snapshot(age=0, profit=17.0486):
    return {
        "schema_version": 1,
        "refresh_type": "signed_live_account_settlements_30s",
        "as_of_utc": (datetime.now(UTC) - timedelta(seconds=age)).isoformat(),
        "markets": {
            "spread": {
                "status": "verified_fill_ledger",
                "realized_profit_dollars": profit,
                "filled_contracts": 102.59,
                "settled_markets": 21,
            },
            "nba": {"settled_profit_dollars": 999},
        },
        "account": {"settled_profit_dollars": 888},
    }


def main():
    repo = Path(__file__).resolve().parents[1]
    screenshots = repo / "test-artifacts"
    screenshots.mkdir(exist_ok=True)
    handler = partial(SimpleHTTPRequestHandler, directory=str(repo))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width in (320, 375, 390, 768, 1440):
                    context = browser.new_context(
                        viewport={"width": width, "height": 1000},
                        device_scale_factor=1,
                        is_mobile=width <= 768,
                        has_touch=width <= 768,
                    )
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    state = {"data": snapshot(), "fail": False}
                    context.route(
                        "**/live-pnl-source.json",
                        lambda route: route.fulfill(
                            json={"api_url": "https://feed.example/v1/pnl"}
                        ),
                    )

                    def feed(route):
                        if state["fail"]:
                            route.abort("failed")
                        else:
                            route.fulfill(json=state["data"])

                    context.route("https://feed.example/v1/pnl", feed)
                    page.goto(
                        f"http://127.0.0.1:{server.server_port}/dashboard/",
                        wait_until="networkidle",
                    )
                    assert page.locator("#spread-pnl").inner_text() == "+$17.05"
                    assert page.locator("#contracts").inner_text() == "102.59"
                    assert page.locator("#settled").inner_text() == "21"
                    assert "999" not in page.locator("body").inner_text()
                    assert "888" not in page.locator("body").inner_text()
                    assert "NBA" not in page.locator("body").inner_text()
                    assert not errors, errors
                    metrics = page.evaluate(
                        """() => ({page: document.documentElement.clientWidth,
                        widest: document.documentElement.scrollWidth})"""
                    )
                    assert metrics["widest"] <= metrics["page"] + 1, metrics
                    page.screenshot(
                        path=str(screenshots / f"spread-{width}.png"), full_page=True
                    )
                    page.locator("#method summary").click()
                    assert page.locator("#method").evaluate("el => el.open")
                    assert (
                        "reconciled manual exits"
                        in page.locator("#method").inner_text()
                    )
                    page.evaluate("window.__noReload = true")
                    page.set_viewport_size({"width": width, "height": 620})
                    assert page.evaluate("window.__noReload") is True
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_function("window.scrollY > 0")

                    def update(data=None, fail=False):
                        state.update(data=data, fail=fail)
                        page.locator("#refresh").click()
                        page.wait_for_function(
                            "!document.getElementById('refresh').disabled"
                        )

                    update(snapshot(profit=-1.23))
                    assert page.locator("#spread-pnl").inner_text() == "−$1.23"
                    assert "negative" in page.locator("#spread-pnl").get_attribute(
                        "class"
                    )
                    update(snapshot(age=100))
                    assert page.locator("#spread-pnl").inner_text() == "—"
                    assert page.locator("#feed-status").inner_text() == "Update delayed"
                    update(snapshot())
                    update(fail=True)
                    assert page.locator("#spread-pnl").inner_text() == "—"
                    assert page.locator("#contracts").inner_text() == "—"
                    assert "unavailable" in page.locator("#feed-status").inner_text()
                    update(snapshot(profit=0))
                    assert page.locator("#spread-pnl").inner_text() == "$0.00"
                    assert not errors, errors
                    print(f"PASS {width}px: layout, scrolling, data, failure, recovery")
                    context.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
