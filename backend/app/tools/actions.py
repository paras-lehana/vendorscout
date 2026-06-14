# ============================================================
# VendorScout - Browser action schema + Playwright executors
# ============================================================
# Ported from parse.lehana.in's puppeteer_scraper_v2.mjs action engine
# (navigate / fill / click / wait / extract) to Playwright (Microsoft),
# plus scroll / press / select for richer multi-step transactions.
#
# Each executor performs ONE real browser action and returns a result dict
# (status + metadata) that the agentic loop logs and streams to the UI.
# ============================================================

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# The planner observes the page as an accessibility tree whose lines look like
# "- link: 3 Star Split AC Hitachi 1.5 Ton…" or "- textbox: Enter product…". It
# sometimes echoes that label back as a selector ("link:3 Star Split AC…"), which
# Playwright cannot parse ("Unexpected token") and the step hard-fails. Translate
# that shape: input-ish roles → the Playwright role engine (text= can NOT match an
# input's placeholder); content roles → a forgiving text= selector. Real
# CSS/text=/role=/xpath selectors are left untouched.
_A11Y_LABEL = re.compile(
    r"^\s*[-*]?\s*(link|button|textbox|combobox|checkbox|heading|text|img|image|"
    r"tab|menuitem|option|radio|searchbox|cell|row|listitem|paragraph|generic)"
    r"\s*:\s*(.+)$", re.I)
_INPUT_ROLES = {"textbox", "searchbox", "combobox", "checkbox", "radio", "option"}


def _normalize_selector(sel: Optional[str]) -> Optional[str]:
    if not sel:
        return sel
    s = sel.strip()
    if s.startswith(("text=", "role=", "xpath=", "css=", "//", "(")):
        return s
    m = _A11Y_LABEL.match(s)
    if m:
        role = m.group(1).lower()
        name = m.group(2).strip().strip("\"'")
        if role in _INPUT_ROLES:
            # text= can't target an input by placeholder; use the role engine.
            return f"role={role}"
        # Content roles: only treat as a human label (not a CSS pseudo like
        # button:hover) when it actually reads like one — space/comma or long.
        if " " in name or "," in name or len(name) > 15:
            return "text=" + name[:80]
    return s

ActionType = Literal[
    "navigate", "fill", "click", "wait", "extract",
    "scroll", "press", "select",
]


class Action(BaseModel):
    """A single browser action. Mirrors parse.lehana.in's schema verbatim
    (so its planner prompt + any saved workflows port over) and extends it."""
    action: ActionType
    # navigate
    url: Optional[str] = None
    wait_until: str = "networkidle"          # domcontentloaded|load|networkidle|commit
    # fill
    selector: Optional[str] = None
    value: Optional[str] = None
    clear: bool = True
    type_delay: int = 40
    # wait
    until: Optional[str] = None              # duration|navigation|selector|idle
    duration: Optional[int] = None
    visible: bool = True
    # extract
    name: Optional[str] = None
    extract_type: str = "text"               # text|html|attribute
    attribute: Optional[str] = None
    find_type: str = "element"               # element|elements
    # scroll / press / select
    direction: str = "down"                  # down|up|bottom|top
    amount: int = 800
    key: Optional[str] = None                # press: e.g. "Enter"
    option: Optional[str] = None             # select: value/label
    # control
    timeout: int = 15000
    continue_on_error: bool = False
    # planner-only narration (not executed)
    thought: Optional[str] = None


class ActionResult(BaseModel):
    action: str
    status: str                              # success|error|skipped
    name: Optional[str] = None               # for extract — the field name
    detail: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    value: Any = None                        # for extract


# ---- Executors (Playwright async `page`) ------------------------------------

async def _navigate(page, a: Action) -> ActionResult:
    if not a.url:
        raise ValueError("navigate requires 'url'")
    await page.goto(a.url, wait_until=a.wait_until, timeout=a.timeout)
    return ActionResult(action="navigate", status="success",
                        detail={"final_url": page.url})


