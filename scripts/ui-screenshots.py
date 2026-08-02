#!/usr/bin/env python3
"""Capture the web interface for the documentation.

Screenshots that are drawn go stale silently; these are taken from the running
interface, against a real indexed project, so an interface that changed and a
README that did not is visible in the diff.

Playwright is not a dependency of this project — the interface has no build
step and no Node toolchain, and adding one for pictures would be a poor trade.
Install it when you need to regenerate them:

    pip install playwright && playwright install chromium
    scripts/dev.sh gateway            # in another terminal
    python3 scripts/ui-screenshots.py

Pass --project to name an indexed project other than the first one offered.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
BASE = "http://127.0.0.1:8080"

#: Wide enough for the three-column graph layout, and a 16:10 ratio that does
#: not force a README reader to scroll sideways.
VIEWPORT = {"width": 1440, "height": 900}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=BASE, help="where the gateway is")
    parser.add_argument("--token", default="devtoken", help="the bearer token to sign in with")
    parser.add_argument("--admin-user", default="admin")
    parser.add_argument("--admin-password", default="devadmin-password")
    parser.add_argument("--project", help="which indexed project to show")
    parser.add_argument("--browser", help="path to a Chromium binary")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "playwright is not installed. This script is optional:\n"
            "  pip install playwright && playwright install chromium",
            file=sys.stderr,
        )
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    launch = {"executable_path": args.browser} if args.browser else {}

    with sync_playwright() as play:
        browser = play.chromium.launch(**launch)
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)

        page.goto(f"{args.base}/ui", wait_until="networkidle")
        page.wait_for_timeout(800)
        shot(page, "ui-signin")

        page.fill("#token", args.token)
        page.click("#signin-form button[type=submit]")
        page.wait_for_selector("#app:not([hidden])", timeout=15000)
        page.wait_for_timeout(2500)

        if args.project:
            # Two of the three selectors live on pages that are hidden right
            # now, so they are set directly rather than clicked.
            page.evaluate(
                """(name) => {
                    for (const id of ['overview-project', 'search-project', 'map-project']) {
                        const select = document.getElementById(id);
                        if ([...select.options].some((o) => o.value === name)) select.value = name;
                    }
                }""",
                args.project,
            )
            page.click("#overview-refresh")
            page.wait_for_timeout(2500)
        shot(page, "ui-overview")

        page.click("nav button[data-page=search]")
        page.fill("#search-query", "session")
        page.click("#search-go")
        page.wait_for_timeout(2500)
        hits = page.query_selector_all("#search-results .hit")
        if hits:
            hits[0].click()
            page.wait_for_timeout(2500)
        shot(page, "ui-search")

        page.click("nav button[data-page=map]")
        page.click("#map-go")
        # Wait for the layout to start and then to finish. Checking only for
        # "laying out" would pass immediately, while the status still says
        # "fetching", and photograph a blank canvas.
        page.wait_for_function(
            "() => /laying out/.test(document.getElementById('map-status').textContent)",
            timeout=60000,
        )
        page.wait_for_function(
            "() => !/laying out/.test(document.getElementById('map-status').textContent)",
            timeout=120000,
        )
        page.wait_for_timeout(1500)
        shot(page, "ui-map")

        page.click("nav button[data-page=admin]")
        page.wait_for_timeout(400)
        page.fill("#admin-user", args.admin_user)
        page.fill("#admin-pass", args.admin_password)
        page.click("#admin-form button[type=submit]")
        page.wait_for_selector("#admin-body:not([hidden])", timeout=10000)
        page.wait_for_timeout(1200)
        shot(page, "ui-admin")

        browser.close()

    print(f"\nwrote {len(list(OUT.glob('ui-*.png')))} screenshots to {OUT.relative_to(ROOT)}")
    return 0


def shot(page, name: str) -> None:
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path))
    print(f"  {path.relative_to(ROOT)}")


if __name__ == "__main__":
    raise SystemExit(main())
