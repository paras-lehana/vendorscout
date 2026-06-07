# ============================================================
# VendorScout Pro - Jobs API Endpoints (V1.2)
# ============================================================
# Job status tracking and SSE streaming endpoints:
# GET  /api/jobs/{job_id}        - Get job status
# GET  /api/jobs/{job_id}/stream - SSE stream of agent updates
# GET  /api/jobs                 - List recent jobs
#
# V1.2: Client disconnect detection to save browser resources
# ============================================================

import json
import logging
import asyncio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app import database as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["jobs"])


# ---- V2.2: Pipeline control endpoints ----

@router.post("/jobs/{job_id}/stop")
async def stop_job(job_id: str):
    """
    Stop a running research job.
    
    Sets a 'stop' signal that causes all pending agents to be skipped.
    Already-running agents will finish naturally, then the pipeline halts.
    No report is generated. Partial vendor data may still be available.
    """
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") not in ("processing", "running", "queued"):
        raise HTTPException(status_code=400, detail=f"Job is already {job['status']}")
    
    await db.add_job_signal(job_id, "stop")
    logger.info(f"Stop signal sent for job {job_id}")
    return {"status": "signal_sent", "signal": "stop", "job_id": job_id}


@router.post("/jobs/{job_id}/fast-forward")
async def fast_forward_job(job_id: str):
    """
    Fast-forward a running job to the report stage.
    
    Skips remaining assessment agents (compliance, financial, risk,
    authenticity, price, specification) but still runs analysis + report
    so the user gets a partial result based on whatever data is available.
    """
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") not in ("processing", "running", "queued"):
        raise HTTPException(status_code=400, detail=f"Job is already {job['status']}")
    
    await db.add_job_signal(job_id, "fast_forward")
    logger.info(f"Fast-forward signal sent for job {job_id}")
    return {"status": "signal_sent", "signal": "fast_forward", "job_id": job_id}


@router.post("/jobs/{job_id}/skip-agent/{agent_name}")
async def skip_agent(job_id: str, agent_name: str):
    """
    Skip a specific agent in the pipeline.
    
    If the agent hasn't started yet, it will be skipped entirely.
    If it's already running, the skip takes effect after the current
    operation finishes.
    
    Valid agent names: orchestrator, research, compliance, financial,
    risk, authenticity, price_comparison, specification, analysis, report
    """
    valid_agents = {
        "orchestrator", "research", "compliance", "financial",
        "risk", "authenticity", "price_comparison", "specification",
        "analysis", "report",
    }
    if agent_name not in valid_agents:
        raise HTTPException(status_code=400, detail=f"Invalid agent: {agent_name}")
    
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") not in ("processing", "running", "queued"):
        raise HTTPException(status_code=400, detail=f"Job is already {job['status']}")
    
    await db.add_job_signal(job_id, "skip_agent", agent_name)
    logger.info(f"Skip signal sent for agent '{agent_name}' in job {job_id}")
    return {"status": "signal_sent", "signal": "skip_agent", "target": agent_name, "job_id": job_id}


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """
    Get the current status of a research job.
    
    Returns job metadata, current status, and if completed,
    a summary of results.
    
    Statuses: queued → running → completed | failed
    """
    job = await db.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return job


@router.get("/jobs/{job_id}/stream")
async def stream_job_updates(job_id: str, request: Request):
    """
    Server-Sent Events (SSE) endpoint for real-time agent updates.
    
    The frontend connects to this endpoint and receives a stream
    of events as agents progress through the pipeline.
    
    Event format:
        data: {"agent": "research", "status": "running", "message": "...", "timestamp": "..."}
    
    Special events:
        event: complete - Sent when the job finishes
        event: error - Sent when the job fails
    
    Connection stays open until job completes or client disconnects.
    
    V1.2: Checks request.is_disconnected() to detect when the user
    navigates away, saving browser resources by stopping the stream.
    """
    job = await db.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return StreamingResponse(
        _generate_sse_events(job_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


async def _generate_sse_events(job_id: str, request: Request):
    """
    Generator that yields SSE-formatted events.
    
    Polls the database for new agent log entries and yields them
    as SSE events. Sends heartbeat pings every 5 seconds to keep
    the connection alive through proxies.
    
    V1.2: Checks request.is_disconnected() every poll cycle.
    When the client navigates away, the generator stops immediately,
    which saves browser resources by freeing resources faster.
    
    Stops when:
    - Job status is "completed" or "failed"
    - Client disconnects (detected via request.is_disconnected())
    - Timeout reached (10 minutes)
    """
    seen_log_ids = set()
    heartbeat_interval = 5  # seconds
    poll_interval = 1  # seconds
    max_wait = 600  # 10 min timeout
    elapsed = 0
    
    try:
        while elapsed < max_wait:
            # V1.2: Check if client disconnected to save API credits
            # When user navigates away mid-research, we detect it here
            # and stop streaming. The background workflow still completes,
            # but we release the SSE connection immediately.
            if await request.is_disconnected():
                logger.info(f"Client disconnected from SSE stream for job {job_id} (saving resources)")
                return
            
            # Fetch latest agent logs
            logs = await db.get_agent_logs(job_id)
            
            # Send any new log entries as events
            for log in logs:
                log_id = f"{log['agent_name']}_{log['created_at']}"
                if log_id not in seen_log_ids:
                    seen_log_ids.add(log_id)
                    
                    event_data = json.dumps({
                        "agent": log["agent_name"],
                        "status": log["status"],
                        "message": log["message"],
                        "findings_count": log.get("findings_count", 0),
                        "timestamp": log["created_at"]
                    })
                    
                    yield f"data: {event_data}\n\n"
            
            # Check if job is finished
            job = await db.get_job(job_id)
            if job and job.get("status") in ("completed", "failed", "stopped"):
                # Send final event
                status_label = {
                    "completed": "completed",
                    "failed": "failed",
                    "stopped": "stopped by user",
                }
                final_data = json.dumps({
                    "agent": "system",
                    "status": job["status"],
                    "message": f"Research {status_label.get(job['status'], job['status'])}",
                    "job_status": job["status"]
                })
                yield f"event: {job['status']}\ndata: {final_data}\n\n"
                return
            
            # Send heartbeat to keep connection alive
            elapsed += poll_interval
            if elapsed % heartbeat_interval == 0:
                yield f": heartbeat\n\n"
            
            await asyncio.sleep(poll_interval)
        
        # Timeout reached
        yield f"event: timeout\ndata: {{\"message\": \"Stream timeout after {max_wait}s\"}}\n\n"
        
    except asyncio.CancelledError:
        # Client disconnected - this is normal
        logger.debug(f"SSE stream cancelled for job {job_id}")
        return


@router.get("/jobs")
async def list_jobs(limit: int = 20):
    """
    List recent research jobs.
    Used by the frontend to show job history/recent searches.
    """
    # We'll implement a simple query - in production would add pagination
    # For now, get a list from the database
    # Note: This is a simplified implementation for hackathon
    import aiosqlite
    from app.config import settings
    
    async with aiosqlite.connect(settings.DATABASE_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM research_jobs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        rows = await cursor.fetchall()
        
    return [dict(row) for row in rows]