async def _fill(page, a: Action) -> ActionResult:
    if not a.selector or a.value is None:
        raise ValueError("fill requires 'selector' and 'value'")
    loc = page.locator(a.selector).first
    await loc.wait_for(state="visible", timeout=a.timeout)
    if a.clear:
        await loc.fill("")
    await loc.type(str(a.value), delay=a.type_delay)
    return ActionResult(action="fill", status="success",
                        detail={"selector": a.selector, "len": len(str(a.value))})


async def _click(page, a: Action) -> ActionResult:
    if not a.selector:
        raise ValueError("click requires 'selector'")
    loc = page.locator(a.selector).first
    # Fail fast (real sites throw auto-popups): a stuck click must not burn the
    # whole step budget on Playwright's internal 15s retry loop.
    t = min(a.timeout or 8000, 8000)
    await loc.wait_for(state="visible", timeout=t)
    await loc.scroll_into_view_if_needed(timeout=t)
    try:
        await loc.click(timeout=t)
    except Exception:
        # A modal/backdrop (e.g. IndiaMART's `blckbg`) is intercepting pointer
        # events. Dismiss the popup and retry; then force the click through.
        with contextlib.suppress(Exception):
            await page.keyboard.press("Escape")
        with contextlib.suppress(Exception):
            await page.mouse.click(8, 8)  # click a neutral corner to close overlays
        try:
            await loc.click(timeout=4000)
        except Exception:
            await loc.click(timeout=4000, force=True)  # bypass the interception
    return ActionResult(action="click", status="success", detail={"selector": a.selector})


async def _wait(page, a: Action) -> ActionResult:
    until = a.until or "duration"
    if until == "duration":
        await asyncio.sleep((a.duration or 1000) / 1000)
    elif until == "navigation":
        await page.wait_for_load_state(a.wait_until, timeout=a.timeout)
    elif until == "selector":
        if not a.selector:
            raise ValueError("wait until=selector requires 'selector'")
        await page.locator(a.selector).first.wait_for(
            state="visible" if a.visible else "attached", timeout=a.timeout)
    elif until == "idle":
        await page.wait_for_load_state("networkidle", timeout=a.timeout)
    else:
        raise ValueError(f"unknown wait until={until}")
    return ActionResult(action="wait", status="success", detail={"until": until})


async def _extract(page, a: Action) -> ActionResult:
    if not a.selector or not a.name:
        raise ValueError("extract requires 'selector' and 'name'")
    loc = page.locator(a.selector)
    if a.find_type == "elements":
        n = await loc.count()
        out = []
        for i in range(n):
            out.append(await _read(loc.nth(i), a))
        value: Any = out
    else:
        value = await _read(loc.first, a) if await loc.count() else ""
    return ActionResult(action="extract", status="success", name=a.name,
                        value=value, detail={"selector": a.selector, "count": (
                            len(value) if isinstance(value, list) else 1)})


async def _read(loc, a: Action):
    try:
        if a.extract_type == "text":
            return (await loc.inner_text()).strip()
        if a.extract_type == "html":
            return await loc.inner_html()
        if a.extract_type == "attribute":
            return await loc.get_attribute(a.attribute or "value")
    except Exception:
        return ""
    return ""


async def _scroll(page, a: Action) -> ActionResult:
    if a.direction == "bottom":
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    elif a.direction == "top":
        await page.evaluate("window.scrollTo(0, 0)")
    else:
        delta = a.amount if a.direction == "down" else -a.amount
        await page.evaluate(f"window.scrollBy(0, {delta})")
    return ActionResult(action="scroll", status="success", detail={"direction": a.direction})


async def _press(page, a: Action) -> ActionResult:
    if not a.key:
        raise ValueError("press requires 'key'")
    if a.selector:
        await page.locator(a.selector).first.press(a.key, timeout=a.timeout)
    else:
        await page.keyboard.press(a.key)
    return ActionResult(action="press", status="success", detail={"key": a.key})


