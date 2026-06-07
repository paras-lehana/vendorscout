# ============================================================
# VendorScout Pro - LangGraph Workflow Definition (V2.1)
# ============================================================
# Defines the multi-agent workflow using LangGraph's StateGraph.
#
# Pipeline (sequential with two parallel stages):
#
#   START → Orchestrator → Research →
#     [Compliance ∥ Financial ∥ Risk] →
#     [Authenticity ∥ Price Comparison ∥ Specification] →
#     Analysis → Report → END
#
# Phase 1 parallel: compliance, financial, risk (core assessments)
# Phase 2 parallel: authenticity, price, specification (extended intel)
# Both parallel groups run their agents concurrently for lower latency.
#
# State is a dict that accumulates data as it flows through agents.
# Each agent reads what it needs and adds its outputs.
#
# V1.3: detail_level (low/medium/high) flows through state.
# V2.0: Added extended assessment phase with authenticity,
#        price comparison, and specification corpus agents.
# V2.1: Added fast-forward/skip mechanism so users can proceed
#        with available data without waiting for slow assessment agents.
# ============================================================

import asyncio
import json
import logging
import time
from typing import TypedDict, Any

from langgraph.graph import StateGraph, END

from app.agents.orchestrator import OrchestratorAgent
from app.agents.research import ResearchAgent
from app.agents.compliance import ComplianceAgent
from app.agents.financial import FinancialAgent
from app.agents.risk import RiskAgent
from app.agents.authenticity import AuthenticityAgent
from app.agents.price_comparison import PriceComparisonAgent
from app.agents.specification import SpecificationAgent
from app.agents.analysis import AnalysisAgent
from app.agents.report import ReportAgent
from app import database as db

logger = logging.getLogger(__name__)


class WorkflowState(TypedDict, total=False):
    """
    State schema for the LangGraph workflow.
    
    Each agent reads the fields it needs and writes new fields.
    Using TypedDict for clear documentation of data flow,
    though LangGraph uses this mainly as a reference.
    """
    # Input
    query: str
    job_id: str
    detail_level: str  # V1.3: "low", "medium", or "high"
    
    # From Orchestrator
    parsed_requirements: dict
    search_keywords: list
    enhanced_query: str
    
    # From Research
    vendors: list
    search_results_count: int
    
    # From Compliance
    compliance_data: dict
    
    # From Financial
    financial_data: dict
    
    # From Risk
    risk_data: dict
    high_risk_vendor_count: int
    
    # From Authenticity (V2.0)
    authenticity_data: dict
    
    # From Price Comparison (V2.0)
    price_data: dict
    
    # From Specification (V2.0)
    specification_data: dict
    
    # From Analysis
    rankings: list
    comparison_matrix: dict
    analyses: dict
    
    # From Report
    report: dict
    
    # Error tracking
    errors: list


# ---- Instantiate all agents once (they're reusable) ----
orchestrator = OrchestratorAgent()
research = ResearchAgent()
compliance = ComplianceAgent()
financial = FinancialAgent()
risk = RiskAgent()
authenticity = AuthenticityAgent()
price_comparison = PriceComparisonAgent()
specification = SpecificationAgent()
analysis = AnalysisAgent()
report = ReportAgent()


# ---- Node functions for LangGraph ----
# Each node is an async function that takes state and returns state updates.
# The safe_execute wrapper ensures failures don't crash the pipeline.
#
# CRITICAL: With StateGraph(dict) in LangGraph 0.2.0, the dict returned
# by a node REPLACES the entire state (not merge). Every node must
# propagate ALL upstream state keys it wants to preserve. We use
# _merge_state() to copy existing state first, then overlay new results.


def _merge_state(state: dict, result: dict) -> dict:
    """
    Merge agent result into existing state, preserving all upstream keys.
    
    With LangGraph StateGraph(dict), node return values REPLACE the state.
    This helper ensures we don't lose data from previous pipeline stages
    (e.g., 'vendors' from research, 'parsed_requirements' from orchestrator).
    """
    merged = state.copy()
    merged.update(result)
    return merged


async def _check_stop(state: dict) -> bool:
    """Check if the pipeline has a stop signal — all nodes become no-ops."""
    return await db.has_signal(state["job_id"], "stop")


async def orchestrator_node(state: dict) -> dict:
    """Parse natural language query into structured requirements."""
    result = await orchestrator.safe_execute(state, state["job_id"])
    if result.get("_skipped"):
        return state
    return _merge_state(state, result)


async def research_node(state: dict) -> dict:
    """Discover and profile vendors from the web."""
    result = await research.safe_execute(state, state["job_id"])
    if result.get("_skipped"):
        return state
    return _merge_state(state, result)


async def parallel_assessment_node(state: dict) -> dict:
    """
    Run compliance, financial, and risk assessments IN PARALLEL.
    
    Each agent checks for skip/stop signals individually via safe_execute.
    If an agent is skipped, its result is excluded from the merge.
    """
    job_id = state["job_id"]
    
    # Log the parallel start
    await db.log_agent_activity(
        job_id=job_id,
        agent_name="system",
        status="running",
        message="Starting parallel assessment: Compliance + Financial + Risk"
    )
    
    # Run all three in parallel — each agent's safe_execute checks signals
    compliance_result, financial_result, risk_result = await asyncio.gather(
        compliance.safe_execute(state, job_id),
        financial.safe_execute(state, job_id),
        risk.safe_execute(state, job_id),
        return_exceptions=False
    )
    
    # Merge results, excluding skipped agents
    merged = {}
    for result in [compliance_result, financial_result, risk_result]:
        if result and not result.get("_skipped"):
            merged.update({k: v for k, v in result.items() if not k.startswith("_")})
    
    # Collect any errors from the parallel agents
    errors = []
    for result in [compliance_result, financial_result, risk_result]:
        if result and "errors" in result and not result.get("_skipped"):
            errors.extend(result["errors"])
    
    if errors:
        merged["errors"] = state.get("errors", []) + errors
    
    return _merge_state(state, merged)


