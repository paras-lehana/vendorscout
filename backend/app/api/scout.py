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

# The 9 evaluation dimensions VendorScout claims (keep this order everywhere).
DIMENSIONS = ["relevance", "compliance", "financial", "risk", "authenticity",
              "reputation", "capability", "price", "specification"]

SCORE_SYS = (
    "You are VendorScout, a procurement analyst. You are given a buyer requirement and suppliers "
    "scraped live from an Indian B2B marketplace (IndiaMART), each with an `available` map telling "
    "you which of the 9 evaluation dimensions are actually evidenced in that listing.\n"
    "Score and rank RELATIVELY across THIS set (not absolute): the best price in the set scores ~100 "
    "on price, the most complete specs ~100 on specification, etc. Spread scores so the best options "
    "stand out — never bunch everyone at 30-40.\n"
    "HONESTY (critical): For a dimension, set verifiable=true and a numeric score ONLY if `available` "
    "says so. For dimensions with no evidence in the listing (typically compliance, financial, risk, "
    "reputation, capability), set verifiable=false, score=null, and note=\"Not shown on listing — verify "
    "on supplier visit\". NEVER invent certifications, turnover, ratings, or capacity.\n"
    "Return ONLY JSON:\n"
    '{"executive_summary":"3 crisp plain-language lines: the best pick, why, and the price spread",'
    '"vendors":[{"name":..,"product":..,"price":..,"location":..,"url":..,'
    '"score":0-100,"recommendation":"Preferred|Consider|Caution",'
    '"highlights":["3-5 measurable factors, <=10 words each"],'
    '"evidence":{"relevance":{"score":0-100|null,"note":"<=10 words","verifiable":true|false,"where":"short source|null"},'
    '"compliance":{...},"financial":{...},"risk":{...},"authenticity":{...},"reputation":{...},'
    '"capability":{...},"price":{...},"specification":{...}}}]}\n'
    "Copy name/product/price/location/url EXACTLY from the input. Rank best overall first. "
    "`where` is a short pointer like 'Listing title', 'Listed price', 'Spec sheet', 'IndiaMART product page'."
)

ASK_SYS = (
    "You are VendorScout's analyst answering a buyer's follow-up question about ONE sourcing report. "
    "Use ONLY the provided report (ranked vendors, per-dimension evidence, scores) and the raw scraped "
    "listings. Explain WHY a score/rank is what it is when asked, citing the evidence. Be crisp (2-5 "
    "sentences, lists ok). If the answer isn't in the data, say so plainly and, if useful, suggest a "
    "fresh/deeper scrape — do NOT invent certifications, prices, ratings, or financials."
)


def _evidence_availability(v: dict) -> dict:
    """Deterministically decide which of the 9 dimensions are actually evidenced
    by an IndiaMART catalog listing — so the LLM cannot over-claim verifiability."""
    specs = v.get("specs") or {}
    has_specs = bool(specs) or any(c.isdigit() for c in str(v.get("product", "")))
    return {
        "relevance": {"verifiable": True, "where": "Listing title"},
        "price": {"verifiable": _has_price(v), "where": "Listed price"},
        "specification": {"verifiable": has_specs, "where": "Listing spec sheet"},
        "authenticity": {"verifiable": _is_indiamart_product_url(v.get("url")),
                         "where": "IndiaMART product page"},
        "compliance": {"verifiable": False, "where": None},
        "financial": {"verifiable": False, "where": None},
        "risk": {"verifiable": False, "where": None},
        "reputation": {"verifiable": False, "where": None},
        "capability": {"verifiable": False, "where": None},
    }


