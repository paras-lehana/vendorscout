"""Drive the Live Browser Theater UI and screenshot it mid-run (UI validation + deck asset)."""
import asyncio, sys
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011"

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = await (await b.new_context(viewport={"width": 1440, "height": 900})).new_page()
        await page.goto(f"{BASE}/theater", wait_until="networkidle")
        await page.get_by_role("button", name="Launch mission").click()
        # Let the agent browse IndiaMART live; capture a mid-run frame with timeline populated.
        await page.wait_for_timeout(48000)
        await page.screenshot(path="/tmp/vs_theater.png", full_page=False)
        print("screenshot saved /tmp/vs_theater.png; url=", page.url)
        await b.close()

asyncio.run(main())
