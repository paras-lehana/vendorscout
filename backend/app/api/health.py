# ============================================================
# VendorScout Pro - Health Endpoint
# ============================================================
# Standard health check endpoint following Lehana.in conventions.
# GET /health - Returns service status, version, dependencies.
# ============================================================

import logging
from datetime import datetime, timezone
from fastapi import APIRouter

from app.config import settings
from version import APP_VERSION, APP_NAME

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """
    Standard health check endpoint.
    
    Returns:
    - Service name and version
    - Current status
    - Dependency statuses (database, API keys configured)
    - Uptime information
    """
    # Check database connectivity
    db_status = "ok"
    try:
        import aiosqlite
        async with aiosqlite.connect(settings.DATABASE_PATH) as conn:
            await conn.execute("SELECT 1")
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    # Browser-agent (Playwright) readiness
    browser_status = "missing"
    try:
        from app.tools.browser_agent import _PLAYWRIGHT_AVAILABLE
        browser_status = "ready" if _PLAYWRIGHT_AVAILABLE else "playwright-not-installed"
    except Exception as e:  # noqa: BLE001
        browser_status = f"error: {e}"

    # Which LLM provider is active
    if settings.use_azure:
        llm_provider = "azure-openai"
    elif settings.LLM_API_KEY or settings.OPENROUTER_API_KEY or settings.GEMINI_API_KEY:
        llm_provider = "openai-compatible"
    elif settings.LLM_SERVICE_URL:
        llm_provider = "llm.lehana.in-fallback"
    else:
        llm_provider = "missing"

    api_keys_status = {
        "llm_provider": llm_provider,
        "azure_openai": "configured" if settings.use_azure else "not-set",
        "browser_agent": browser_status,
        "serper": "configured" if settings.SERPER_API_KEY else "missing",
    }

    llm_ok = llm_provider != "missing"
    overall_status = "healthy" if (db_status == "ok" and llm_ok) else "degraded"
    
    return {
        "status": overall_status,
        "service": APP_NAME,
        "version": APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dependencies": {
            "database": db_status,
            "api_keys": api_keys_status
        }
    }
