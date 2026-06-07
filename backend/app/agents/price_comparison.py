# ============================================================
# VendorScout Pro - Price Comparison Agent (V2.0)
# ============================================================
# Performs pricing intelligence for discovered vendors by:
# 1. Searching for vendor pricing on their website
# 2. Finding competitor/market pricing for comparison
# 3. Calculating price index and competitiveness metrics
# 4. Generating market positioning summary
#
# Uses Google Search (SerperDev) to find pricing data and
# the browser agent to extract specific pricing from pages.
# LLM synthesizes findings into structured price analysis.
#
# Integration: Runs in parallel with Authenticity and Specification
# agents during the extended assessment phase.
# ============================================================

import asyncio
import json
import logging
from typing import Optional

from app.agents.base import BaseAgent
from app.tools.json_parser import parse_json_robust
from app import database as db

logger = logging.getLogger(__name__)

# the browser agent prompt for extracting pricing from vendor websites
PRICE_SCRAPE_PROMPT = """You are a pricing analyst extracting pricing information from this vendor's website.

PHASE_1 - FIND PRICING PAGES:
- Look for "Pricing", "Plans", "Packages", "Products", "Services", "Quote" pages
- Check for pricing tables, plan comparison charts
- Look for "Starting at", "From", "per month", "per year", "per user" indicators
- Find any downloadable price lists or catalogs

PHASE_2 - EXTRACT PRICE DATA:
- For each product/service/plan found, extract: name, price, currency, billing_period
- Note any volume discounts, enterprise pricing tiers
- Capture free tier / free trial details
- Look for "Contact Sales" (indicates custom/enterprise pricing)
- Identify the pricing model (per user, per unit, flat rate, usage-based)

Return ONLY valid JSON:
{{ "pricing_found": true/false, "pricing_model": "per_user|per_unit|flat_rate|usage_based|custom|mixed", "plans": [{{ "name": "", "price": 0, "currency": "INR", "billing_period": "monthly|yearly|one_time", "features": [] }}], "enterprise_pricing": true/false, "free_tier": true/false, "contact_for_pricing": true/false, "pricing_url": "" }}"""

# Search query template for finding market pricing
MARKET_PRICE_SEARCH = "{product_service} pricing India {year}"

# LLM prompt for price analysis synthesis
PRICE_ANALYSIS_PROMPT = """Analyze the pricing intelligence for this vendor compared to market rates.

Vendor: {company_name}
Website: {website}
Product/Service Category: {product_service}

Vendor's Pricing Data:
{vendor_pricing}

Market/Competitor Pricing Data:
{market_pricing}

Calculate and return ONLY valid JSON:
{{
    "product_or_service": "what they sell",
    "prices_found": [
        {{ "source": "vendor name or source", "price": 0.0, "currency": "INR", "url": "" }}
    ],
    "average_price": 0.0,
    "median_price": 0.0,
    "min_price": 0.0,
    "max_price": 0.0,
    "price_index": 100.0,
    "price_competitiveness": "very_competitive|competitive|average|premium|overpriced",
    "pricing_model": "subscription/per_unit/flat_rate/custom",
    "market_summary": "2-3 sentence analysis of pricing position in the market"
}}

Notes:
- price_index = (vendor_price / market_average) * 100. Below 100 = cheaper than market.
- If exact numbers unavailable, estimate from available data and market knowledge.
- If pricing is custom/enterprise (contact sales), note this and estimate based on market."""


