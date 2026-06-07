"""Dogfood the agent's stealth context: navigate to URLs and screenshot them.
Usage: python scripts/nav_capture.py  (run from repo root, venv active, PYTHONPATH=backend)
"""
import asyncio, sys, base64
sys.path.insert(0, "backend")
from playwright.async_api import async_playwright
from app.tools import stealth

TARGETS = [
    ("github_new", "https://github.com/new"),
    ("azure_foundry", "https://ai.azure.com"),
    ("indiamart", "https://www.indiamart.com"),
]

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=stealth.DEFAULT_LAUNCH_ARGS)
        for name, url in TARGETS:
            ctx = await browser.new_context(**stealth.context_kwargs("stealth"))
            await ctx.add_init_script(stealth.STEALTH_INIT_SCRIPT)
            page = await ctx.new_page()
            status = "ok"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2500)
            except Exception as e:
                status = f"nav-warn: {e}"
            title = ""
            try:
                title = await page.title()
            except Exception:
                pass
            out = f"/tmp/vs_{name}.png"
            try:
                await page.screenshot(path=out, full_page=False)
            except Exception as e:
                out = f"(screenshot failed: {e})"
            print(f"[{name}] url={page.url}\n  title={title!r}\n  status={status}\n  shot={out}")
            await ctx.close()
        await browser.close()

asyncio.run(main())
