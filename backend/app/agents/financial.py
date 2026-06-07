# ============================================================
# VendorScout Pro - Financial Health Agent (V1.2)
# ============================================================
# Assesses vendor financial stability and viability by:
# 1. Searching for financial indicators on vendor websites
# 2. Looking for funding announcements, revenue data
# 3. Checking business registrations and credit indicators
#
# Uses the browser agent to navigate financial data sources and vendor
# investor/about pages for real financial intelligence.
#
# V1.2: Multi-phase goal prompt, robust JSON parsing.
# ============================================================

import asyncio
import json
import logging
from typing import Optional

from app.agents.base import BaseAgent
from app.tools.json_parser import parse_json_robust

logger = logging.getLogger(__name__)

# Search queries for financial intelligence gathering
FINANCIAL_SEARCH_QUERIES = [
    '"{company}" revenue OR funding OR valuation',
    '"{company}" financial stability OR annual report',
    '"{company}" investment OR acquisition OR growth',
]

# Multi-phase the browser agent prompt for financial data extraction (V1.2)
# PHASE_1 navigates to relevant pages, PHASE_2 extracts deep data
FINANCIAL_EXTRACT_PROMPT = """You are a financial intelligence analyst reviewing this company's website.

PHASE_1 - NAVIGATE TO FINANCIAL INFO:
- Look for "About", "Investor Relations", "Company", "Careers", or "Press" pages
- Check footer for company statistics, founding year, or headquarters
- Look for "Our Clients", "Partners", or "Case Studies" sections

PHASE_2 - EXTRACT FINANCIAL INDICATORS:
- Revenue figures or growth rates (if publicly shared)
- Number of employees (check careers page or about page)
- Funding rounds or investments received
- Number of office locations globally
- Years in business / founding year
- Major client logos, partnerships, or case studies
- Awards for growth, financial performance, or industry leadership
- Investor or stakeholder information

Return ONLY valid JSON:
{{ "revenue": "", "employees": "", "funding": "", "locations": "", "years_in_business": "", "major_clients": [], "awards": [] }}"""

# LLM prompt for financial assessment
FINANCIAL_ASSESSMENT_PROMPT = """Assess the financial health of this vendor based on available data.

Company: {company_name}
Website: {website}
Company Size: {company_size}
Year Established: {year_established}

Financial Data from Website:
{website_data}

Financial Data from Search:
{search_data}

Return ONLY valid JSON:
{{
    "financial_health_score": 0.0 to 1.0,
    "estimated_company_size": "startup/small/medium/large/enterprise",
    "estimated_annual_revenue": "range estimate or 'Unknown'",
    "funding_info": "known funding details or 'Not found'",
    "years_in_business": null or number,
    "employee_count_estimate": "range or 'Unknown'",
    "growth_indicators": ["positive financial signals"],
    "risk_factors": ["financial concerns identified"],
    "stability_assessment": "2-3 sentence assessment",
    "key_clients_or_partners": ["notable business relationships"]
}}"""


class FinancialAgent(BaseAgent):
    """
    Assesses vendor financial health and business viability.
    
    Gathers financial intelligence from:
    1. Vendor's own website (about page, investor relations)
    2. Google search for financial news and data
    3. the LLM analysis to synthesize indicators
    """
    
    name = "financial"
    description = "Financial Health Assessment"
    
    async def execute(self, state: dict, job_id: str) -> dict:
        """
        Assess financial health for all discovered vendors.
        
        State input: {"vendors": [...]}
        State output: {"financial_data": {vendor_url: assessment}}
        """
        vendors = state.get("vendors", [])
        
        if not vendors:
            await self.log_activity(job_id, "running", "No vendors to assess financially")
            return {"financial_data": {}}
        
        await self.log_activity(
            job_id, "running",
            f"Assessing financial health for {len(vendors)} vendors"
        )
        
        financial_data = {}
        
        for i, vendor in enumerate(vendors):
            company_name = vendor.get("company_name", "Unknown")
            website = vendor.get("website", "")
            
            await self.log_activity(
                job_id, "running",
                f"Financial analysis [{i+1}/{len(vendors)}]: {company_name}"
            )
            
            assessment = await self._assess_vendor_financials(vendor, job_id)
            
            if assessment:
                financial_data[website] = assessment
            
            await asyncio.sleep(0.2)
        
        # Count financially healthy vendors
        healthy_count = sum(
            1 for f in financial_data.values()
            if f.get("financial_health_score", 0) > 0.6
        )
        
        return {
            "financial_data": financial_data,
            "_findings_count": healthy_count
        }
    
    async def _assess_vendor_financials(
        self, vendor: dict, job_id: str
    ) -> Optional[dict]:
        """
        Gather and analyze financial data for a single vendor.
        Combines the browser agent website scraping with Google search results.
        """
        company_name = vendor.get("company_name", "Unknown")
        website = vendor.get("website", "")
        company_size = vendor.get("company_size", "Unknown")
        year_established = vendor.get("year_established")
        
        try:
            # Step 1: Search Google for financial news about this company
            search_data_parts = []
            for query_template in FINANCIAL_SEARCH_QUERIES[:2]:  # Limit to 2 searches per vendor
                query = query_template.format(company=company_name)
                results = await self.search.search(query, num_results=3)
                for r in results:
                    search_data_parts.append(f"- {r.title}: {r.snippet}")
                await asyncio.sleep(0.2)
            
            search_data = "\n".join(search_data_parts) if search_data_parts else "No financial news found"
            
            # Step 2: Use the browser agent to check the vendor's own website for financial info
            browser_result = await self.browser.run_task(
                url=website,
                goal=FINANCIAL_EXTRACT_PROMPT
            )
            
            if browser_result.success and browser_result.extracted_data:
                website_data = json.dumps(browser_result.extracted_data)
            elif browser_result.raw_text:
                # V1.2: Robust JSON parser for the browser agent output
                parsed = parse_json_robust(browser_result.raw_text)
                website_data = json.dumps(parsed) if parsed else browser_result.raw_text
            else:
                website_data = "No financial data found on vendor website."
            
            # Step 3: Use the LLM to synthesize all data into financial assessment
            assessment = await self.llm.generate_structured(
                FINANCIAL_ASSESSMENT_PROMPT.format(
                    company_name=company_name,
                    website=website,
                    company_size=company_size,
                    year_established=year_established or "Unknown",
                    website_data=website_data[:2000],
                    search_data=search_data[:2000]
                ),
                system_prompt="You are a financial analyst specializing in vendor assessment. Return only valid JSON."
            )
            
            return assessment
            
        except Exception as e:
            logger.error(f"Financial assessment failed for {company_name}: {e}")
            return {
                "financial_health_score": 0.5,
                "estimated_company_size": company_size,
                "stability_assessment": f"Assessment incomplete: {str(e)}",
                "risk_factors": ["Financial data could not be fully assessed"],
                "growth_indicators": []
            }
