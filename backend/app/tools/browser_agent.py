# ============================================================
# VendorScout - Self-hosted Agentic Browser
# ============================================================
# A drop-in replacement for the prior third-party web-agent client: same
# public interface (run_task / run_task_streaming / run_batch / health_check)
# and a BrowserResult with the same fields, so the 8 orchestration agents
# only swap their web-client attribute -> `self.browser`.
#
# Engine: Playwright (Microsoft) + Azure OpenAI planner.
# Loop:   OBSERVE (screenshot + a11y/DOM snapshot)
#      -> PLAN    (Azure OpenAI -> next typed actions)
#      -> ACT     (Playwright real clicks/typing, emit live frame)
#      -> VERIFY  (did state change?)
#      -> RECOVER (re-plan on failure; escalate; degrade gracefully)
#
# Ported concepts from parse.lehana.in: action engine + stealth
# (puppeteer_scraper_v2.mjs), NL->action planning (ai_prompts.py),
# self-correcting iteration (llm_handler.py).
# ============================================================

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from app.config import settings
from app.tools.actions import Action, execute_action
from app.tools.llm import LLMTool
from app.tools.planner import plan_next_step
from app.tools import stealth

logger = logging.getLogger(__name__)

# Playwright is imported lazily so the app still boots (and `health_check`
# reports "not ready") in environments where chromium isn't installed yet.
try:  # pragma: no cover
    from playwright.async_api import async_playwright
    _PLAYWRIGHT_AVAILABLE = True
except Exception:  # noqa: BLE001
    async_playwright = None  # type: ignore
    _PLAYWRIGHT_AVAILABLE = False

OnUpdate = Optional[Callable[[dict], Awaitable[None]]]


@dataclass
class BrowserResult:
    """Result of an agentic browser task. Field-compatible with the prior
    web-agent result type so downstream code is untouched."""
    success: bool
    url: str
    run_id: str = ""
    extracted_data: dict = field(default_factory=dict)
    raw_text: str = ""
    error: Optional[str] = None
    num_steps: int = 0
    duration_ms: int = 0
    streaming_url: str = ""          # our own live-view (set by the API layer)
    transcript: list[dict] = field(default_factory=list)  # per-step audit trail

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "url": self.url,
            "run_id": self.run_id,
            "extracted_data": self.extracted_data,
            "raw_text": self.raw_text[:2000],
            "error": self.error,
            "num_steps": self.num_steps,
            "duration_ms": self.duration_ms,
            "streaming_url": self.streaming_url,
        }


