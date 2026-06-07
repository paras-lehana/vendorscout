# ============================================================
# VendorScout Pro - Base Agent Class
# ============================================================
# Abstract base class for all specialized agents.
# Provides common functionality: LLM access, agentic browser access,
# SSE update emission, and error handling.
#
# Each agent implements execute() to perform its specific task
# and returns state updates as a dict.
# ============================================================

import logging
import time
from abc import ABC, abstractmethod
from typing import Callable, Optional

from app.tools.llm import LLMTool
from app.tools.browser_agent import BrowserAgentClient
from app.tools.search_tool import SearchTool
from app import database as db

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Abstract base class for VendorScout Pro agents.
    
    All agents share:
    - LLM tool (Azure OpenAI, with llm.lehana.in fallback) for reasoning
    - Agentic browser client (self-hosted Playwright) for web navigation + actions
    - Search tool (SerperDev) for Google search
    - SSE update mechanism for real-time frontend updates
    
    Subclasses must implement:
    - execute(state, on_update) -> dict of state updates
    """
    
    # Agent identity - override in subclasses
    name: str = "base"
    description: str = "Base agent"
    
    def __init__(self):
        self.llm = LLMTool()
        self.browser = BrowserAgentClient()
        self.search = SearchTool()
    
    @abstractmethod
    async def execute(self, state: dict, job_id: str) -> dict:
        """
        Execute the agent's task.
        
        Args:
            state: Current workflow state dict containing all data from previous agents
            job_id: Job ID for logging agent activity to database
            
        Returns:
            Dict of state updates to merge into the workflow state
        """
        pass
    
    async def log_activity(
        self,
        job_id: str,
        status: str,
        message: str,
        findings_count: int = 0,
        details: dict = None
    ):
        """
        Log agent activity to database.
        These logs are streamed to the frontend via SSE.
        
        Status values:
        - "running": Agent is actively working
        - "completed": Agent finished successfully
        - "failed": Agent encountered an error
        """
        await db.log_agent_activity(
            job_id=job_id,
            agent_name=self.name,
            status=status,
            message=message,
            findings_count=findings_count,
            details=details
        )
        logger.info(f"[{self.name}] {status}: {message}")
    
    async def safe_execute(self, state: dict, job_id: str) -> dict:
        """
        Wrapper around execute() with signal-aware skip logic.
        
        Before running the agent, checks for control signals:
        - stop: Halt everything — agent is skipped
        - fast_forward: Skip assessment agents, let analysis/report run
        - skip_agent: Skip this specific agent
        
        Returns {"_skipped": True} when an agent is skipped.
        """
        start_time = time.time()
        
        try:
            # V2.2: Check control signals before executing
            if await self._should_skip(job_id):
                return {"_skipped": True}
            
            await self.log_activity(job_id, "running", f"{self.description} starting...")
            
            result = await self.execute(state, job_id)
            
            duration = time.time() - start_time
            await self.log_activity(
                job_id, "completed",
                f"{self.description} completed in {duration:.1f}s",
                findings_count=result.get("_findings_count", 0)
            )
            
            return result
            
        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"{self.description} failed after {duration:.1f}s: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            await self.log_activity(
                job_id, "failed",
                error_msg,
                details={"error": str(e)}
            )
            
            # Return empty updates - workflow continues with partial data
            return {"errors": [error_msg]}
    
    async def _should_skip(self, job_id: str) -> bool:
        """
        Check if this agent should be skipped due to a user control signal.
        
        Signal precedence: stop > fast_forward > skip_agent
        Assessment agents (compliance, financial, risk, authenticity,
        price_comparison, specification) are skipped on fast_forward.
        Analysis and report always run on fast_forward so partial results
        are still produced.
        """
        from app import database as db_mod
        
        # Stop signal = skip everything
        if await db_mod.has_signal(job_id, "stop"):
            await self.log_activity(
                job_id, "skipped",
                f"{self.description} skipped — research stopped by user"
            )
            return True
        
        # Fast-forward = skip assessment agents only
        assessment_agents = {
            "compliance", "financial", "risk",
            "authenticity", "price_comparison", "specification",
        }
        if self.name in assessment_agents and await db_mod.has_signal(job_id, "fast_forward"):
            await self.log_activity(
                job_id, "skipped",
                f"{self.description} skipped — fast-forwarded to report"
            )
            return True
        
        # Skip this specific agent
        if await db_mod.has_signal(job_id, "skip_agent", self.name):
            await self.log_activity(
                job_id, "skipped",
                f"{self.description} skipped by user"
            )
            return True
        
        return False