def _enforce_honesty(report: dict, raw_vendors: list[dict]) -> dict:
    """Post-process the LLM report: clamp verifiable flags to what the listing
    actually supports, and guarantee a clickable source url per vendor."""
    by_name = {str(x.get("name", "")).strip().lower(): x for x in raw_vendors}
    for v in report.get("vendors", []):
        src = by_name.get(str(v.get("name", "")).strip().lower(), {})
        if src.get("url") and not v.get("url"):
            v["url"] = src["url"]
        avail = _evidence_availability(src or v)
        ev = v.get("evidence") or {}
        fixed = {}
        for dim in DIMENSIONS:
            cell = ev.get(dim) or {}
            ok = avail.get(dim, {}).get("verifiable", False)
            if not ok:  # listing has no evidence → force honest "not shown"
                fixed[dim] = {"score": None, "verifiable": False, "where": None,
                              "note": cell.get("note") or "Not shown on listing — verify on supplier visit"}
            else:
                fixed[dim] = {"score": cell.get("score"),
                              "verifiable": True,
                              "where": cell.get("where") or avail[dim]["where"],
                              "note": (cell.get("note") or "")[:80]}
        v["evidence"] = fixed
    return report


async def _emit(q: asyncio.Queue, run_id: str, ev: dict):
    try:
        await q.put({**ev, "runId": run_id})
    except Exception:  # noqa: BLE001
        pass


def _has_price(v: dict) -> bool:
    p = str(v.get("price") or "")
    return any(c.isdigit() for c in p)


def _is_indiamart_product_url(url) -> bool:
    """A REAL, clickable IndiaMART listing URL (so a buyer can verify the product)
    — not a planner-hallucinated slug. Catalog parses these from actual HTML."""
    u = str(url or "").lower()
    return "indiamart.com/proddetail" in u or "indiamart.com/impcat" in u