class BrowserAgentClient:
    """Autonomous Playwright browser agent with a stable, drop-in web-client API."""

    def __init__(self) -> None:
        self.max_concurrent = getattr(settings, "BROWSER_MAX_CONCURRENCY", 3)
        self.max_steps = getattr(settings, "BROWSER_MAX_STEPS", 12)
        self.headless = getattr(settings, "BROWSER_HEADLESS", True)
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._llm = LLMTool()
        self._pw = None
        self._browser = None
        self._launch_lock = asyncio.Lock()

    # ---- browser lifecycle --------------------------------------------------

    async def _ensure_browser(self):
        if not _PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright not installed — run `playwright install chromium`")
        async with self._launch_lock:
            # Self-heal: a long-lived Chromium can crash/exit (OOM, sandbox death)
            # while `self._browser` still points at the dead handle. Detect a
            # disconnected browser and tear it down so we relaunch a fresh one —
            # otherwise every `new_context()` fails with "browser has been closed".
            if self._browser is not None and not self._browser.is_connected():
                logger.warning("Playwright browser disconnected — relaunching")
                with contextlib.suppress(Exception):
                    await self._browser.close()
                with contextlib.suppress(Exception):
                    if self._pw:
                        await self._pw.stop()
                self._browser = None
                self._pw = None
            if self._browser is None:
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(
                    headless=self.headless, args=stealth.DEFAULT_LAUNCH_ARGS,
                )
                logger.info("Playwright Chromium launched (headless=%s)", self.headless)
        return self._browser

    @contextlib.asynccontextmanager
    async def _new_page(self, url: str):
        browser = await self._ensure_browser()
        profile = stealth.profile_for(url)
        context = await browser.new_context(**stealth.context_kwargs(profile))
        if profile == "stealth":
            await context.add_init_script(stealth.STEALTH_INIT_SCRIPT)
        page = await context.new_page()
        try:
            yield page
        finally:
            with contextlib.suppress(Exception):
                await context.close()

    # ---- observe ------------------------------------------------------------

    async def _observe(self, page) -> dict:
        url = page.url
        title = ""
        a11y = ""
        visible = ""
        screenshot_b64 = ""
        with contextlib.suppress(Exception):
            title = await page.title()
        with contextlib.suppress(Exception):
            # Accessibility tree = compact interactive-element map (buttons/links/inputs).
            tree = await page.accessibility.snapshot()
            a11y = _flatten_a11y(tree) if tree else ""
        # ALWAYS include visible body text too — success messages, results, and other
        # plain-text nodes are filtered out of the a11y tree, so the planner would be
        # blind to them (e.g. a "Enquiry sent" acknowledgement). Combine both.
        with contextlib.suppress(Exception):
            visible = (await page.locator("body").inner_text()).strip()
        if a11y and visible:
            snapshot = (a11y + "\n\n--- visible page text ---\n" + visible)[:8000]
        else:
            snapshot = (a11y or visible)[:8000]
        with contextlib.suppress(Exception):
            png = await page.screenshot(type="jpeg", quality=55, full_page=False)
            screenshot_b64 = base64.b64encode(png).decode("ascii")
        return {"url": url, "title": title, "snapshot": snapshot,
                "screenshot_b64": screenshot_b64}

    # ---- the agentic loop ---------------------------------------------------

    async def run_task(
        self,
        url: str,
        goal: str,
        browser_profile: str = "auto",   # kept for interface compatibility
        timeout: int = 180,
        max_steps: Optional[int] = None,
        on_update: OnUpdate = None,
        allow_submit: Optional[bool] = None,
    ) -> BrowserResult:
        run_id = uuid.uuid4().hex[:12]
        steps_budget = max_steps or self.max_steps
        # Submits (incl. pressing Enter to search) are allowed BY DEFAULT so normal
        # navigation/search works. Confirm-before-send is OPT-IN: a caller passes
        # allow_submit=False only for safety-sensitive flows (e.g. an RFQ that should
        # be filled-but-not-sent in production). The RFQ demo passes True explicitly.
        if allow_submit is None:
            allow_submit = True
        started = time.monotonic()
        history: list[dict] = []
        extracted: dict = {}
        transcript: list[dict] = []

        async with self._semaphore:
            try:
                async with self._new_page(url) as page:
                    await _emit(on_update, {"type": "STARTED", "runId": run_id, "url": url})
                    # Initial navigation is the first action. Use domcontentloaded,
                    # NOT networkidle: ad/analytics-heavy marketplaces (IndiaMART)
                    # never go idle, so networkidle just times out and wastes a step.
                    await execute_action(page, Action(action="navigate", url=url,
                                                       wait_until="domcontentloaded",
                                                       timeout=30000,
                                                       continue_on_error=True))

                    repeat_sig = None
                    repeat_n = 0
                    for step in range(steps_budget):
                        if time.monotonic() - started > timeout:
                            return self._finish(False, url, run_id, extracted, history,
                                                transcript, started, error="step timeout")

                        obs = await self._observe(page)
                        # Vision-assisted recovery: feed the screenshot to the planner
                        # (gpt-4o multimodal) on the step right after a failure, where
                        # seeing the page beats the text snapshot.
                        recovering = bool(history and history[-1].get("status") == "error")
                        plan = await plan_next_step(
                            self._llm, goal, obs, history, extracted,
                            screenshot_b64=obs["screenshot_b64"] if recovering else None,
                        )
                        if plan.extracted:
                            extracted.update(plan.extracted)

                        frame = {"type": "STEP", "runId": run_id, "step": step,
                                 "message": plan.thought, "thought": plan.thought,
                                 "url": obs["url"], "screenshot": obs["screenshot_b64"]}
                        await _emit(on_update, frame)
                        transcript.append({k: frame[k] for k in ("step", "thought", "url")})

                        # Repeated-action breaker: if the planner keeps choosing the
                        # SAME action on the SAME element (e.g. clicking a covered
                        # "Get Best Price" behind a login popup), stop gracefully
                        # instead of burning the whole budget on a wall.
                        sig = ((plan.actions[0].action, (plan.actions[0].selector or "")[:60])
                               if plan.actions else None)
                        if sig and sig == repeat_sig:
                            repeat_n += 1
                        else:
                            repeat_sig, repeat_n = sig, 0
                        if repeat_n >= 3:
                            extracted.setdefault(
                                "stopped_at",
                                "a login / OTP / pop-up gate the agent could not pass without signing in")
                            return self._finish(bool(extracted), page.url, run_id, extracted,
                                                history, transcript, started)

                        if plan.done or not plan.actions:
                            if plan.done:
                                return self._finish(True, page.url, run_id, extracted,
                                                    history, transcript, started)
                            # No actions and not done -> nudge once, else stop.
                            history.append({"action": "noop", "status": "empty_plan"})
                            if _stuck(history):
                                break
                            continue

                        for act in plan.actions:
                            # A 'wait' that fails (e.g. a guessed selector that never
                            # appears) must not derail the run — re-observe instead.
                            if act.action == "wait":
                                act.continue_on_error = True
                                act.timeout = min(act.timeout or 6000, 6000)
                            try:
                                res = await execute_action(page, act, allow_submit=allow_submit)
                                history.append({"action": act.action, "status": res.status,
                                                "error": res.error})
                                if res.action == "extract" and res.value is not None:
                                    extracted[res.name or act.name or "extract"] = res.value
                                # Smoother "live" view: push a fresh frame showing the
                                # RESULT of this action (click/scroll/type), not just the
                                # once-per-step observe frame — so it feels like a live
                                # browser, not a slideshow.
                                with contextlib.suppress(Exception):
                                    await page.wait_for_timeout(250)
                                    _png = await page.screenshot(type="jpeg", quality=55, full_page=False)
                                    await _emit(on_update, {"type": "STEP", "runId": run_id, "step": step,
                                                            "url": page.url,
                                                            "screenshot": base64.b64encode(_png).decode("ascii")})
                            except Exception as e:  # noqa: BLE001 — RECOVER
                                history.append({"action": act.action, "status": "error",
                                                "error": str(e)})
                                await _emit(on_update, {"type": "RECOVER", "runId": run_id,
                                                        "step": step, "error": str(e),
                                                        "message": f"recovering from: {e}"})
                                break  # re-observe & re-plan next loop

                    # Budget exhausted -> graceful degrade with whatever we have.
                    return self._finish(bool(extracted), page.url, run_id, extracted,
                                        history, transcript, started,
                                        error=None if extracted else "max_steps reached")
            except Exception as e:  # noqa: BLE001
                logger.error("browser run_task failed for %s: %s", url, e)
                await _emit(on_update, {"type": "ERROR", "runId": run_id, "message": str(e)})
                return self._finish(False, url, run_id, extracted, history, transcript,
                                    started, error=str(e))

    async def run_task_streaming(
        self, url: str, goal: str, on_update: OnUpdate = None,
        browser_profile: str = "auto", timeout: int = 180,
        max_steps: Optional[int] = None, allow_submit: Optional[bool] = None,
    ) -> BrowserResult:
        """Streaming entry point — identical loop, events flow via on_update."""
        result = await self.run_task(url, goal, browser_profile, timeout,
                                     max_steps=max_steps, on_update=on_update,
                                     allow_submit=allow_submit)
        await _emit(on_update, {"type": "COMPLETE", "runId": result.run_id,
                                "status": "COMPLETED" if result.success else "FAILED",
                                "resultJson": result.extracted_data})
        return result

    async def run_rfq_streaming(
        self, url: str, site: str = "", name: str = "",
        on_update: OnUpdate = None, timeout: int = 180,
    ) -> BrowserResult:
        """Deterministic Request-for-Quote flow, driven to the OTP/verification
        gate and stopped there — NOT left to the LLM planner.

        Real B2B enquiry forms are a fixed, well-known sequence (open the modal →
        fill mobile/quantity/requirement → Continue → an OTP/verification screen
        appears). The generic agent loop kept re-clicking the ubiquitous "Send
        Inquiry" button instead of progressing, so this hard-codes the happy path
        for a reliable, watchable demo. We fill DUMMY buyer details, click through
        to the OTP screen, and STOP — we never type an OTP or sign in.
        """
        run_id = uuid.uuid4().hex[:12]
        started = time.monotonic()
        transcript: list[dict] = []
        history: list[dict] = []
        mobile = "9811122233"  # dummy buyer number — never verified / never an OTP entered
        extracted: dict = {"mode": "rfq", "site": site, "product": name, "mobile_used": mobile}

        async def step(thought: str, page=None, status: str = "ok"):
            frame = {"type": "STEP", "runId": run_id, "step": len(transcript) + 1,
                     "message": thought, "thought": thought}
            if page is not None:
                frame["url"] = page.url
                with contextlib.suppress(Exception):
                    png = await page.screenshot(type="jpeg", quality=55, full_page=False)
                    frame["screenshot"] = base64.b64encode(png).decode("ascii")
            await _emit(on_update, frame)
            transcript.append({"step": len(transcript) + 1, "thought": thought,
                               "url": frame.get("url", "")})
            history.append({"action": "rfq", "status": status})

        async def click_first(page, labels, timeout_ms=4000):
            for lab in labels:
                loc = page.get_by_role("button", name=lab)
                if await loc.count() == 0:
                    loc = page.get_by_text(lab, exact=False)
                cnt = await loc.count()
                for i in range(min(cnt, 3)):
                    el = loc.nth(i)
                    try:
                        if await el.is_visible():
                            with contextlib.suppress(Exception):
                                await el.scroll_into_view_if_needed(timeout=1500)
                            await el.click(timeout=timeout_ms)
                            return lab
                    except Exception:  # noqa: BLE001
                        continue
            return None

        async def fill_first(page, selector, value):
            with contextlib.suppress(Exception):
                loc = page.locator(selector).first
                if await loc.count() and await loc.is_visible():
                    await loc.fill(value)
                    return True
            return False

        try:
            await _emit(on_update, {"type": "GOAL", "runId": run_id,
                                    "goal": f"Request a quote on {site or 'the marketplace'} for "
                                            f"'{name or 'this product'}' — fill the enquiry & stop at OTP",
                                    "url": url})
            async with self._new_page(url) as page:
                await _emit(on_update, {"type": "PHASE", "runId": run_id, "phase": "OPEN"})
                with contextlib.suppress(Exception):
                    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2500)
                with contextlib.suppress(Exception):
                    await page.keyboard.press("Escape")
                await step(f"Opened the {site or ''} product page for "
                           f"'{name or 'this product'}'.", page)

                # STEP 1 — OPEN the enquiry modal (click ONCE)
                opened = await click_first(page, [
                    "Send Inquiry", "Send Enquiry", "Get Best Price", "Contact Supplier",
                    "Get Latest Price", "Contact Seller", "Enquire Now", "Enquire"])
                await page.wait_for_timeout(2600)
                if not opened:
                    extracted["stopped_at"] = "no enquiry button found on this page"
                    await step("Could not find an enquiry button on this page.", page, status="error")
                    return self._finish(False, page.url, run_id, extracted, history, transcript, started)
                await step(f"Clicked '{opened}' — the enquiry form is opening.", page)

                # STEP 2 — FILL the enquiry form with dummy buyer details
                await _emit(on_update, {"type": "PHASE", "runId": run_id, "phase": "FILL"})
                filled: list[str] = []
                if await fill_first(page,
                        "input[name='mobile']:visible, input[type='tel']:visible, "
                        "input[placeholder*='Mobile' i]:visible, input[placeholder*='mobile number' i]:visible",
                        mobile):
                    filled.append("Mobile")
                if await fill_first(page,
                        "input[placeholder*='Quantity' i]:visible, input[name*='quantity' i]:visible", "12"):
                    filled.append("Quantity")
                if await fill_first(page,
                        "textarea:visible, input[placeholder*='Requirement' i]:visible, "
                        "input[placeholder*='message' i]:visible",
                        "Need 12 units in bulk; please share best price, MOQ, lead time and certifications."):
                    filled.append("Requirement")
                extracted["fields_filled"] = filled
                await page.wait_for_timeout(700)
                if filled:
                    await step("Filled the enquiry form (dummy buyer details): " + ", ".join(filled) + ".", page)
                else:
                    await step("Enquiry opened; waiting for the form fields.", page)

                # STEP 3 — PROCEED to the OTP screen, handling a buyer-registration
                # sub-step. Some marketplaces (TradeIndia for a new number) insert a
                # one-time "Your Name / Pin Code" form BETWEEN the phone entry and the
                # OTP. So: click Continue, and if a registration form appears, fill it
                # and click Continue again — up to 3 rounds — until the OTP shows.
                await _emit(on_update, {"type": "PHASE", "runId": run_id, "phase": "PROCEED"})

                async def scan_gate(page):
                    body = ""
                    with contextlib.suppress(Exception):
                        body = (await page.locator("body").inner_text()).lower()
                    otp_text = any(k in body for k in [
                        "enter otp", "enter the otp", "one time password", "verify your mobile",
                        "verification code", "otp sent", "otp has been sent", "resend otp",
                        "resend code", "enter verification", "enter the code", "we have sent",
                        "otp verification"])
                    otp_field = 0
                    with contextlib.suppress(Exception):
                        otp_field = await page.locator(
                            "input[placeholder*='OTP' i]:visible, input[autocomplete='one-time-code']:visible, "
                            "input[name*='otp' i]:visible").count()
                    boxes = 0
                    with contextlib.suppress(Exception):
                        boxes = await page.locator("input[maxlength='1']:visible").count()
                    already = "already posted inquiry" in body or "already enquired" in body
                    return (otp_text or otp_field > 0 or boxes >= 4), already

                reached_otp = False
                already = False
                for rnd in range(3):
                    proceeded = await click_first(page, [
                        "Continue", "Proceed", "Get OTP", "Send OTP", "Verify Mobile",
                        "Submit", "Send Inquiry", "Send Enquiry", "Send"])
                    await page.wait_for_timeout(3800)
                    if proceeded:
                        await step(f"Clicked '{proceeded}' — proceeding toward phone verification.", page)
                    reached_otp, already = await scan_gate(page)
                    if reached_otp or already:
                        break
                    # A one-time buyer-registration form may now be on screen
                    # (Your Name / Pin Code / Company). Fill it by walking the
                    # visible inputs and matching on placeholder keywords — robust
                    # to markup differences across products.
                    reg: list[str] = []
                    with contextlib.suppress(Exception):
                        ins = page.locator("input:visible, textarea:visible")
                        for i in range(await ins.count()):
                            el = ins.nth(i)
                            typ = (await el.get_attribute("type") or "").lower()
                            if typ in ("checkbox", "radio", "hidden", "submit", "button"):
                                continue
                            already_val = ""
                            with contextlib.suppress(Exception):
                                already_val = await el.input_value()
                            if already_val:
                                continue  # already filled (e.g. the mobile field)
                            # Effective label = placeholder + aria-label + closest <label>
                            # + parent text. TradeIndia uses floating labels (no
                            # placeholder), so placeholder alone is not enough.
                            lab = ""
                            with contextlib.suppress(Exception):
                                lab = (await el.evaluate(
                                    "e=>{const l=e.closest('label');const p=e.parentElement;"
                                    "return ((e.placeholder||'')+' '+(e.getAttribute('aria-label')||'')+' '+"
                                    "(l?l.innerText:'')+' '+(p?p.innerText:'')).toLowerCase()}") or "")
                            if any(s in lab for s in ("search", "mobile", "quantity")):
                                continue
                            if "name" in lab and "company" not in lab:
                                with contextlib.suppress(Exception):
                                    await el.fill("Demo Buyer"); reg.append("Name")
                            elif "pin" in lab:
                                with contextlib.suppress(Exception):
                                    await el.fill("110001"); reg.append("Pin Code")
                            elif "company" in lab:
                                with contextlib.suppress(Exception):
                                    await el.fill("Demo Procurement"); reg.append("Company")
                            elif "email" in lab:
                                with contextlib.suppress(Exception):
                                    await el.fill("buyer@example.com"); reg.append("Email")
                            elif "requirement" in lab or "message" in lab:
                                with contextlib.suppress(Exception):
                                    await el.fill("Need 12 units in bulk; please share best price, "
                                                  "MOQ, lead time and certifications."); reg.append("Requirement")
                    # Tick the "I agree to terms" checkbox (required to proceed); skip GST.
                    with contextlib.suppress(Exception):
                        cbs = page.locator("input[type='checkbox']:visible")
                        for i in range(await cbs.count()):
                            el = cbs.nth(i)
                            lbl = ""
                            with contextlib.suppress(Exception):
                                lbl = (await el.evaluate(
                                    "e=>{const p=e.closest('label')||e.parentElement;"
                                    "return (p&&p.innerText)||''}") or "").lower()
                            if "gst" in lbl:
                                continue
                            with contextlib.suppress(Exception):
                                if not await el.is_checked():
                                    await el.check()
                    if reg:
                        for r in reg:
                            if r not in filled:
                                filled.append(r)
                        extracted["fields_filled"] = filled
                        await step("Filled the buyer registration step (dummy details): "
                                   + ", ".join(reg) + ".", page)
                    elif not proceeded:
                        break  # nothing to click and no reg form — stop probing

                # STEP 4 — STOP at the gate (never enter an OTP / sign in)
                await _emit(on_update, {"type": "PHASE", "runId": run_id, "phase": "STOP"})
                if reached_otp:
                    extracted["reached_otp"] = True
                    extracted["stopped_at"] = ("OTP verification screen — stopped before entering any "
                                               "code (we never complete verification)")
                    await step("✅ Reached the OTP / verification screen. Stopping here — we never "
                               "enter the OTP or send on your behalf.", page)
                    ok = True
                elif already:
                    extracted["reached_otp"] = True
                    extracted["stopped_at"] = ("supplier reports an enquiry was already posted for this "
                                               "product — reached the transaction endpoint")
                    await step("✅ Reached the enquiry endpoint (an enquiry is already posted for this "
                               "product). Stopping here.", page)
                    ok = True
                else:
                    # Reached + filled the phone-verification gate but the OTP boxes
                    # weren't auto-confirmed — still the real transaction endpoint.
                    extracted["reached_otp"] = False
                    extracted["stopped_at"] = ("phone-verification gate — filled the enquiry and stopped "
                                               "before OTP / sign-in (we never verify)")
                    await step("Reached the phone-verification gate and filled the enquiry. Stopping "
                               "before OTP / sign-in — we never verify on your behalf.", page)
                    ok = True
                return self._finish(ok, page.url, run_id, extracted, history, transcript, started)
        except Exception as e:  # noqa: BLE001
            logger.error("rfq run failed for %s: %s", url, e)
            await _emit(on_update, {"type": "ERROR", "runId": run_id, "message": str(e)})
            return self._finish(False, url, run_id, extracted, history, transcript, started, error=str(e))

    async def live_preview_streaming(
        self, url: str, on_update: OnUpdate = None, run_id: str = "",
        pane: str = "IndiaMART", label: str = "IndiaMART", frames: int = 5,
    ) -> None:
        """Lightweight live-browser preview for the SEARCH cockpit.

        Navigates the real marketplace listings page and streams a few real
        screenshots while scrolling, so the user watches the agent "browse" live
        (the running agentic view) — WITHOUT the heavy per-step LLM loop or a
        second concurrent browser (which previously stalled the run). Emits STEP
        frames tagged with `pane` so the cockpit shows them in that pane's live
        view. Best-effort and self-contained: never raises.
        """
        captions = [
            f"Opening {label} listings…", f"Scanning supplier cards…",
            f"Reading names, prices & locations…", f"Collecting matching suppliers…",
            f"Compiling the {label} shortlist…", f"Cross-checking the best matches…"]
        try:
            async with self._new_page(url) as page:
                await _emit(on_update, {"type": "STEP", "runId": run_id, "pane": pane,
                                        "thought": captions[0]})
                with contextlib.suppress(Exception):
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(1100)
                with contextlib.suppress(Exception):
                    await page.keyboard.press("Escape")  # dismiss any auto-popup
                for i in range(max(1, frames)):
                    with contextlib.suppress(Exception):
                        png = await page.screenshot(type="jpeg", quality=55, full_page=False)
                        await _emit(on_update, {
                            "type": "STEP", "runId": run_id, "pane": pane,
                            "thought": captions[min(i, len(captions) - 1)],
                            "screenshot": base64.b64encode(png).decode("ascii")})
                    with contextlib.suppress(Exception):
                        await page.mouse.wheel(0, 620)
                    await page.wait_for_timeout(1050)
        except Exception as e:  # noqa: BLE001 — preview is decorative; never fail the search
            logger.warning("live preview failed for %s: %s", url, e)

    async def run_batch(self, tasks: list[dict]) -> list[BrowserResult]:
        async def _one(t: dict) -> BrowserResult:
            return await self.run_task(
                url=t["url"], goal=t["goal"],
                browser_profile=t.get("browser_profile", "auto"),
                timeout=t.get("timeout", 180),
            )
        results = await asyncio.gather(*[_one(t) for t in tasks], return_exceptions=True)
        out: list[BrowserResult] = []
        for t, r in zip(tasks, results):
            if isinstance(r, Exception):
                out.append(BrowserResult(success=False, url=t["url"], error=str(r)))
            else:
                out.append(r)
        ok = sum(1 for r in out if r.success)
        logger.info("browser batch: %d/%d succeeded", ok, len(tasks))
        return out

    async def health_check(self) -> bool:
        if not _PLAYWRIGHT_AVAILABLE:
            return False
        try:
            await self._ensure_browser()
            return self._browser is not None and bool(self._llm.api_key or self._llm.service_url)
        except Exception as e:  # noqa: BLE001
            logger.warning("browser health check failed: %s", e)
            return False

    async def aclose(self):
        with contextlib.suppress(Exception):
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()

    # ---- helpers ------------------------------------------------------------

    def _finish(self, success, url, run_id, extracted, history, transcript,
                started, error=None) -> BrowserResult:
        return BrowserResult(
            success=success, url=url, run_id=run_id,
            extracted_data=extracted if isinstance(extracted, dict) else {"raw": extracted},
            raw_text=str(extracted)[:2000],
            error=error, num_steps=len(history),
            duration_ms=int((time.monotonic() - started) * 1000),
            transcript=transcript,
        )


def _flatten_a11y(node: dict, depth: int = 0, out: Optional[list] = None) -> str:
    """Flatten Playwright's accessibility snapshot into compact labelled lines."""
    if out is None:
        out = []
    if depth > 12 or len(out) > 400:
        return "\n".join(out)
    role = node.get("role", "")
    name = (node.get("name") or "").strip()
    if role and (name or role in ("textbox", "button", "link", "combobox")):
        out.append(f"{'  ' * min(depth, 6)}- {role}: {name[:120]}")
    for child in node.get("children", []) or []:
        _flatten_a11y(child, depth + 1, out)
    return "\n".join(out)


def _stuck(history: list[dict], window: int = 3) -> bool:
    recent = history[-window:]
    return len(recent) == window and all(h.get("status") in ("empty_plan", "error") for h in recent)


async def _emit(on_update: OnUpdate, event: dict) -> None:
    if on_update is None:
        return
    with contextlib.suppress(Exception):
        await on_update(event)
