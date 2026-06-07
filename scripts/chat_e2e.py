"""Drive the ChatGPT-style chat end-to-end and screenshot the inline report + learn page."""
import asyncio
from playwright.async_api import async_playwright
BASE="https://vendorscout.lehana.in"

async def main():
    async with async_playwright() as pw:
        b=await pw.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=await b.new_context(viewport={"width":1440,"height":900})
        p=await ctx.new_page()
        await p.goto(BASE+"/",wait_until="networkidle")
        # body must NOT scroll (only transcript)
        body_scroll=await p.evaluate("({bs:document.body.scrollHeight, ih:window.innerHeight})")
        await p.get_by_placeholder("Describe what you want to source").fill("hitachi 1.5 to 2 ton ac for household chores in bulk of 12 with best price")
        await p.get_by_role("button", name="Source ▸").click()
        # wait for the report card (✓ Sourced) up to ~150s
        try:
            await p.wait_for_selector("text=Sourced", timeout=150000)
            await p.wait_for_timeout(1500)
            print("REPORT rendered ✅")
        except Exception as e:
            print("report wait failed:", e)
        await p.screenshot(path="/tmp/qa/chat-report.png", full_page=False)
        # page-scroll check (window should not scroll beyond viewport)
        d=await p.evaluate("({sw:document.documentElement.scrollWidth,cw:document.documentElement.clientWidth,winScroll:document.scrollingElement.scrollHeight<=window.innerHeight+2})")
        print("no-horizontal-overflow:", d['sw']<=d['cw']+1, "| page-not-scrollable:", d['winScroll'])
        # learn page
        p2=await ctx.new_page()
        await p2.goto(BASE+"/learn",wait_until="networkidle")
        await p2.wait_for_timeout(1500)
        await p2.screenshot(path="/tmp/qa/learn.png", full_page=False)
        print("learn screenshot ✅")
        await b.close()

asyncio.run(main())
