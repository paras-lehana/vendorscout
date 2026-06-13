# ============================================================
# VendorScout - Agentic planner (Azure OpenAI)
# ============================================================
# The "PLAN" step of the observe -> plan -> act -> verify -> recover loop.
#
# Given a natural-language goal, the current page observation (URL + trimmed
# accessibility/DOM text, and optionally a screenshot), and the action history
# (including any errors), the planner returns the NEXT 1-3 typed browser
# actions, a short human "thought", whether the task is done, and any
# structured data it has extracted so far.
#
# System prompt adapted from parse.lehana.in's ai_prompts.py
# (build_system_prompt) — same action schema, same complete/partial/failed
# discipline — but driven step-by-step for resilience instead of one-shot.
# ============================================================

from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from app.tools.actions import Action
from app.tools.json_parser import parse_json_robust

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """You are VendorScout's autonomous web-browsing agent. You drive a real \
Chromium browser (via Playwright) to accomplish a goal on live websites: navigating, clicking, \
typing into forms, extracting data, and completing multi-step transactions (e.g. submitting an \
RFQ/enquiry). You work step by step: at each step you SEE the current page and decide the next \
1-3 actions.

## OUTPUT — respond with ONLY this JSON object (no markdown, no prose):
{
  "thought": "one short sentence: what you see and what you'll do next",
  "actions": [ <0-3 action objects, see schema> ],
  "done": false,
  "extracted": {}      // structured data gathered so far (use null for missing fields)
}

Set "done": true (and "actions": []) ONLY when the goal is fully achieved; put the final result in "extracted".

## ACTION SCHEMA — each action's key is "action" (NEVER "type"):
- navigate:  {"action":"navigate","url":"https://...","wait_until":"domcontentloaded"}
- click:     {"action":"click","selector":"CSS or text= selector"}
- fill:      {"action":"fill","selector":"#q","value":"text","clear":true}
- wait:      {"action":"wait","until":"selector|navigation|idle|duration","selector":".x","duration":1500}
- extract:   {"action":"extract","name":"vendors","selector":".card","extract_type":"text","find_type":"elements"}
- scroll:    {"action":"scroll","direction":"down|up|bottom|top","amount":800}
- press:     {"action":"press","key":"Enter","selector":"#q"}
- select:    {"action":"select","selector":"#dropdown","option":"value-or-label"}

## SELECTOR RULES
- Prefer robust selectors: ids, name=, aria-label, Playwright text engine ("text=Send Enquiry"), role-based.
- INPUTS / SEARCH BOXES: `text=` matches VISIBLE text, NOT placeholder text — never target an input by its
  placeholder via text=. Use the role instead: `role=searchbox`, `role=combobox`, or `role=textbox`
  (a snapshot line "- textbox: Enter product / service to search" → selector `role=textbox`), or a
  `[placeholder="…"]` / `#id` / `[name="…"]` CSS selector. e.g. fill {"selector":"role=searchbox","value":"…"}.
- Avoid brittle deep CSS chains. If the page changed since last step, re-read the snapshot and adapt.
- After a click that loads/AJAXes, add a wait (until=selector or idle) before extracting.
- A selector is NOT the snapshot line. The snapshot shows accessibility lines like
  "- link: 3 Star Split AC …" — that text is the element's NAME, not a selector. Never
  put "link: …" or "button: …" in a "selector" field; use "text=3 Star Split AC" instead.

## GATHERING LIST DATA (e.g. suppliers, products, search results) — IMPORTANT
- The page snapshot you are given ALREADY contains the visible listing text (names, prices,
  locations). To collect such data, DO NOT emit per-row `extract` actions with guessed
  selectors — that is brittle and usually fails. Instead, READ the items straight from the
  snapshot and put them into the `extracted` object yourself, then continue (scroll for more)
  or set done=true.
- Example: {"thought":"6 suppliers are visible; recording them","actions":[],
  "extracted":{"vendors":[{"name":"ABC Traders","product":"Hitachi 1.5T AC","price":"₹35,200","location":"Chennai"}]}}
- Only use the `extract` action for a single specific value behind a clear selector
  (e.g. an acknowledgement number after submitting a form).

## RECOVERY (critical — this is what makes the agent resilient)
If the last action FAILED (see history), DO NOT repeat the SAME action with the SAME selector — that is
the #1 way to get stuck. Re-read the snapshot and change approach: a different selector, scroll to reveal,
dismiss the popup, or work WITH whatever is now on screen. Degrade gracefully: if a sub-goal is impossible,
record what you have in `extracted` and finish (done=true).

## POPUPS / MODALS / OVERLAYS (common on real sites)
Real marketplaces auto-open login/enquiry popups and dark backdrops that COVER the page (so clicks on
elements behind them fail with "intercepts pointer events"). When that happens:
- If the popup IS the form you need (it has phone / quantity / requirement fields), FILL IT directly —
  do not try to click the button behind the backdrop.
- If it is a login / "Sign In" / "Send OTP" wall, that is the stop point — record stopped_at and finish.
- Otherwise dismiss it: a press of "Escape", or click its ✕ / "close" / "Skip" control, THEN continue.
- Never click the same covered element repeatedly.

## CONFIRMING OUTCOMES (read this — it prevents getting stuck)
- After you click/submit, you AUTOMATICALLY get a fresh view of the page on the next step. Do NOT add a `wait` for a success selector you are guessing (e.g. ".green-box", ".success") — guessed-selector waits just time out and waste steps.
- To confirm something worked, READ the "visible page text" in the next observation. If it shows the expected result (e.g. "sent successfully", an acknowledgement/reference number, search results, the data you need), set done=true and put it in `extracted`.
- Use `wait` ONLY as a short settle: {"action":"wait","until":"duration","duration":1500}. Never wait on a selector you haven't actually seen in the snapshot.
- Don't re-fill or re-click a form you already submitted — check the visible text first.

## TRANSACTIONS
For RFQ/enquiry/contact forms: open the form, fill each field from the provided buyer/RFQ details,
then submit, then VERIFY a success/acknowledgement state and extract any reference text. Use null for
fields you cannot find — never invent data.

## SELF-CHECK before responding
- Pure JSON, no fences. Every action has an "action" key from the list above. Never use "type".
- 0-3 actions per step. "done" matches reality. "extracted" carries forward prior findings.
"""