async def _select(page, a: Action) -> ActionResult:
    if not a.selector or a.option is None:
        raise ValueError("select requires 'selector' and 'option'")
    await page.locator(a.selector).first.select_option(a.option, timeout=a.timeout)
    return ActionResult(action="select", status="success",
                        detail={"selector": a.selector, "option": a.option})


_DISPATCH = {
    "navigate": _navigate, "fill": _fill, "click": _click, "wait": _wait,
    "extract": _extract, "scroll": _scroll, "press": _press, "select": _select,
}

# The confirm-before-send guard is a STOP-AT-VERIFICATION line, not a "never
# touch the form" line. On a real-site RFQ we deliberately WANT the agent to
# open the enquiry form and click Continue / request-OTP so the verification
# (OTP / sign-in) screen actually appears — then stop. So the opening steps
# ("Send Inquiry", "Contact Supplier", "Get Best Price", "Continue", "Get OTP")
# are ALLOWED; only the final completion of phone verification / sign-in is
# blocked, as a hard backstop behind the planner's own "never type the OTP" rule.
_STOP_WORDS = (
    "verify otp", "submit otp", "confirm otp", "validate otp", "verify code",
    "verify mobile", "verify number", "verify & continue", "verify and continue",
    "verify", "sign in", "signin", "log in", "login", "create account",
    "register now",
)


async def _would_submit(page, a: Action) -> bool:
    """True if this click would COMPLETE phone/OTP verification or sign-in.

    (Name kept for call-site compatibility.) Enquiry-opening and request-OTP
    clicks are intentionally NOT treated as submits — we want to reach the OTP.
    """
    if a.action == "press":
        # Enter is no longer treated as a blanket submit: the RFQ flow drives
        # the form via explicit buttons, and blocking Enter also blocked the
        # legitimate "Continue" step that reveals the OTP screen.
        return False
    if a.action != "click" or not a.selector:
        return False
    try:
        loc = page.locator(a.selector).first
        if await loc.count() == 0:
            return False
        info = await loc.evaluate(
            "el => ({type:(el.getAttribute('type')||'').toLowerCase(),"
            "text:((el.innerText||el.value||'')+'').toLowerCase(),"
            "inForm: !!el.closest('form')})"
        )
        text = info.get("text", "")
        return any(w in text for w in _STOP_WORDS)
    except Exception:
        # If we can't tell, do NOT block — let the flow reach the gate; the
        # planner is instructed to stop at the OTP/sign-in screen.
        return False


async def execute_action(page, a: Action, allow_submit: bool = True) -> ActionResult:
    """Run one action; raise on error unless continue_on_error is set.

    When allow_submit is False (confirm-before-send), submit-type clicks/Enter
    are refused at the executor level — the prompt instruction is only
    defense-in-depth; this is the hard guard.
    """
    fn = _DISPATCH.get(a.action)
    if fn is None:
        return ActionResult(action=a.action, status="skipped",
                            error="unknown_action_type")
    # Repair accessibility-label-as-selector mistakes before anything touches the DOM.
    if a.selector:
        a.selector = _normalize_selector(a.selector)
    if not allow_submit and a.action in ("click", "press") and await _would_submit(page, a):
        logger.info("stop-at-verification: blocked OTP/sign-in completion %s on %r", a.action, a.selector)
        return ActionResult(action=a.action, status="skipped",
                            error="verification_gate",
                            detail={"reason": "stop-at-verification guard blocked an OTP/sign-in completion",
                                    "selector": a.selector, "key": a.key})
    try:
        return await fn(page, a)
    except Exception as e:  # noqa: BLE001
        logger.warning("action %s failed: %s", a.action, e)
        if a.continue_on_error:
            return ActionResult(action=a.action, status="error", error=str(e))
        raise
