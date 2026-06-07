# ============================================================
# VendorScout Pro - Risk Assessment Agent (V1.2)
# ============================================================
# Identifies potential risks associated with each vendor by:
# 1. Searching for negative news, lawsuits, recalls
# 2. Checking online reviews and reputation signals
# 3. Assessing geopolitical and supply chain risks
#
# Combines SerperDev news search with the browser agent review scraping
# and the LLM sentiment analysis for comprehensive risk profiling.
#
# V1.2: Multi-phase prompts, robust JSON parsing.
# ============================================================

import asyncio
import json
import logging
from typing import Optional

from app.agents.base import BaseAgent
from app.tools.json_parser import parse_json_robust

logger = logging.getLogger(__name__)

# Search templates for risk-related news
RISK_SEARCH_QUERIES = [
    '"{company}" lawsuit OR recall OR scandal OR violation',
    '"{company}" review OR complaint OR problem',
    '"{company}" supply chain risk OR delay OR shortage',
]

# Multi-phase the browser agent prompt for checking vendor reviews/reputation (V1.2)
REVIEW_CHECK_PROMPT = """You are a procurement risk analyst checking this vendor's reputation.

PHASE_1 - NAVIGATE TO REPUTATION INFO:
- Look for "Testimonials", "Reviews", "Clients", or "Case Studies" sections
- Check for third-party review badges (G2, Trustpilot, BBB, Capterra)
- Look for trust indicators in footer or sidebar

PHASE_2 - EXTRACT REPUTATION DATA:
- Customer reviews and ratings found
- Business reputation scores (BBB rating, Trustpilot score, G2 ratings)
- Complaint records or negative mentions
- Industry recognition, awards, or accreditations
- Client testimonials or case study outcomes

Search for reviews and reputation information about \"{company_name}\".

Return ONLY valid JSON:
{{ "reviews": [], "ratings": {{}}, "complaints": [], "awards": [] }}"""

# LLM prompt for risk assessment synthesis
RISK_ASSESSMENT_PROMPT = """Assess the overall risk profile of this vendor based on available data.

Company: {company_name}
Website: {website}
Industry: {industry}

Negative News Search Results:
{negative_news}

Reputation & Review Data:
{reputation_data}

Return ONLY valid JSON:
{{
    "overall_risk_score": 0.0 to 1.0 (0 = low risk, 1 = extremely high risk),
    "risk_level": "low" | "medium" | "high" | "critical",
    "negative_news_found": [
        {{"headline": "...", "severity": "low/medium/high", "summary": "..."}}
    ],
    "reputation_score": 0.0 to 1.0 (1 = excellent reputation),
    "review_summary": "summary of online reviews if found",
    "identified_risks": [
        {{"category": "legal/financial/operational/reputational/geopolitical", 
          "description": "...",
          "severity": "low/medium/high"}}
    ],
    "risk_mitigation_suggestions": ["suggested ways to mitigate identified risks"],
    "risk_summary": "2-3 sentence overall risk assessment"
}}"""


class RiskAgent(BaseAgent):
    """
    Comprehensive risk assessment for discovered vendors.
    
    Searches for:
    - Negative news (lawsuits, recalls, violations)
    - Online reputation (reviews, ratings, complaints)
    - Industry-specific risks (supply chain, geopolitical)
    
    Produces a risk score and categorized risk inventory.
    """
    
    name = "risk"
    description = "Risk Assessment"
    
    async def execute(self, state: dict, job_id: str) -> dict:
        """
        Assess risks for all discovered vendors.
        
        State input: {"vendors": [...], "parsed_requirements": {...}}
        State output: {"risk_data": {vendor_url: risk_assessment}}
        """
        vendors = state.get("vendors", [])
        requirements = state.get("parsed_requirements", {})
        industry = requirements.get("industry", "General")
        
        if not vendors:
            await self.log_activity(job_id, "running", "No vendors to assess risk for")
            return {"risk_data": {}}
        
        await self.log_activity(
            job_id, "running",
            f"Running risk assessment for {len(vendors)} vendors in {industry} industry"
        )
        
        risk_data = {}
        
        for i, vendor in enumerate(vendors):
            company_name = vendor.get("company_name", "Unknown")
            website = vendor.get("website", "")
            
            await self.log_activity(
                job_id, "running",
                f"Risk assessment [{i+1}/{len(vendors)}]: {company_name}"
            )
            
            assessment = await self._assess_vendor_risk(
                vendor, industry, job_id
            )
            
            if assessment:
                risk_data[website] = assessment
            
            await asyncio.sleep(0.2)
        
        # Count high-risk vendors
        high_risk_count = sum(
            1 for r in risk_data.values()
            if r.get("risk_level") in ("high", "critical")
        )
        
        return {
            "risk_data": risk_data,
            "high_risk_vendor_count": high_risk_count,
            "_findings_count": len(risk_data)
        }
    
    async def _assess_vendor_risk(
        self, vendor: dict, industry: str, job_id: str
    ) -> Optional[dict]:
        """
        Run full risk assessment for a single vendor.
        Combines news search, reputation check, and AI synthesis.
        """
        company_name = vendor.get("company_name", "Unknown")
        website = vendor.get("website", "")
        
        try:
            # Step 1: Search for negative news
            negative_news_parts = []
            for query_template in RISK_SEARCH_QUERIES[:2]:
                query = query_template.format(company=company_name)
                results = await self.search.search_news(query, num_results=5)
                for r in results:
                    negative_news_parts.append(f"- [{r.title}]: {r.snippet}")
                await asyncio.sleep(0.2)
            
            negative_news = "\n".join(negative_news_parts) if negative_news_parts else "No negative news found"
            
            # Step 2: Use the browser agent to check online reputation
            # the browser agent navigates the vendor's website (or Google) for reputation data
            reputation_url = website if website else f"https://www.google.com/search?q={company_name}+reviews+reputation"
            browser_result = await self.browser.run_task(
                url=reputation_url,
                goal=REVIEW_CHECK_PROMPT.format(company_name=company_name)
            )
            
            if browser_result.success and browser_result.extracted_data:
                reputation_data = json.dumps(browser_result.extracted_data)
            elif browser_result.raw_text:
                # V1.2: Robust JSON parser for the browser agent output
                parsed = parse_json_robust(browser_result.raw_text)
                reputation_data = json.dumps(parsed) if parsed else browser_result.raw_text
            else:
                reputation_data = "No reputation data found online."
            
            # Step 3: Synthesize into risk assessment using the LLM
            assessment = await self.llm.generate_structured(
                RISK_ASSESSMENT_PROMPT.format(
                    company_name=company_name,
                    website=website,
                    industry=industry,
                    negative_news=negative_news[:2000],
                    reputation_data=reputation_data[:2000]
                ),
                system_prompt="You are a risk analyst specializing in vendor due diligence. Return only valid JSON."
            )
            
            return assessment
            
        except Exception as e:
            logger.error(f"Risk assessment failed for {company_name}: {e}")
            return {
                "overall_risk_score": 0.5,
                "risk_level": "medium",
                "negative_news_found": [],
                "identified_risks": [{
                    "category": "operational",
                    "description": f"Risk assessment incomplete: {str(e)}",
                    "severity": "medium"
                }],
                "risk_summary": f"Risk assessment could not be fully completed: {str(e)}"
            }
