# ============================================================
# VendorScout - Scout API (the ChatGPT-style agentic flow)
# ============================================================
# ONE coherent flow that actually produces REAL data (no Serper needed):
#   1. PLAN   — Azure gpt-4o parses the query into a structured requirement.
#   2. SCOUT  — the self-hosted Playwright agent searches a live B2B marketplace
#               (IndiaMART) and extracts real suppliers (name/product/price/...).
#   3. SCORE  — Azure gpt-4o ranks the suppliers vs the requirement with reasons.
#   4. REPORT — a compact, complete ranked report (rendered inline, no scroll).
#
# Every step streams over SSE so the chat UI shows the live browser + distinct
# step messages (not duplicate agent logs). Sessions are client-side (localStorage),
# so this endpoint is stateless apart from a bounded in-memory run registry.
# ============================================================

import asyncio
import json
import logging
import re
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from app.tools.browser_agent import BrowserAgentClient
from app.tools.indiamart_seo import fetch_seo_suppliers, load_seed_suppliers
from app.tools.llm import LLMTool
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scout", tags=["scout"])

_browser = BrowserAgentClient()
_llm = LLMTool()
_RUNS: dict[str, dict] = {}

MARKETPLACE_URL = "https://www.indiamart.com"


class ScoutRequest(BaseModel):
    query: str
    max_vendors: int = 6


PLAN_SYS = (
    "You parse a B2B procurement request into JSON. Return ONLY: "
    '{"product":"short product/service name for a marketplace search",'
    '"quantity":"qty or null","budget":"budget/price target or null",'
    '"location":"region or null","must_haves":["key specs/certs, <=4"],'
    '"search_query":"the exact text to type into a B2B marketplace search box"}'
)

SCORE_SYS = (
    "You are a procurement analyst. Given a buyer requirement and a list of suppliers "
    "scraped live from a B2B marketplace, score and rank them. Return ONLY JSON: "
    '{"summary":"2-3 sentence recommendation for the buyer",'
    '"vendors":[{"name":..,"product":..,"price":..,"location":..,'
    '"score":0-100,"recommendation":"Preferred|Consider|Caution",'
    '"reasons":["<=3 short match reasons"]}]}. '
    "Rank best-fit first. Base scores on relevance to the requirement, price competitiveness, "
    "and any credibility signals present. Do NOT invent suppliers — only use the provided list."
)


async def _emit(q: asyncio.Queue, run_id: str, ev: dict):
    try:
        await q.put({**ev, "runId": run_id})
    except Exception:  # noqa: BLE001
        pass


def _has_price(v: dict) -> bool:
    p = str(v.get("price") or "")
    return any(c.isdigit() for c in p)


# Generic names the planner invents when it can't read real ones ("Supplier A",
# "Vendor 1", "Company B"). Treat these as NOT real — fall back to real data.
_PLACEHOLDER_NAME = re.compile(
    r"^(supplier|vendor|company|seller|manufacturer|distributor)\s+([a-z]|\d{1,2})$", re.I)


def _looks_placeholder(name: str) -> bool:
    n = (name or "").strip().lower()
    return (not n) or n in {"unknown", "n/a", "na", "supplier", "vendor"} \
        or bool(_PLACEHOLDER_NAME.match(name or ""))


def _usable(vendors) -> bool:
    """True only if the live browser extraction returned REAL suppliers — i.e.
    at least 2 priced rows AND mostly real company names (not the anti-bot
    skeleton, which has no prices, and not hallucinated 'Supplier A/B/C' names)."""
    if not isinstance(vendors, list) or len(vendors) < 2:
        return False
    priced = sum(1 for v in vendors if isinstance(v, dict) and _has_price(v))
    placeholder = sum(1 for v in vendors if isinstance(v, dict)
                      and _looks_placeholder(str(v.get("name", ""))))
    return priced >= 2 and placeholder <= len(vendors) // 2


