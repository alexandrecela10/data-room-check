"""Screenshot the demo journey with your installed Chrome, headless.

    .venv/bin/python -m case_study.capture <out_dir>   # demo must be running on :8517

Playwright's own Chromium doesn't support macOS 13, so this drives Google Chrome.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8517"


def settle(pg, ms=2500):
    pg.wait_for_load_state("networkidle")
    pg.wait_for_function("() => !document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=120000)
    pg.wait_for_timeout(ms)


def step(pg, label):
    pg.locator("[data-testid=stSidebar]").get_by_text(label, exact=True).click()
    settle(pg)


def pick(pg, select_index, option_text):
    # Streamlit selectboxes are searchable: type into the input, then Enter picks the match.
    box = pg.locator("[data-testid=stSelectbox] input").nth(select_index)
    box.click(force=True)
    box.fill(option_text)
    pg.wait_for_timeout(500)
    box.press("Enter")
    settle(pg)


def shot(pg, out, name, full=True):
    path = out / f"{name}.png"
    pg.screenshot(path=str(path), full_page=full)
    print("wrote", path)


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        pg = b.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1.5)
        pg.goto(URL)
        settle(pg, 5000)
        shot(pg, out, "1-pick-your-deck")

        step(pg, "2. Meet your data room")
        shot(pg, out, "2-data-room", full=False)

        step(pg, "3. Run the check")
        pg.get_by_role("button", name="Show the results").click()
        settle(pg, 4000)
        shot(pg, out, "4-results-top", full=False)
        pick(pg, 0, "Revenue FY2025")
        pg.get_by_text("Open one. Where's the proof?").scroll_into_view_if_needed()
        pg.wait_for_timeout(1500)
        shot(pg, out, "4-results-evidence", full=False)
        pg.get_by_text("Red flags, from every page of every file").scroll_into_view_if_needed()
        pg.wait_for_timeout(800)
        shot(pg, out, "4-red-flags", full=False)

        step(pg, "5. Look under the hood")
        pick(pg, 0, "Revenue FY2025")
        shot(pg, out, "5-under-the-hood", full=True)

        step(pg, "6. How we got here")
        shot(pg, out, "6-how-we-got-here", full=True)
        b.close()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
