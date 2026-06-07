# ============================================================
# VendorScout Pro - Application Configuration
# ============================================================
# Loads settings from environment variables with sensible defaults.
# All API keys are REQUIRED - app will fail to start without them.
# Optional settings have defaults that work for development.
# ============================================================

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file - try multiple locations to support both local dev and Docker
# Local: /root/ideas/product-scrapper/.env (3 levels up from config.py)
# Docker: /app/.env (mounted via docker-compose volume)
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_env_candidates = [
    _PROJECT_ROOT / ".env",           # Local dev: project root
    Path("/app_config/.env"),          # Docker: mounted env file
    _PROJECT_ROOT.parent / ".env",    # Fallback: one level up
    Path(__file__).parent.parent / ".env",  # Fallback: backend dir
]
for _env_path in _env_candidates:
    if _env_path.exists():
        load_dotenv(_env_path)
        break


class Settings:
    """
    Central configuration for VendorScout Pro.
    All settings loaded from environment variables.
    
    Required (at least one LLM provider + a search key):
        AZURE_OPENAI_* (preferred)  OR  LLM_API_KEY  OR  LLM_SERVICE_URL fallback
        SERPER_API_KEY: SerperDev search API key

    Optional:
        BROWSER_*: self-hosted Playwright agent knobs
        DATABASE_PATH: SQLite file path
    """

    # --- Azure OpenAI (PRIMARY — Microsoft AI stack) ---
    # When AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY + AZURE_OPENAI_DEPLOYMENT
    # are set, the LLM tool routes all reasoning/planning through Azure OpenAI
    # (Azure AI Foundry). This is the authentically Microsoft-native path.
    AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")       # https://<res>.openai.azure.com
    AZURE_OPENAI_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    AZURE_OPENAI_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")    # deployment name, e.g. gpt-4o
    AZURE_OPENAI_API_VERSION: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

    # --- Generic OpenAI-compatible endpoint (alt primary / dev) ---
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")

    # --- Fallback: llm.lehana.in SMK proxy (disclosed resilience) ---
    LLM_SERVICE_URL: str = os.getenv("LLM_SERVICE_URL", "")
    LLM_SERVICE_ENDPOINT: str = os.getenv("LLM_SERVICE_ENDPOINT", "vendorscout")

    # Legacy keys (backward compat)
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    LLM_PRIMARY_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")
    LLM_FALLBACK_MODEL: str = os.getenv("LLM_FALLBACK_MODEL", "")

    # --- Search ---
    SERPER_API_KEY: str = os.getenv("SERPER_API_KEY", "")

    # --- Self-hosted Agentic Browser (Playwright) ---
    BROWSER_HEADLESS: bool = os.getenv("BROWSER_HEADLESS", "true").lower() != "false"
    BROWSER_MAX_CONCURRENCY: int = int(os.getenv("BROWSER_MAX_CONCURRENCY", "3"))
    BROWSER_MAX_STEPS: int = int(os.getenv("BROWSER_MAX_STEPS", "12"))
    # Confirm-before-send guard for real transactions (RFQ/enquiry submit).
    BROWSER_ALLOW_AUTOSUBMIT: bool = os.getenv("BROWSER_ALLOW_AUTOSUBMIT", "false").lower() == "true"
    
    # --- Database ---
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", str(_PROJECT_ROOT / "data" / "vendorscout.db"))
    
    # --- Server ---
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # --- Application Limits ---
    MAX_VENDORS_PER_JOB: int = int(os.getenv("MAX_VENDORS_PER_JOB", "30"))
    SSE_KEEPALIVE_SECONDS: int = int(os.getenv("SSE_KEEPALIVE_SECONDS", "15"))
    
    # --- Paths ---
    PROJECT_ROOT: Path = _PROJECT_ROOT
    TEMPLATES_DIR: Path = Path(os.getenv("TEMPLATES_DIR", str(_PROJECT_ROOT / "frontend" / "templates")))
    STATIC_DIR: Path = Path(os.getenv("STATIC_DIR", str(_PROJECT_ROOT / "frontend" / "static")))
    
    def validate(self) -> list[str]:
        """
        Validate that all required settings are present.
        Returns list of missing/invalid settings.
        LLM_API_KEY is the primary check; falls back to legacy keys.
        """
        errors = []

        has_azure = bool(self.AZURE_OPENAI_ENDPOINT and self.AZURE_OPENAI_API_KEY
                         and self.AZURE_OPENAI_DEPLOYMENT)
        has_generic = bool(self.LLM_API_KEY or self.OPENROUTER_API_KEY or self.GEMINI_API_KEY)
        has_fallback = bool(self.LLM_SERVICE_URL)
        if not (has_azure or has_generic or has_fallback):
            errors.append(
                "No LLM provider configured - set AZURE_OPENAI_* (preferred), or LLM_API_KEY, "
                "or LLM_SERVICE_URL (llm.lehana.in fallback)."
            )
        if not self.SERPER_API_KEY:
            errors.append("SERPER_API_KEY is recommended for web discovery - get from https://serper.dev")

        return errors

    @property
    def use_azure(self) -> bool:
        return bool(self.AZURE_OPENAI_ENDPOINT and self.AZURE_OPENAI_API_KEY
                    and self.AZURE_OPENAI_DEPLOYMENT)


# Singleton settings instance used throughout the app
settings = Settings()
