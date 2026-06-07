# ============================================================
# VendorScout Pro - LLM Tool (OpenAI-Compatible Endpoint)
# ============================================================
# Unified wrapper for any OpenAI-compatible chat completions API.
#
# Supports:
# - Direct endpoint: Any URL exposing /chat/completions
#   (OpenAI, AntiGravity, OpenRouter, Azure OpenAI, etc.)
# - Fallback via llm-service proxy (Lehana.in infra)
#
# Configuration via environment variables:
#   LLM_API_KEY    - API key for the provider
#   LLM_BASE_URL   - Base URL (e.g. https://antigravity.aidhunik.com/v1)
#   LLM_MODEL      - Model name (e.g. gemini-3-flash, gpt-4o)
#
# V2.0: Replaced OpenRouter-specific code with generic OpenAI-compatible
# client. Any provider that speaks /v1/chat/completions works.
# ============================================================

import json
import logging
from typing import Optional

import httpx

from app.config import settings
from app.tools.json_parser import parse_json_robust

logger = logging.getLogger(__name__)


class LLMTool:
    """
    Wrapper around any OpenAI-compatible chat completions API.
    
    Provides two main methods:
    - generate_structured(): Returns parsed JSON (for data extraction)
    - generate_text(): Returns free-form text (for summaries, reports)
    
    Includes retry logic and fallback to llm-service proxy.
    """
    
    def __init__(self):
        # --- PRIMARY: Azure OpenAI (Azure AI Foundry) — Microsoft AI stack ---
        self.use_azure = settings.use_azure
        if self.use_azure:
            self.api_key = settings.AZURE_OPENAI_API_KEY
            # Azure URL: {endpoint}/openai/deployments/{deployment}/chat/completions?api-version=...
            self.base_url = settings.AZURE_OPENAI_ENDPOINT.rstrip("/")
            self.model = settings.AZURE_OPENAI_DEPLOYMENT
            self.azure_api_version = settings.AZURE_OPENAI_API_VERSION
            # Azure authenticates via the `api-key` header, not Bearer.
            self.headers = {"api-key": self.api_key, "Content-Type": "application/json"}
            self.service_url = settings.LLM_SERVICE_URL
            self.service_endpoint = settings.LLM_SERVICE_ENDPOINT
            logger.info("LLM: using Azure OpenAI deployment=%s (api-version=%s)",
                        self.model, self.azure_api_version)
            return

        # --- ALT PRIMARY: generic OpenAI-compatible endpoint ---
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL.rstrip("/")
        self.model = settings.LLM_MODEL
        self.azure_api_version = None

        # Legacy fallback: use OPENROUTER or GEMINI keys if LLM_API_KEY not set
        if not self.api_key:
            if settings.OPENROUTER_API_KEY:
                self.api_key = settings.OPENROUTER_API_KEY
                self.base_url = "https://openrouter.ai/api/v1"
                self.model = settings.LLM_PRIMARY_MODEL or "google/gemini-2.5-flash"
                logger.info("LLM: Using legacy OPENROUTER_API_KEY")
            elif settings.GEMINI_API_KEY:
                self.api_key = settings.GEMINI_API_KEY
                self.base_url = "https://openrouter.ai/api/v1"
                self.model = settings.LLM_PRIMARY_MODEL or "google/gemini-2.5-flash"
                logger.info("LLM: Using legacy GEMINI_API_KEY")
        
        if not self.api_key:
            logger.warning("No LLM API key configured (LLM_API_KEY)")
        else:
            logger.info(f"LLM: base_url={self.base_url} model={self.model}")
        
        # llm-service proxy fallback
        self.service_url = settings.LLM_SERVICE_URL
        self.service_endpoint = settings.LLM_SERVICE_ENDPOINT
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://vendorscout.lehana.in",
            "X-Title": "VendorScout Pro",
        }
    
    async def _call_llm(
        self,
        messages: list[dict],
        model: str = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> Optional[str]:
        """
        Make a request to an OpenAI-compatible /chat/completions endpoint.
        Falls back to llm-service proxy if the primary endpoint fails.
        Returns the raw text content from the response.
        """
        model = model or self.model
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        # --- Primary: Direct endpoint call (Azure or OpenAI-compatible) ---
        try:
            if getattr(self, "use_azure", False):
                url = (f"{self.base_url}/openai/deployments/{self.model}"
                       f"/chat/completions?api-version={self.azure_api_version}")
            else:
                url = f"{self.base_url}/chat/completions"
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    url,
                    headers=self.headers,
                    json=payload
                )
                
                if response.status_code == 200:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    return content.strip()
                
                logger.error(f"LLM API error {response.status_code}: {response.text[:500]}")
                
        except Exception as e:
            logger.error(f"LLM primary call failed: {e}")
        
        # --- Fallback: llm-service proxy ---
        if self.service_url:
            try:
                return await self._call_llm_service(messages, temperature, max_tokens, json_mode)
            except Exception as e:
                logger.error(f"LLM service fallback also failed: {e}")
        
        return None
    
    async def _call_llm_service(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> Optional[str]:
        """
        Call via the Lehana llm-service SMK proxy as fallback.
        POST {llm_service_url}/smk/{endpoint}
        """
        url = f"{self.service_url}/smk/{self.service_endpoint}"
        
        payload = {
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "json_mode": json_mode,
        }
        
        logger.info(f"LLM fallback via llm-service: {url}")
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload
            )
            
            if response.status_code != 200:
                logger.error(f"LLM service error {response.status_code}: {response.text[:500]}")
                return None
            
            data = response.json()
            if "choices" in data and data["choices"]:
                return data["choices"][0]["message"]["content"].strip()
            return None
    
    async def generate_structured(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        max_retries: int = 2,
        image_b64: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Generate structured JSON output from a prompt.
        
        Sends the prompt to the LLM and parses the response as JSON.
        Retries on parse failures (LLMs sometimes output markdown-wrapped JSON).
        
        Args:
            prompt: The user prompt with instructions
            system_prompt: System-level context for the model
            max_retries: Number of retry attempts on JSON parse failure
        
        Returns:
            Parsed JSON dict, or None if all attempts fail
        """
        # Multimodal: attach a screenshot (Azure OpenAI gpt-4o vision) when provided.
        if image_b64:
            user_content = [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ]
        else:
            user_content = prompt
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        for attempt in range(max_retries + 1):
            try:
                text = await self._call_llm(messages)
                
                if not text:
                    continue
                
                # Use robust JSON parser (handles markdown fences,
                # trailing commas, single quotes, regex extraction)
                parsed = parse_json_robust(text)
                if parsed is not None:
                    return parsed
                
                logger.warning(
                    f"Robust JSON parse returned None (attempt {attempt + 1}/{max_retries + 1})"
                )
                if attempt == max_retries:
                    logger.error(f"All JSON parse attempts failed. Raw: {text[:500] if text else 'None'}")
                    return None
                    
            except Exception as e:
                logger.error(f"LLM generate_structured failed: {e}")
                if attempt == max_retries:
                    return None
    
    async def generate_text(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant."
    ) -> Optional[str]:
        """
        Generate free-form text output.
        Used for executive summaries, vendor descriptions, etc.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        return await self._call_llm(messages)
    
    async def analyze_vendor_data(
        self,
        vendor_data: str,
        analysis_type: str = "general",
        context: str = ""
    ) -> Optional[dict]:
        """
        Convenience method for vendor-specific analysis.
        
        Args:
            vendor_data: Raw or structured vendor data as string
            analysis_type: Type of analysis (compliance, financial, risk, etc.)
            context: Additional context about what to analyze
        """
        role_prompts = {
            "compliance": "You are a regulatory compliance expert specializing in vendor certification verification.",
            "financial": "You are a financial analyst specializing in vendor financial health assessment.",
            "risk": "You are a risk analyst specializing in supply chain and vendor risk assessment.",
            "authenticity": "You are a product authenticity expert specializing in certification and quality verification.",
            "price": "You are a pricing analyst specializing in e-commerce price comparison and market trends.",
            "specification": "You are a product specifications expert who enriches and validates technical product data.",
            "general": "You are a procurement analyst helping evaluate vendor suitability.",
        }
        
        system_prompt = role_prompts.get(analysis_type, role_prompts["general"])
        
        prompt = f"""Analyze the following vendor data for {analysis_type} assessment.

{context}

Vendor Data:
{vendor_data}

Return your analysis as structured JSON."""
        
        return await self.generate_structured(prompt, system_prompt)