class PlanStep(BaseModel):
    thought: str = ""
    actions: list[Action] = Field(default_factory=list)
    done: bool = False
    extracted: dict = Field(default_factory=dict)


def _build_user_prompt(goal: str, observation: dict, history: list[dict],
                       extracted: dict) -> str:
    parts = [
        f"## GOAL\n{goal}\n",
        f"## CURRENT PAGE\nURL: {observation.get('url','')}\n"
        f"Title: {observation.get('title','')}\n",
        "### Page snapshot (trimmed accessibility/DOM text):\n"
        f"{observation.get('snapshot','')[:6000]}\n",
    ]
    if extracted:
        parts.append(f"### Data extracted so far\n{json.dumps(extracted)[:1500]}\n")
    if history:
        parts.append("### Recent action history (most recent last)")
        for h in history[-8:]:
            status = h.get("status", "?")
            err = f" — ERROR: {h['error']}" if h.get("error") else ""
            parts.append(f"- {h.get('action')} [{status}]{err}")
        parts.append("")
    parts.append("Decide the next 1-3 actions (or done=true). Respond with ONLY the JSON object.")
    return "\n".join(parts)


async def plan_next_step(
    llm,
    goal: str,
    observation: dict,
    history: list[dict],
    extracted: dict,
    *,
    screenshot_b64: Optional[str] = None,
) -> PlanStep:
    """Ask the LLM (Azure OpenAI via the shared LLMTool) for the next step.

    Uses a text snapshot for grounding by default (cheap, fast); a screenshot
    can be attached for vision when the snapshot is insufficient. Robustly
    parses the JSON; on failure returns an empty step so the loop can recover.
    """
    user_prompt = _build_user_prompt(goal, observation, history, extracted)
    if screenshot_b64:
        user_prompt += "\n\n(A screenshot of the current page is attached — use it to locate elements.)"
    raw = await llm.generate_structured(
        prompt=user_prompt,
        system_prompt=PLANNER_SYSTEM_PROMPT,
        max_retries=2,
        image_b64=screenshot_b64,
    )
    if not raw or not isinstance(raw, dict):
        logger.warning("planner returned no/invalid JSON")
        return PlanStep(thought="(planner returned nothing — will re-observe)", actions=[], done=False)

    actions: list[Action] = []
    for item in raw.get("actions", []) or []:
        try:
            actions.append(Action(**item))
        except Exception as e:  # noqa: BLE001
            logger.warning("dropping malformed action %s: %s", item, e)
    return PlanStep(
        thought=str(raw.get("thought", "")),
        actions=actions,
        done=bool(raw.get("done", False)),
        extracted=raw.get("extracted") or {},
    )
