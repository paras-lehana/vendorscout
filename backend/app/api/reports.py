# ============================================================
# VendorScout Pro - Reports API Endpoint
# ============================================================
# GET /api/reports/{job_id} - Get the full research report
# ============================================================

import json
import logging
from fastapi import APIRouter, HTTPException

from app import database as db
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/reports/{job_id}")
async def get_report(job_id: str):
    """
    Get the complete research report for a finished job.
    
    Constructs the report from database columns:
    - executive_summary, comparison_matrix, recommendations from jobs table
    - Vendor data from vendors table
    - Agent activity from agent_logs table
    
    Only available when job status is "completed".
    """
    job = await db.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.get("status") != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Report not ready. Job status: {job.get('status')}"
        )
    
    # Get vendors for this job
    vendors = await db.get_vendors_for_job(job_id)
    
    # Parse JSON fields from the job record
    comparison_matrix = job.get("comparison_matrix", "{}")
    if isinstance(comparison_matrix, str):
        try:
            comparison_matrix = json.loads(comparison_matrix)
        except json.JSONDecodeError:
            comparison_matrix = {}
    
    recommendations = job.get("recommendations", "[]")
    if isinstance(recommendations, str):
        try:
            recommendations = json.loads(recommendations)
        except json.JSONDecodeError:
            recommendations = []
    
    # Construct the full report response
    report = {
        "job_id": job_id,
        "query": job.get("query", ""),
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
        "duration_seconds": job.get("duration_seconds", 0),
        "executive_summary": job.get("executive_summary", ""),
        "total_vendors_found": job.get("total_vendors_found", 0),
        "total_vendors_verified": job.get("total_vendors_verified", 0),
        "recommendations": recommendations,
        "comparison_matrix": comparison_matrix,
        "vendors": vendors,
        "methodology": {
            "scoring_weights": {
                "relevance": 0.25,
                "compliance": 0.20,
                "financial": 0.20,
                "risk": 0.15,
                "reputation": 0.10,
                "capability": 0.10
            },
            "data_sources": [
                "Google Search (via SerperDev)" if settings.SERPER_API_KEY else "Live marketplace discovery (Playwright browser agent)",
                "Self-hosted Playwright browser agent (live navigation + actions)",
                (f"Azure OpenAI · {settings.AZURE_OPENAI_DEPLOYMENT} (Azure AI Foundry)"
                 if settings.use_azure else f"{settings.LLM_MODEL} (OpenAI-compatible)"),
            ],
            "agents_used": [
                "Orchestrator", "Research", "Compliance",
                "Financial", "Risk", "Analysis", "Report"
            ]
        }
    }
    
    return report


@router.get("/reports/{job_id}/vendors")
async def get_report_vendors(job_id: str):
    """
    Get just the vendor list for a job.
    Lighter endpoint when you only need vendor data, not the full report.
    """
    # Confirm the job exists first (get_vendors_for_job always returns a list,
    # so an unknown id would otherwise yield a misleading 200 + empty list).
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    vendors = await db.get_vendors_for_job(job_id)
    return {"job_id": job_id, "vendors": vendors}