def _real_urls(vendors) -> bool:
    if not isinstance(vendors, list) or not vendors:
        return False
    return sum(1 for v in vendors if isinstance(v, dict)
               and _is_indiamart_product_url(v.get("url"))) >= max(2, len(vendors) // 2)


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

        async def on_update(ev: dict):
            await _emit(q, run_id, ev)  # forward live browser STEP/FRAME/RECOVER frames

        # ---- 2a. Pull REAL, verifiable data from IndiaMART's live catalog FIRST ----
        # (IndiaMART's JS search box is anti-bot protected — driving it headlessly is
        # unreliable and the planner can hallucinate fake names/URLs. The catalog/SEO
        # pages are server-rendered with real `proddetail` URLs a buyer can click.)
        await _emit(q, run_id, {"type": "PHASE", "phase": "scout",
                                "message": f"Scouting IndiaMART for “{search_query}”…"})
        catalog, cat_url = await fetch_seo_suppliers(search_query, req.max_vendors)

        # ---- 2b. THEATER: browse that REAL listings page live (no search box) ----
        theater_url = cat_url or MARKETPLACE_URL
        await _emit(q, run_id, {"type": "STEP",
                                "thought": f"Opening the live IndiaMART listings page for “{search_query}” and reading the suppliers shown…"})
        review_goal = (
            f"You are viewing an IndiaMART listings page for '{search_query}'. Scroll and READ the "
            f"supplier listings already shown on THIS page — note product names, prices and locations "
            f"into `extracted` as {{\"vendors\":[{{\"name\":..,\"product\":..,\"price\":..,\"location\":..,\"url\":..}}]}}. "
            f"Do NOT use the search box and do NOT navigate to other sites — just review what is on this page."
        )
        result = await _browser.run_task_streaming(
            url=theater_url, goal=review_goal, on_update=on_update,
            timeout=90, max_steps=6, allow_submit=False)
        raw = result.extracted_data if isinstance(result.extracted_data, dict) else {}
        browser_vendors = raw.get("vendors") or raw.get("suppliers") or []
        if not isinstance(browser_vendors, list):
            browser_vendors = []

        # ---- 2c. Choose the most TRUSTWORTHY data source (catalog wins) ----
        if catalog:
            vendors, source = catalog, "catalog"
        elif _usable(browser_vendors) and _real_urls(browser_vendors):
            vendors, source = browser_vendors, "live"
        else:
            seed = load_seed_suppliers(search_query, req.max_vendors)
            if seed:
                vendors, source = seed, "sample"
            else:
                vendors, source = (browser_vendors or []), "live"
        st["raw_vendors"] = vendors
        st["source"] = source
        if vendors:
            sample = ", ".join(str(v.get("name", "")) for v in vendors[:3] if v.get("name"))
            await _emit(q, run_id, {"type": "STEP",
                                    "thought": f"Verified {len(vendors)} suppliers on IndiaMART (e.g. {sample}) — each with a clickable product link."})
        await _emit(q, run_id, {"type": "SCOUTED", "count": len(vendors), "source": source})

        # ---- 3. SCORE (relative, evidence-based across the 9 dimensions) ----
        report = {"summary": "", "executive_summary": "", "vendors": [],
                  "query": req.query, "parsed": parsed, "source": source,
                  "dimensions": DIMENSIONS}
        if vendors:
            await _emit(q, run_id, {"type": "PHASE", "phase": "score",
                                    "message": f"Comparing {len(vendors)} suppliers across 9 checks…"})
            await _emit(q, run_id, {"type": "STEP",
                                    "thought": "Scoring relatively: relevance, price & specs are read from the listing; compliance/financial/risk need a supplier visit."})
            # Attach deterministic availability so the model can't over-claim.
            enriched = [{**v, "available": _evidence_availability(v)} for v in vendors]
            scored = await _llm.generate_structured(
                prompt=(f"Buyer requirement: {json.dumps(parsed)}\n\nQuery: {req.query}\n\n"
                        f"Suppliers (with `available` evidence flags):\n{json.dumps(enriched)[:9000]}"),
                system_prompt=SCORE_SYS) or {}
            report["executive_summary"] = scored.get("executive_summary", "")
            report["summary"] = scored.get("executive_summary", "")  # back-compat
            report["vendors"] = scored.get("vendors") or vendors
            report = _enforce_honesty(report, vendors)
        else:
            report["executive_summary"] = report["summary"] = (
                "No suppliers could be extracted for this query. Try a more specific "
                "product name (e.g. 'Hitachi 1.5 ton split AC').")

        st["status"] = "completed"
        st["report"] = report
        await _emit(q, run_id, {"type": "REPORT", "report": report,
                                "num_steps": result.num_steps,
                                "duration_ms": result.duration_ms})

        # ---- 4. ACT — autonomously draft an enquiry to the TOP match ----
        # The agent doesn't wait to be asked: it opens the #1 supplier's real
        # IndiaMART page, fills the enquiry with dummy buyer details, and STOPS at
        # the Sign-In / Send-OTP gate (confirm-before-send). Best-effort: it never
        # breaks the report. Users can re-run it on any product from the report.
        top = next((v for v in report["vendors"]
                    if _is_indiamart_product_url(v.get("url"))), None)
        if top:
            await _emit(q, run_id, {"type": "PHASE", "phase": "act",
                                    "message": f"Drafting an enquiry to the top match — {top.get('name')}…"})
            try:
                rfq_goal = (
                    f"You are on the IndiaMART product page for '{top.get('product') or top.get('name')}'. "
                    "Start a Request-for-Quote: open 'Get Best Price' / 'Send Enquiry' (if a login or "
                    "enquiry popup is already open, work WITH it — do not click behind a backdrop). FILL "
                    "the enquiry form with DUMMY buyer details — Quantity:'12', Requirement:'Need 12 units "
                    "in bulk; share best price, MOQ, lead time, certifications.', Mobile:'9000000000', "
                    "Name:'Demo Buyer', Email:'buyer@example.com'. Then STOP — do NOT sign in / send OTP / "
                    "submit (we confirm before sending). Return JSON {filled:true, fields_filled:[...], "
                    "stopped_at:'<the Sign-In/OTP/submit gate you reached>'}."
                )
                act = await _browser.run_task_streaming(
                    url=top["url"], goal=rfq_goal, on_update=on_update,
                    timeout=80, max_steps=7, allow_submit=False)
                ext = act.extracted_data if isinstance(act.extracted_data, dict) else {}
                await _emit(q, run_id, {"type": "ACTION", "result": {
                    "vendor": top.get("name"), "url": top.get("url"),
                    "filled": bool(ext.get("filled") or ext.get("fields_filled")),
                    "fields_filled": ext.get("fields_filled") or [],
                    "stopped_at": ext.get("stopped_at") or "supplier's Sign-In / OTP gate",
                    "status": "drafted_stopped_before_send"}})
            except Exception as e:  # noqa: BLE001 — ACT is best-effort
                logger.warning("auto-RFQ failed for %s: %s", run_id, e)
                await _emit(q, run_id, {"type": "ACTION", "result": {
                    "vendor": top.get("name"), "url": top.get("url"),
                    "status": "incomplete",
                    "stopped_at": "could not reach the enquiry form (site popup/anti-bot)"}})
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


class AskRequest(BaseModel):
    question: str
    report: dict | None = None   # client-provided fallback (survives restarts/reloads)


@router.post("/{run_id}/ask")
async def ask_scout(run_id: str, body: AskRequest):
    """Answer a buyer's follow-up about THIS report at runtime, grounded in the
    report's reasoning. Stateless-resilient: uses the server's stored run when it
    exists (richer — includes raw listings), otherwise the report the client sends
    (so Q&A keeps working after a redeploy/restart or on a reloaded session)."""
    st = _RUNS.get(run_id)
    report = (st or {}).get("report") or body.report
    if not report:
        return JSONResponse({"error": "no report available to answer from"}, status_code=404)
    context = {
        "query": report.get("query"),
        "requirement": report.get("parsed"),
        "data_source": report.get("source"),
        "executive_summary": report.get("executive_summary"),
        "ranked_vendors": report.get("vendors"),
        "raw_listings": (st or {}).get("raw_vendors") or report.get("vendors", []),
    }
    answer = await _llm.generate_text(
        prompt=(f"REPORT DATA (JSON):\n{json.dumps(context)[:11000]}\n\n"
                f"Buyer question: {body.question.strip()}\n\nAnswer:"),
        system_prompt=ASK_SYS) or "Sorry — I couldn't answer that from this report."
    return {"answer": answer}


SESSION_SYS = (
    "You are VendorScout. The buyer ran several sourcing searches this session; each has its ranked "
    "suppliers (real IndiaMART listings). Produce ONE consolidated, decision-ready report across ALL of "
    "them. Return ONLY JSON: {\"executive_summary\":\"3-4 plain lines spanning all searches\","
    "\"pointers\":[\"10-15 crisp takeaways, <=15 words each — best pick per search, price ranges, what is "
    "verified vs needs a supplier visit, and cross-search insights\"],"
    "\"best_overall\":{\"query\":..,\"name\":..,\"price\":..,\"why\":\"<=15 words\"}}. "
    "Use the REAL names/prices provided. Do NOT invent suppliers, certifications or numbers."
)


class SessionReportRequest(BaseModel):
    searches: list[dict] = []   # [{query, vendors:[{name,price,location,score,recommendation,url}]}]


@router.post("/session-report")
async def session_report(body: SessionReportRequest):
    """Consolidated 10-15 pointer report across every search in the session."""
    searches = [s for s in (body.searches or []) if s.get("vendors")]
    if not searches:
        return JSONResponse({"error": "no searches with results in this session yet"}, status_code=400)
    out = await _llm.generate_structured(
        prompt=f"Sourcing searches this session (JSON):\n{json.dumps(searches)[:11000]}",
        system_prompt=SESSION_SYS) or {}
    out.setdefault("executive_summary", "")
    out.setdefault("pointers", [])
    out["search_count"] = len(searches)
    return out
