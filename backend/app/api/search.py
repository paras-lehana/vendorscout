# ============================================================
# VendorScout Pro - Search API Endpoint (V1.3)
# ============================================================
# Handles new vendor research requests:
# POST /api/search - Submit a new procurement query
#
# Kicks off the async workflow and returns a job_id for tracking.
# The frontend uses SSE to get real-time progress updates.
#
# V1.3: Passes detail_level (low/medium/high) to the pipeline,
# controlling vendor count, keyword depth, and timeouts.
# ============================================================

import json
import logging
import uuid
import asyncio
from fastapi import APIRouter, HTTPException

from app.models.schemas import SearchRequest, SearchResponse
from app import database as db
from app.workflows.pipeline import run_research

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def create_search(request: SearchRequest):
    """
    Submit a new vendor research query.
    
    Accepts a natural language procurement query, creates a job,
    and starts the multi-agent workflow asynchronously.
    
    The returned job_id can be used to:
    - Check status: GET /api/jobs/{job_id}
    - Stream updates: GET /api/jobs/{job_id}/stream
    - Get report: GET /api/reports/{job_id}
    
    Request body:
        {"query": "I need industrial ball bearings, ISO 9001, budget under $50k"}
    
    Response:
        {"job_id": "uuid", "status": "queued", "message": "Research started"}
    """
    query = request.query.strip()
    detail_level = request.detail_level  # V1.3: low/medium/high
    
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    
    if len(query) > 1000:
        raise HTTPException(status_code=400, detail="Query too long (max 1000 characters)")
    
    # Generate unique job ID
    job_id = str(uuid.uuid4())
    
    # Create job record in database
    await db.create_job(job_id=job_id, query=query)
    
    logger.info(f"New search job created: {job_id} query='{query[:100]}' detail_level={detail_level}")
    
    # Start the workflow in the background.
    # asyncio.create_task runs it concurrently without blocking the response.
    # The job status is tracked in the database.
    asyncio.create_task(_run_workflow_safe(job_id, query, detail_level))
    
    return SearchResponse(
        job_id=job_id,
        status="queued",
        message="Research pipeline started. Use the job_id to track progress."
    )


async def _run_workflow_safe(job_id: str, query: str, detail_level: str = "medium"):
    """
    Wrapper to run the workflow with error handling.
    This runs as a background task - exceptions are caught
    and stored in the job record rather than raised.
    
    V1.3: detail_level controls research depth:
    - low:    5 vendors, fewer keywords, 60s timeout
    - medium: 8 vendors (default), standard depth, 120s timeout
    - high:   12 vendors, more keywords, 180s timeout
    """
    try:
        await run_research(query=query, job_id=job_id, detail_level=detail_level)
    except Exception as e:
        logger.error(f"Background workflow failed for {job_id}: {e}", exc_info=True)
        # The workflow already updates job status on failure,
        # but this is a safety net
        try:
            await db.update_job_status(
                job_id, "failed",
                errors=json.dumps([str(e)])
            )
        except Exception:
            logger.error(f"Failed to update job status for {job_id}")