async def extended_assessment_node(state: dict) -> dict:
    """
    Run authenticity, price comparison, and specification enrichment IN PARALLEL.
    
    Each agent checks for skip/stop signals individually via safe_execute.
    If an agent is skipped, its result is excluded from the merge.
    """
    job_id = state["job_id"]
    
    await db.log_agent_activity(
        job_id=job_id,
        agent_name="system",
        status="running",
        message="Starting extended assessment: Authenticity + Price Comparison + Specification"
    )
    
    # Run all three in parallel — each agent's safe_execute checks signals
    auth_result, price_result, spec_result = await asyncio.gather(
        authenticity.safe_execute(state, job_id),
        price_comparison.safe_execute(state, job_id),
        specification.safe_execute(state, job_id),
        return_exceptions=False
    )
    
    merged = {}
    for result in [auth_result, price_result, spec_result]:
        if result and not result.get("_skipped"):
            merged.update({k: v for k, v in result.items() if not k.startswith("_")})
    
    errors = []
    for result in [auth_result, price_result, spec_result]:
        if result and "errors" in result and not result.get("_skipped"):
            errors.extend(result["errors"])
    
    if errors:
        merged["errors"] = state.get("errors", []) + errors
    
    return _merge_state(state, merged)


async def analysis_node(state: dict) -> dict:
    """Score, rank, and analyze all vendors."""
    result = await analysis.safe_execute(state, state["job_id"])
    if result.get("_skipped"):
        return state
    return _merge_state(state, result)


async def report_node(state: dict) -> dict:
    """Generate the final research report."""
    result = await report.safe_execute(state, state["job_id"])
    if result.get("_skipped"):
        return state
    return _merge_state(state, result)


def build_workflow() -> StateGraph:
    """
    Build and compile the LangGraph workflow.
    
    The graph is:
        orchestrator → research → parallel_assessment → extended_assessment → analysis → report → END
    
    Returns a compiled StateGraph ready for invocation.
    """
    workflow = StateGraph(dict)
    
    # Add all nodes
    workflow.add_node("orchestrator", orchestrator_node)
    workflow.add_node("research", research_node)
    workflow.add_node("parallel_assessment", parallel_assessment_node)
    workflow.add_node("extended_assessment", extended_assessment_node)
    workflow.add_node("analysis", analysis_node)
    workflow.add_node("report", report_node)
    
    # Define the linear pipeline (with parallel hidden inside assessment nodes)
    workflow.set_entry_point("orchestrator")
    workflow.add_edge("orchestrator", "research")
    workflow.add_edge("research", "parallel_assessment")
    workflow.add_edge("parallel_assessment", "extended_assessment")
    workflow.add_edge("extended_assessment", "analysis")
    workflow.add_edge("analysis", "report")
    workflow.add_edge("report", END)
    
    return workflow.compile()


# Pre-compile the workflow for reuse across requests.
# LangGraph compiled graphs are thread-safe and reusable.
compiled_workflow = build_workflow()


async def run_research(query: str, job_id: str, detail_level: str = "medium") -> dict:
    """
    Execute the full vendor research pipeline.
    
    This is the main entry point for the workflow system.
    Called by the API endpoint when a new search is submitted.
    
    Args:
        query: Natural language procurement query
        job_id: Unique job identifier for tracking
        detail_level: Research depth — "low" (quick), "medium" (default), "high" (deep)
    
    Returns:
        Final workflow state including complete report
    """
    start_time = time.time()
    
    logger.info(f"Starting research workflow for job {job_id}: '{query}'")
    
    # Update job status to running
    await db.update_job_status(job_id, "running")
    
    try:
        # Initialize state with query and job_id
        initial_state = {
            "query": query,
            "job_id": job_id,
            "detail_level": detail_level,  # V1.3: flows to all agents
            "errors": []
        }
        
        # Run the full workflow
        # ainvoke runs the graph asynchronously through all nodes
        final_state = await compiled_workflow.ainvoke(initial_state)
        
        duration = time.time() - start_time
        
        # V2.2: Handle stop signal — pipeline ran but nodes were no-ops
        if await db.has_signal(job_id, "stop"):
            await db.update_job_status(job_id, "stopped")
            await db.log_agent_activity(
                job_id=job_id,
                agent_name="system",
                status="stopped",
                message=f"Research stopped by user after {duration:.1f}s"
            )
            await db.mark_signals_processed(job_id)
            return final_state
        
        # V2.2: Clean up processed signals (fast_forward, skip_agent)
        await db.mark_signals_processed(job_id)
        
        logger.info(f"Workflow completed for job {job_id} in {duration:.1f}s")
        
        # Log completion
        await db.log_agent_activity(
            job_id=job_id,
            agent_name="system",
            status="completed",
            message=f"Full research pipeline completed in {duration:.1f}s",
            findings_count=len(final_state.get("rankings", []))
        )
        
        return final_state
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Workflow failed after {duration:.1f}s: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        await db.update_job_status(job_id, "failed", errors=json.dumps([str(e)]))
        await db.log_agent_activity(
            job_id=job_id,
            agent_name="system",
            status="failed",
            message=error_msg
        )
        
        raise
