# ============================================================
# VendorScout - Agent Mission API (Live Browser Theater backend)
# ============================================================
# A focused vertical slice of the Agentic Web loop: give the agent a
# natural-language GOAL + a starting URL, it runs the self-hosted Playwright
# observe->plan->act->verify->recover loop, and every step (thought + live
# screenshot + recover events) is streamed to the browser over SSE so the
# user can WATCH the agent work — the "Live Browser Theater".
#
# Endpoints:
#   POST /api/mission            { goal, url } -> { run_id, stream_url }
#   GET  /api/mission/{id}/stream  SSE of {STARTED, STEP, RECOVER, COMPLETE, END}
#   GET  /api/mission/{id}         final status + extracted result
# ============================================================

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from app.tools.browser_agent import BrowserAgentClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mission", tags=["mission"])

# One shared browser client → Chromium launches once and is reused.
_client = BrowserAgentClient()

# run_id -> {"queue": asyncio.Queue, "status": str, "result": dict|None, "goal": str, "url": str}
_MISSIONS: dict[str, dict] = {}


class MissionRequest(BaseModel):
    goal: str
    url: str = "https://www.indiamart.com"
    max_steps: int | None = None
    allow_submit: bool | None = None   # confirm-before-send override (transaction demos)
    rfq: bool = False                  # deterministic RFQ-to-OTP flow (not the LLM loop)
    site: str = ""                     # marketplace label for the RFQ flow
    name: str = ""                     # product/supplier label for the RFQ flow


async def _run_mission(run_id: str, req: MissionRequest):
    state = _MISSIONS[run_id]
    queue: asyncio.Queue = state["queue"]

    async def on_update(event: dict):
        # Stamp the canonical client-facing run_id on EVERY frame so SSE
        # consumers never see the engine's internal id (which 404s on GET).
        event = {**event, "runId": run_id}
        try:
            await queue.put(event)
        except Exception:  # noqa: BLE001 — never let a dead consumer back-pressure the loop
            pass

    try:
        if req.rfq:
            # Deterministic Request-for-Quote: drive the enquiry form to the OTP
            # gate and stop. Reliable + watchable; not subject to LLM re-click loops.
            result = await _client.run_rfq_streaming(
                url=req.url, site=req.site, name=req.name,
                on_update=on_update, timeout=240,
            )
            await on_update({"type": "COMPLETE", "runId": run_id,
                             "status": "COMPLETED" if result.success else "FAILED",
                             "resultJson": result.extracted_data})
        else:
            result = await _client.run_task_streaming(
                url=req.url, goal=req.goal, on_update=on_update,
                timeout=240, max_steps=req.max_steps, allow_submit=req.allow_submit,
            )
        state["status"] = "completed" if result.success else "failed"
        state["result"] = {
            "success": result.success,
            "extracted": result.extracted_data,
            "num_steps": result.num_steps,
            "duration_ms": result.duration_ms,
            "error": result.error,
        }
        await queue.put({"type": "RESULT", "runId": run_id, **state["result"]})
    except Exception as e:  # noqa: BLE001
        logger.error("mission %s crashed: %s", run_id, e)
        state["status"] = "failed"
        state["result"] = {"success": False, "error": str(e)}
        await queue.put({"type": "ERROR", "runId": run_id, "message": str(e)})
    finally:
        await queue.put({"type": "END", "runId": run_id})


@router.post("")
async def start_mission(req: MissionRequest):
    """Kick off an agent mission; returns a run_id to stream."""
    run_id = uuid.uuid4().hex[:12]
    # Bound memory: keep only the most recent ~50 missions.
    while len(_MISSIONS) > 50:
        _MISSIONS.pop(next(iter(_MISSIONS)), None)
    _MISSIONS[run_id] = {
        "queue": asyncio.Queue(), "status": "running",
        "result": None, "goal": req.goal, "url": req.url, "task": None,
    }
    _MISSIONS[run_id]["task"] = asyncio.create_task(_run_mission(run_id, req))
    logger.info("mission %s started: %s @ %s", run_id, req.goal[:60], req.url)
    return {"run_id": run_id, "stream_url": f"/api/mission/{run_id}/stream"}


@router.get("/{run_id}/stream")
async def stream_mission(run_id: str, request: Request):
    """Server-Sent Events stream of the agent's live steps + screenshots."""
    state = _MISSIONS.get(run_id)
    if not state:
        return JSONResponse({"error": "unknown run_id"}, status_code=404)
    queue: asyncio.Queue = state["queue"]

    async def event_gen():
        # Announce the goal first so the UI has context immediately.
        yield _sse({"type": "GOAL", "runId": run_id, "goal": state["goal"], "url": state["url"]})
        while True:
            if await request.is_disconnected():
                logger.info("mission %s: client disconnected — cancelling run", run_id)
                task = state.get("task")
                if task and not task.done():
                    task.cancel()
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"   # comment frame keeps the connection warm
                continue
            yield _sse(event)
            if event.get("type") == "END":
                break

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.get("/{run_id}")
async def mission_status(run_id: str):
    state = _MISSIONS.get(run_id)
    if not state:
        return JSONResponse({"error": "unknown run_id"}, status_code=404)
    return {"run_id": run_id, "status": state["status"], "goal": state["goal"],
            "url": state["url"], "result": state["result"]}


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"