class PriceComparisonAgent(BaseAgent):
    """
    Performs pricing intelligence and market comparison for vendors.
    
    For each vendor discovered by ResearchAgent:
    1. Scrapes vendor website for pricing information
    2. Searches market for competitor/comparable pricing
    3. Calculates price index and competitiveness
    4. Stores results in price_analysis table
    """
    
    name = "price_comparison"
    description = "Price Comparison"
    
    async def execute(self, state: dict, job_id: str) -> dict:
        """
        Analyze pricing for all discovered vendors.
        
        State input: {"vendors": [...], "parsed_requirements": {...}}
        State output: {"price_data": {vendor_website: price_analysis}}
        """
        vendors = state.get("vendors", [])
        requirements = state.get("parsed_requirements", {})
        product_service = requirements.get("product_or_service", "")
        
        if not vendors:
            await self.log_activity(job_id, "running", "No vendors to analyze pricing for")
            return {"price_data": {}}
        
        await self.log_activity(
            job_id, "running",
            f"Analyzing pricing for {len(vendors)} vendors"
        )
        
        # Step 1: Gather market pricing context (one search for all vendors)
        market_context = await self._gather_market_pricing(product_service)
        
        price_data = {}
        analyzed_count = 0
        
        for i, vendor in enumerate(vendors):
            company_name = vendor.get("company_name", "Unknown")
            website = vendor.get("website", "")
            
            await self.log_activity(
                job_id, "running",
                f"Analyzing pricing [{i+1}/{len(vendors)}]: {company_name}"
            )
            
            analysis = await self._analyze_vendor_pricing(
                vendor, product_service, market_context, job_id
            )
            
            if analysis:
                price_data[website] = analysis
                
                # Save to database
                await db.save_price_analysis(job_id, website, analysis)
                analyzed_count += 1
            
            await asyncio.sleep(0.2)
        
        await self.log_activity(
            job_id, "running",
            f"Price analysis complete: analyzed {analyzed_count}/{len(vendors)} vendors",
            findings_count=analyzed_count
        )
        
        return {
            "price_data": price_data,
            "_findings_count": analyzed_count
        }
    
    async def _gather_market_pricing(self, product_service: str) -> str:
        """
        Search for general market pricing context for the product/service category.
        Returns a text summary of market pricing to use as context for each vendor.
        """
        if not product_service:
            return "No product/service specified for market price comparison."
        
        try:
            search_query = MARKET_PRICE_SEARCH.format(
                product_service=product_service,
                year="2026"
            )
            results = await self.search.search(search_query, num_results=5)
            
            if results:
                # Compile snippets into market context
                snippets = []
                for r in results[:5]:
                    title = r.title if hasattr(r, 'title') else str(r)
                    snippet = r.snippet if hasattr(r, 'snippet') else ""
                    snippets.append(f"- {title}: {snippet}")
                return "\n".join(snippets)
            
            return "No market pricing data found via search."
            
        except Exception as e:
            logger.warning(f"Market pricing search failed: {e}")
            return "Market pricing search unavailable."
    
    async def _analyze_vendor_pricing(
        self, vendor: dict, product_service: str, market_context: str, job_id: str
    ) -> Optional[dict]:
        """
        Analyze a single vendor's pricing including market comparison.
        """
        website = vendor.get("website", "")
        company_name = vendor.get("company_name", "Unknown")
        
        try:
            # Step 1: Use the browser agent to scrape vendor's pricing page
            browser_result = await self.browser.run_task(
                url=website,
                goal=PRICE_SCRAPE_PROMPT
            )
            
            if browser_result.success and browser_result.extracted_data:
                vendor_pricing = json.dumps(browser_result.extracted_data)
            elif browser_result.raw_text:
                parsed = parse_json_robust(browser_result.raw_text)
                vendor_pricing = json.dumps(parsed) if parsed else browser_result.raw_text
            else:
                vendor_pricing = "No pricing information found on vendor website."
            
            # Step 2: Use LLM to synthesize price analysis
            analysis = await self.llm.generate_structured(
                PRICE_ANALYSIS_PROMPT.format(
                    company_name=company_name,
                    website=website,
                    product_service=product_service or "general services",
                    vendor_pricing=vendor_pricing[:2000],
                    market_pricing=market_context[:2000],
                ),
                system_prompt="You are a pricing analyst expert. Calculate price metrics accurately. Return only valid JSON."
            )
            
            return analysis
            
        except Exception as e:
            logger.error(f"Price analysis failed for {company_name}: {e}")
            return {
                "product_or_service": product_service,
                "prices_found": [],
                "average_price": 0.0,
                "median_price": 0.0,
                "min_price": 0.0,
                "max_price": 0.0,
                "price_index": 100.0,
                "price_competitiveness": "unknown",
                "market_summary": f"Price analysis failed for {company_name}: {str(e)}"
            }
