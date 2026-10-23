"""Smoke test the published dashboard in a mobile-sized Chromium viewport.

Run explicitly after installing Playwright/Chromium; not part of regular pytest.
"""

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    repo = Path(__file__).resolve().parents[1]
    screenshots = repo / "test-artifacts"
    screenshots.mkdir(exist_ok=True)
    expected = json.loads((repo / "outputs/dashboard/summary.json").read_text())
    handler = partial(SimpleHTTPRequestHandler, directory=str(repo))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
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
                    url = f"http://127.0.0.1:{server.server_port}/dashboard/"
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_function(
                        "() => !document.querySelector('#stamp').textContent.includes('Loading')",
                        timeout=15000,
                    )
                    assert not errors, f"{width}px: JS errors: {errors}"
                    expected_edge = expected["research"]["bookline"]["veto"]["cents"]
                    assert page.locator("#lead-edge").inner_text() == (
                        f"+{expected_edge:.2f}¢"
                    )
                    assert page.locator("#study-chart svg").count() == 1
                    page.screenshot(path=str(screenshots / f"research-{width}.png"))
                    if width == 1440:
                        page.locator("#strategies").screenshot(
                            path=str(screenshots / "research-strategies.png")
                        )
                        page.locator("#research-section").screenshot(
                            path=str(screenshots / "research-evidence.png")
                        )
                    metrics = page.evaluate(
                        """() => ({
                          page: document.documentElement.clientWidth,
                          widest: document.documentElement.scrollWidth,
                          height: document.documentElement.scrollHeight,
                          navOverflow: getComputedStyle(
                            document.querySelector('.toplinks')
                          ).overflowX
                        })"""
                    )
                    assert metrics["widest"] <= metrics["page"] + 2, (
                        f"{width}px: horizontal page overflow: {metrics}"
                    )
                    if width <= 700:
                        assert metrics["navOverflow"] == "auto"
                        # The old #heat element was removed from the
                        # dashboard; validate the *actual* horizontal
                        # scroll regions, including the navigation.
                        for selector in (".toplinks", ".scroll"):
                            for region in page.locator(selector).all():
                                if not region.is_visible():
                                    continue
                                action = region.evaluate(
                                    "(el) => getComputedStyle(el).touchAction"
                                )
                                assert action == "auto", (
                                    f"{width}px: {selector} traps vertical swipes: "
                                    f"{action}"
                                )
                    assert metrics["height"] > 1200, (
                        f"{width}px: unexpectedly short page; data failed to render"
                    )

                    # A phone's URL bar changing height must NOT reload the page
                    # or jump the user back to the top.
                    page.evaluate(
                        "() => { window.__scrollMarker = true; window.scrollTo({top: 650, behavior: 'instant'}); }"
                    )
                    before = page.evaluate("window.scrollY")
                    assert before >= 200, f"{width}px: page did not scroll"
                    page.set_viewport_size({"width": width, "height": 680})
                    page.wait_for_timeout(700)
                    after = page.evaluate(
                        "() => ({y: window.scrollY, marker: window.__scrollMarker})"
                    )
                    assert after["marker"] is True, f"{width}px: page reloaded"
                    assert abs(after["y"] - before) < 90, (
                        f"{width}px: scroll jumped on height-only resize: "
                        f"{before} -> {after['y']}"
                    )
                    assert not errors, f"{width}px: JS errors after resize: {errors}"

                    # Jumping to lower anchors must work.
                    page.locator('a[href="#research-section"]').click()
                    assert page.evaluate("location.hash") == "#research-section"
                    # Diagnostics are optional when no suitable research
                    # snapshot is published. Only exercise a rendered panel.
                    visible_panels = page.locator("details.diagnostics:visible")
                    if visible_panels.count():
                        panel = visible_panels.first
                        panel.locator("summary").click()
                        assert panel.evaluate("(el) => el.open")
                    assert not errors, f"{width}px: errors after expanding diagnostics"
                    print(f"PASS {width}px: scroll, no reload, nav, JS and overflow")
                    context.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
