# ============================================================
# VendorScout Pro - Orchestrator Agent
# ============================================================
# Parses natural language procurement queries into structured
# requirements using the LLM.
#
# Input: "I need industrial ball bearings, ISO 9001, budget $50k"
# Output: ParsedRequirements with product, industry, budget,
#         certifications, geographic preferences, etc.
#
# This agent runs FIRST in the workflow to extract structured
# data that all other agents depend on.
# ============================================================

import json
import logging
from typing import Optional

from app.agents.base import BaseAgent
from app.models.schemas import ParsedRequirements

logger = logging.getLogger(__name__)

# Prompt template for parsing procurement queries.
# Instructs the LLM to extract all relevant fields from natural language.
PARSE_PROMPT = """You are an expert procurement analyst. Parse the following procurement query into structured requirements.

Extract ALL relevant information. If something is not mentioned, use null.

Query: "{query}"

Return ONLY valid JSON matching this exact structure:
{{
    "product_or_service": "specific product or service name",
    "industry": "industry sector (e.g., Manufacturing, IT, Healthcare)",
    "budget_range": "budget range if mentioned (e.g., '$10k-50k')",
    "certifications_required": ["ISO 9001", "SOC 2", etc.],
    "geographic_preference": "preferred vendor location/region",
    "quantity": "quantity needed if mentioned",
    "timeline": "delivery timeline if mentioned",
    "quality_requirements": ["specific quality requirements"],
    "additional_constraints": ["any other constraints or preferences"],
    "search_keywords": ["5-8 effective Google search keywords to find vendors"]
}}

IMPORTANT:
- "search_keywords" MUST be 5-8 terms designed to find actual vendor/supplier COMPANY WEBSITES
- DO NOT use the raw query as a keyword — generate targeted search phrases
- Include terms like: "[product] suppliers", "[product] manufacturers [region]", "buy [product] wholesale"
- Add industry-specific vendor directory names if relevant (e.g., "IndiaMART", "ThomasNet")
- Focus on finding company websites, NOT news articles or research papers
- If query is vague, infer reasonable defaults based on context"""

# Alternate prompt for query enhancement when the user query is too short.
ENHANCE_PROMPT = """The user submitted a very brief procurement query: "{query}"

Suggest a more detailed version of this query that includes:
1. Specific product/service details
2. Likely industry context
3. Common requirements for this type of procurement

Return a single enhanced query string (1-2 sentences). Keep it realistic."""


class OrchestratorAgent(BaseAgent):
    """
    First agent in the workflow pipeline.
    
    Responsibilities:
    - Parse natural language query into structured ParsedRequirements
    - Generate effective search keywords for vendor discovery
    - Enhance vague queries with reasonable defaults
    - Set the foundation for all downstream agents
    """
    
    name = "orchestrator"
    description = "Query Parser & Orchestrator"
    
    async def execute(self, state: dict, job_id: str) -> dict:
        """
        Parse the user's natural language query into structured requirements.
        
        State input: {"query": "raw user query string"}
        State output: {"parsed_requirements": ParsedRequirements, "search_keywords": [...]}
        """
        query = state.get("query", "")
        
        if not query:
            raise ValueError("No query provided to orchestrator")
        
        await self.log_activity(
            job_id, "running",
            f"Parsing procurement query: '{query[:100]}...'" if len(query) > 100 else f"Parsing procurement query: '{query}'"
        )
        
        # Step 1: If query is very short (< 20 chars), enhance it first
        enhanced_query = query
        if len(query.strip()) < 20:
            await self.log_activity(job_id, "running", "Query is brief, enhancing with AI...")
            enhanced = await self.llm.generate_text(
                ENHANCE_PROMPT.format(query=query),
                system_prompt="You are a procurement expert. Return only the enhanced query text."
            )
            if enhanced and len(enhanced) > len(query):
                enhanced_query = enhanced.strip().strip('"')
                await self.log_activity(
                    job_id, "running",
                    f"Enhanced query: '{enhanced_query[:100]}'"
                )
        
        # Step 2: Parse the query into structured requirements using the LLM
        await self.log_activity(job_id, "running", "Extracting structured requirements with AI...")
        
        parsed_data = await self.llm.generate_structured(
            PARSE_PROMPT.format(query=enhanced_query),
            system_prompt="You are a procurement analysis AI. Return only valid JSON."
        )
        
        if not parsed_data:
            # Fallback: create minimal requirements from the query itself
            logger.warning("LLM failed to parse query, using fallback extraction")
            parsed_data = self._fallback_parse(query)
        
        # Step 3: Build ParsedRequirements model from LLM output
        # IMPORTANT: Use `or []` instead of just `.get(key, [])` because
        # the LLM may return explicit null values (e.g. "quality_requirements": null).
        # dict.get("key", []) returns None when key exists but value is null,
        # so we need `or []` to coerce None → empty list for Pydantic validation.
        try:
            requirements = ParsedRequirements(
                product_or_service=parsed_data.get("product_or_service") or query,
                industry=parsed_data.get("industry") or "General",
                budget_range=parsed_data.get("budget_range"),
                certifications_required=parsed_data.get("certifications_required") or [],
                geographic_preference=parsed_data.get("geographic_preference"),
                quantity=parsed_data.get("quantity"),
                timeline=parsed_data.get("timeline"),
                quality_requirements=parsed_data.get("quality_requirements") or [],
                additional_constraints=parsed_data.get("additional_constraints") or [],
                search_keywords=parsed_data.get("search_keywords") or [query],
            )
        except Exception as e:
            logger.error(f"Failed to build ParsedRequirements: {e}")
            # Last resort: minimal valid requirements
            requirements = ParsedRequirements(
                product_or_service=query,
                industry="General",
                search_keywords=[query]
            )
        
        await self.log_activity(
            job_id, "running",
            f"Identified: {requirements.product_or_service} in {requirements.industry} industry, "
            f"{len(requirements.search_keywords)} search keywords generated",
            findings_count=len(requirements.search_keywords)
        )
        
        return {
            "parsed_requirements": requirements.model_dump(),
            "search_keywords": requirements.search_keywords,
            "enhanced_query": enhanced_query,
            "_findings_count": len(requirements.search_keywords)
        }
    
    def _fallback_parse(self, query: str) -> dict:
        """
        Simple keyword-based fallback when LLM fails.
        Extracts what we can from the raw query without AI.
        """
        # Split query into potential search terms
        words = query.lower().split()
        
        # Try to detect certifications by common patterns
        cert_keywords = ["iso", "soc", "gdpr", "hipaa", "cmmi", "ce", "ul", "fda"]
        certs = [w.upper() for w in words if any(ck in w for ck in cert_keywords)]
        
        return {
            "product_or_service": query,
            "industry": "General",
            "certifications_required": certs,
            "search_keywords": [
                query,
                f"{query} suppliers",
                f"{query} vendors",
                f"{query} manufacturers",
                f"best {query} companies"
            ]
        }