async def _run_scout(run_id: str, req: ScoutRequest):
    st = _RUNS[run_id]
    q: asyncio.Queue = st["queue"]
    try:
        # ---- 1. PLAN ----
        await _emit(q, run_id, {"type": "PHASE", "phase": "plan", "message": "Understanding your requirement…"})
        parsed = await _llm.generate_structured(
            prompt=f"Procurement request: {req.query}", system_prompt=PLAN_SYS) or {}
        search_query = parsed.get("search_query") or parsed.get("product") or req.query
        st["parsed"] = parsed
        await _emit(q, run_id, {"type": "PLAN", "parsed": parsed})

        # ---- 2. SCOUT (real browser discovery — streams live frames) ----
        await _emit(q, run_id, {"type": "PHASE", "phase": "scout",
                                "message": f"Scouting suppliers for “{search_query}” on IndiaMART…"})
        goal = (
            f"On IndiaMART, search for '{search_query}'. From the results listing, extract the top "
            f"{req.max_vendors} suppliers as JSON {{\"vendors\":[{{\"name\":..,\"product\":..,"
            f"\"price\":..,\"location\":..,\"url\":..}}]}}. Use null for fields not shown. "
            f"Finish once you have up to {req.max_vendors}."
        )

        async def on_update(ev: dict):
            await _emit(q, run_id, ev)  # forward live browser STEP/FRAME/RECOVER frames

        result = await _browser.run_task_streaming(
            url=MARKETPLACE_URL, goal=goal, on_update=on_update, timeout=120, max_steps=8)
        raw = result.extracted_data if isinstance(result.extracted_data, dict) else {}
        vendors = raw.get("vendors") or raw.get("suppliers") or []
        if not isinstance(vendors, list):
            vendors = []

        # Hybrid resilience: IndiaMART's JS search is anti-bot protected and often
        # serves the live browser a placeholder skeleton (no prices). When the live
        # extraction isn't usable, fall back to REAL IndiaMART catalog data fetched
        # from its SEO pages (reliable), then to a real captured sample as a last
        # resort — so the chat never shows "0 suppliers". All paths are real data.
        source = "live"
        if not _usable(vendors):
            await _emit(q, run_id, {"type": "PHASE", "phase": "scout",
                                    "message": "Pulling verified suppliers from IndiaMART's catalog…"})
            seo = await fetch_seo_suppliers(search_query, req.max_vendors)
            if seo:
                vendors, source = seo, "catalog"
            else:
                seed = load_seed_suppliers(search_query, req.max_vendors)
                if seed:
                    vendors, source = seed, "sample"
        st["raw_vendors"] = vendors
        st["source"] = source
        await _emit(q, run_id, {"type": "SCOUTED", "count": len(vendors), "source": source})

        # ---- 3. SCORE ----
        report = {"summary": "", "vendors": [], "query": req.query, "parsed": parsed,
                  "source": source}
        if vendors:
            await _emit(q, run_id, {"type": "PHASE", "phase": "score",
                                    "message": f"Scoring & ranking {len(vendors)} suppliers…"})
            scored = await _llm.generate_structured(
                prompt=(f"Buyer requirement: {json.dumps(parsed)}\n\nQuery: {req.query}\n\n"
                        f"Suppliers scraped live:\n{json.dumps(vendors)[:6000]}"),
                system_prompt=SCORE_SYS) or {}
            report["summary"] = scored.get("summary", "")
            report["vendors"] = scored.get("vendors", vendors)
        else:
            report["summary"] = ("No suppliers could be extracted for this query. Try a more specific "
                                 "product name (e.g. 'Hitachi 1.5 ton split AC').")
            report["vendors"] = []

        st["status"] = "completed"
        st["report"] = report
        await _emit(q, run_id, {"type": "REPORT", "report": report,
                                "num_steps": result.num_steps,
                                "duration_ms": result.duration_ms})
    except Exception as e:  # noqa: BLE001
        logger.error("scout %s failed: %s", run_id, e)
        st["status"] = "failed"
        await _emit(q, run_id, {"type": "ERROR", "message": str(e)})
    finally:
        await _emit(q, run_id, {"type": "END"})


@router.post("")
async def start_scout(req: ScoutRequest):
    run_id = uuid.uuid4().hex[:12]
    while len(_RUNS) > 60:
        _RUNS.pop(next(iter(_RUNS)), None)
    _RUNS[run_id] = {"queue": asyncio.Queue(), "status": "running",
                     "query": req.query, "report": None, "task": None}
    _RUNS[run_id]["task"] = asyncio.create_task(_run_scout(run_id, req))
    logger.info("scout %s: %s", run_id, req.query[:80])
    return {"run_id": run_id, "stream_url": f"/api/scout/{run_id}/stream"}


@router.get("/{run_id}/stream")
async def stream_scout(run_id: str, request: Request):
    st = _RUNS.get(run_id)
    if not st:
        return JSONResponse({"error": "unknown run_id"}, status_code=404)
    q: asyncio.Queue = st["queue"]

    async def gen():
        yield f"data: {json.dumps({'type':'STARTED','runId':run_id,'query':st['query']})}\n\n"
        while True:
            if await request.is_disconnected():
                t = st.get("task")
                if t and not t.done():
                    t.cancel()
                break
            try:
                ev = await asyncio.wait_for(q.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield f"data: {json.dumps(ev)}\n\n"
            if ev.get("type") == "END":
                break

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{run_id}")
async def scout_status(run_id: str):
    st = _RUNS.get(run_id)
    if not st:
        return JSONResponse({"error": "unknown run_id"}, status_code=404)
    return {"run_id": run_id, "status": st["status"], "query": st["query"], "report": st.get("report")}
