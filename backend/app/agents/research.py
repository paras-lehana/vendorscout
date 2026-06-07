# ============================================================
# VendorScout Pro - Research Agent (V1.3)
# ============================================================
# Core vendor discovery engine. Uses SerperDev for Google search
# and Playwright browser agent for actual website navigation to extract
# detailed vendor information.
#
# Pipeline:
# 1. Run Google searches using parsed keywords
# 2. Filter results for likely vendor/supplier URLs
# 3. Use the browser agent to navigate vendor websites and extract data
# 4. Compile initial vendor profiles
#
# V1.2 Changes (cookbook-inspired):
# - Multi-phase goal prompts for deeper vendor extraction
# - Robust JSON parsing for the browser agent output
# - Smart browser profile auto-selection (stealth for directories)
#
# V1.3 Changes:
# - Tiered detail levels (low/medium/high) — control vendor count,
#   keyword search depth, and the browser agent timeout per level.
# ============================================================

import asyncio
import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse

from app.agents.base import BaseAgent
from app.tools.search_tool import SearchResult
from app.tools.json_parser import parse_json_robust

logger = logging.getLogger(__name__)

# ---- Tiered Detail Level Configuration (V1.3) ----
# Each detail level controls how deeply the research agent digs.
# low:    Speed-focused — fewer vendors, fewer keywords, shorter timeout
# medium: Balanced default — standard depth (matches V1.2 behavior)
# high:   Thoroughness — more vendors, more keywords, longer timeout
#
# max_vendors:    How many vendor sites to deep-scrape with the browser agent
# keyword_limit:  How many keyword phrases to Google-search
# browser_timeout: Max seconds to wait for each the browser agent scrape
# concurrent_scrape: Max parallel the browser agent tasks
DETAIL_LEVEL_CONFIG = {
    "low": {
        "max_vendors": 5,
        "keyword_limit": 3,
        "browser_timeout": 60,
        "concurrent_scrape": 3,
    },
    "medium": {
        "max_vendors": 8,
        "keyword_limit": 6,
        "browser_timeout": 120,
        "concurrent_scrape": 3,
    },
    "high": {
        "max_vendors": 12,
        "keyword_limit": 8,
        "browser_timeout": 180,
        "concurrent_scrape": 4,
    },
}

# Default fallback (medium matches V1.2 constants)
MAX_VENDORS = 8
MAX_CONCURRENT_SCRAPE = 3

# ---- Multi-Phase Vendor Extraction Prompt ----
# Inspired by agentic-web patterns (logistics-sentry, game-buying-guide).
# Multi-phase goals guide the agent through complex multi-page navigation,
# ensuring deeper data extraction versus a single-pass prompt.
#
# PHASE_1: Navigate and orient — find key pages
# PHASE_2: Extract core business data — products, services, certifications
# PHASE_3: Gather contact and commercial data — pricing, clients, contact info
VENDOR_EXTRACT_PROMPT = """You are a B2B procurement research agent. Extract vendor information from this website.

PHASE_1 - NAVIGATE & ORIENT:
- If on a homepage, look for "About", "Products", "Services", "Solutions", or "Company" links
- Navigate to the most informative page about this company's offerings
- Note the company name and primary business focus

PHASE_2 - EXTRACT CORE BUSINESS DATA:
- Company official name and brand
- List of products/services offered
- Key certifications, awards, or accreditations (ISO, SOC2, CE, etc.)
- Company size indicators (employees, revenue, locations)
- Industries served
- Year established or history

PHASE_3 - GATHER COMMERCIAL DATA:
- Pricing information (if publicly visible)
- Contact information (email, phone, address)
- Notable clients or case studies
- Technology stack or capabilities

Return ONLY valid JSON:
{{ "company_name": "", "products_services": [], "pricing": "", "contact": {{"email": "", "phone": "", "address": ""}}, "certifications": [], "company_size": "", "notable_clients": [], "year_established": "", "industries_served": [], "description": "" }}"""

# LLM prompt to consolidate raw scraped data into a vendor profile.
CONSOLIDATE_PROMPT = """Given the following raw data scraped from a vendor's website, create a clean vendor profile.

Company URL: {url}
Search Result Title: {title}
Search Result Snippet: {snippet}

Scraped Website Data:
{scraped_data}

Return ONLY valid JSON:
{{
    "company_name": "official company name",
    "website": "{url}",
    "description": "1-2 sentence description of what they do",
    "products_services": ["list of relevant products/services"],
    "pricing_info": "any pricing details found or 'Not available'",
    "contact": {{
        "email": "email or null",
        "phone": "phone or null",
        "address": "address or null"
    }},
    "certifications": ["list of certifications found"],
    "company_size": "small/medium/large/enterprise based on indicators",
    "key_clients": ["notable clients if mentioned"],
    "year_established": "year or null",
    "relevance_score": 0.0 to 1.0 based on how relevant this vendor is
}}"""


class ResearchAgent(BaseAgent):
    """
    Core vendor discovery agent.
    
    Uses a two-step approach:
    1. Google search via SerperDev to find vendor URLs
    2. the browser agent web agent to navigate and extract real data
    
    This combination is the key hackathon requirement:
    demonstrating real web navigation, not just API calls.
    """
    
    name = "research"
    description = "Vendor Discovery & Research"
    
    async def execute(self, state: dict, job_id: str) -> dict:
        """
        Discover and profile vendors based on parsed requirements.
        
        State input: {"search_keywords": [...], "parsed_requirements": {...}, "detail_level": "medium"}
        State output: {"vendors": [{vendor_profile}, ...], "search_results_count": int}
        
        V1.3: Reads detail_level from state to control:
        - max_vendors: Number of vendor sites to scrape (5/8/12)
        - keyword_limit: Number of Google searches to run (3/6/8)
        - browser_timeout: Seconds per scrape (60/120/180)
        """
        keywords = state.get("search_keywords", [])
        requirements = state.get("parsed_requirements", {})
        product = requirements.get("product_or_service", "unknown product")
        
        # V1.3: Get tiered config based on detail_level
        detail_level = state.get("detail_level", "medium")
        tier = DETAIL_LEVEL_CONFIG.get(detail_level, DETAIL_LEVEL_CONFIG["medium"])
        max_vendors = tier["max_vendors"]
        keyword_limit = tier["keyword_limit"]
        concurrent_scrape = tier["concurrent_scrape"]
        
        if not keywords:
            raise ValueError("No search keywords provided to research agent")
        
        await self.log_activity(
            job_id, "running",
            f"Detail level: {detail_level} (max {max_vendors} vendors, {keyword_limit} keywords)"
        )
        
        if not keywords:
            raise ValueError("No search keywords provided to research agent")
        
        # ---- Step 1: Google Search across all keywords ----
        await self.log_activity(
            job_id, "running",
            f"Searching Google for vendors: {min(len(keywords), keyword_limit)} keyword sets"
        )
        
        all_results = []
        seen_domains = set()
        
        # V1.3: keyword_limit controls how many keyword sets we search
        # low=3 (quick scan), medium=6 (standard), high=8 (thorough)
        for keyword in keywords[:keyword_limit]:
            results = await self.search.search(keyword, num_results=10)
            
            for result in results:
                domain = self._extract_domain(result.url)
                # Deduplicate by domain - we only want one page per vendor
                if domain and domain not in seen_domains and self._is_likely_vendor(result):
                    seen_domains.add(domain)
                    all_results.append(result)
            
            # Small delay between searches to be respectful to API limits
            await asyncio.sleep(0.3)
        
        await self.log_activity(
            job_id, "running",
            f"Found {len(all_results)} unique potential vendor websites across {len(seen_domains)} domains"
        )
        
        # ---- Step 2: Rank and select top candidates ----
        # Prioritize results that look most like actual vendor/supplier sites
        # V1.3: max_vendors is tiered — low=5, medium=8, high=12
        ranked_results = self._rank_results(all_results, product)[:max_vendors]
        
        await self.log_activity(
            job_id, "running",
            f"Selected top {len(ranked_results)} candidates for deep analysis via the browser agent"
        )
        
        # ---- Step 3: Scrape vendor websites using the browser agent ----
        # Run the browser agent in parallel with semaphore to limit concurrency
        # V1.3: concurrent_scrape is tiered — low/medium=3, high=4
        semaphore = asyncio.Semaphore(concurrent_scrape)
        
        async def scrape_one(result: SearchResult) -> Optional[dict]:
            async with semaphore:
                return await self._scrape_vendor(result, job_id)
        
        scrape_tasks = [scrape_one(r) for r in ranked_results]
        vendor_profiles = await asyncio.gather(*scrape_tasks, return_exceptions=True)
        
        # Filter out failures and exceptions
        vendors = []
        for i, profile in enumerate(vendor_profiles):
            if isinstance(profile, Exception):
                logger.warning(f"Scrape failed for {ranked_results[i].url}: {profile}")
                continue
            if profile and profile.get("company_name"):
                vendors.append(profile)
        
        await self.log_activity(
            job_id, "running",
            f"Successfully profiled {len(vendors)} vendors out of {len(ranked_results)} attempted",
            findings_count=len(vendors)
        )
        
        return {
            "vendors": vendors,
            "search_results_count": len(all_results),
            "_findings_count": len(vendors)
        }
    
    async def _scrape_vendor(self, result: SearchResult, job_id: str) -> Optional[dict]:
        """
        Use the browser agent to navigate a vendor's website and extract data.
        Then consolidate the raw data into a clean vendor profile using the LLM.
        
        This two-step approach (the browser agent scrape → the LLM consolidation)
        ensures we get structured data even from messy web pages.
        
        V1.2: Uses robust JSON parser (handles markdown fences, trailing commas)
        and auto browser_profile selection (stealth for marketplaces).
        """
        url = result.url
        
        try:
            await self.log_activity(
                job_id, "running",
                f"🔍 the browser agent navigating: {self._extract_domain(url)}"
            )
            
            # Use the browser agent to actually navigate the website
            # browser_profile="auto" selects stealth for marketplaces (V1.2)
            browser_result = await self.browser.run_task(
                url=url,
                goal=VENDOR_EXTRACT_PROMPT
            )
            
            # Extract data from BrowserResult object
            if browser_result.success and browser_result.extracted_data:
                scraped_data = json.dumps(browser_result.extracted_data)
            elif browser_result.raw_text:
                # V1.2: Use robust JSON parser for raw text (handles LLM formatting quirks)
                parsed = parse_json_robust(browser_result.raw_text)
                scraped_data = json.dumps(parsed) if parsed else browser_result.raw_text
            else:
                scraped_data = None
            
            if not scraped_data:
                logger.warning(f"the browser agent returned empty data for {url}")
                # Fall back to using just the search result snippet
                scraped_data = f"Title: {result.title}\nSnippet: {result.snippet}"
            
            # Use the LLM to consolidate raw scraped data into structured profile
            profile = await self.llm.generate_structured(
                CONSOLIDATE_PROMPT.format(
                    url=url,
                    title=result.title,
                    snippet=result.snippet or "",
                    scraped_data=scraped_data[:3000]  # Cap to avoid token limits
                ),
                system_prompt="You are a vendor data analyst. Return only valid JSON."
            )
            
            if profile:
                # Ensure website URL is set correctly
                profile["website"] = url
                profile["source"] = "browser_scrape"
                return profile
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to scrape {url}: {e}")
            # Return minimal profile from search result alone
            return {
                "company_name": result.title.split(" - ")[0].split(" | ")[0].strip(),
                "website": url,
                "description": result.snippet or "",
                "products_services": [],
                "certifications": [],
                "relevance_score": 0.3,
                "source": "search_result_only"
            }
    
    def _extract_domain(self, url: str) -> Optional[str]:
        """Extract clean domain from URL, stripping www prefix."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return None
    
    def _is_likely_vendor(self, result: SearchResult) -> bool:
        """
        Filter out non-vendor results (news articles, Wikipedia, academic papers, etc).
        We want actual company websites, vendor directories, and supplier pages.
        
        This is critical for API efficiency — every URL we keep gets a the browser agent
        call (~$0.01 + 30-180s latency), so aggressive filtering saves money and time.
        """
        url_lower = result.url.lower()
        title_lower = (result.title or "").lower()
        
        # Skip known non-vendor domains — social media, news, encyclopedias
        skip_domains = [
            "wikipedia.org", "youtube.com", "reddit.com", "facebook.com",
            "twitter.com", "instagram.com", "linkedin.com", "pinterest.com",
            "amazon.com", "ebay.com", "quora.com", "medium.com",
            "britannica.com", "investopedia.com", "nytimes.com",
            "bbc.com", "cnn.com", "forbes.com", "bloomberg.com",
            # Academic and government — not vendors
            "nasa.gov", "nih.gov", "ncbi.nlm.nih.gov", "arxiv.org",
            "researchgate.net", "academia.edu", "scholar.google.com",
            # Document hosting — usually PDFs, not vendor sites
            "scribd.com", "slideshare.net", "issuu.com",
            # Financial/investor sites — not vendors
            "ishares.com", "morningstar.com", "sec.gov", "edgar.sec.gov",
            "marketwatch.com", "seekingalpha.com", "finance.yahoo.com",
            # Legal/law sites — not vendors
            "law.cornell.edu", "justia.com",
        ]
        
        if any(domain in url_lower for domain in skip_domains):
            return False
        
        # Skip PDF/document URLs — the browser agent can't navigate these well
        if url_lower.endswith(".pdf") or "/pdf/" in url_lower:
            return False
        
        # Skip government and educational domains — they're not vendors
        domain_suffixes = [".gov/", ".gov.", ".edu/", ".edu."]
        if any(suffix in url_lower for suffix in domain_suffixes):
            return False
        
        # Skip obvious blog/news/article/investor/legal pages
        skip_patterns = [
            "/blog/", "/news/", "/article/", "/wiki/",
            "/investor", "/annual-report", "/sec-filing",
            "/wp-content/uploads/",  # WordPress uploaded PDFs
        ]
        if any(pattern in url_lower for pattern in skip_patterns):
            return False
        
        # Positive signals - these suggest a vendor/supplier page
        vendor_signals = [
            "supplier", "manufacturer", "vendor", "wholesale",
            "industrial", "solutions", "services", "products",
            "company", "about", "contact"
        ]
        
        # At least check the URL/title don't look like a pure news article
        return True
    
    def _rank_results(self, results: list[SearchResult], product: str) -> list[SearchResult]:
        """
        Rank search results by likelihood of being a relevant vendor.
        
        Scoring factors:
        - Product name appears in title/snippet
        - Domain contains industry-related terms
        - Not a marketplace aggregator
        """
        scored = []
        product_words = set(product.lower().split())
        
        for result in results:
            score = 0
            title_lower = (result.title or "").lower()
            snippet_lower = (result.snippet or "").lower()
            url_lower = result.url.lower()
            
            # Bonus for product terms in title
            for word in product_words:
                if len(word) > 3 and word in title_lower:
                    score += 2
                if len(word) > 3 and word in snippet_lower:
                    score += 1
            
            # Bonus for vendor-indicating terms
            vendor_terms = ["manufacturer", "supplier", "provider", "solutions", "inc", "ltd", "llc", "corp"]
            for term in vendor_terms:
                if term in title_lower or term in url_lower:
                    score += 1
            
            # Penalty for aggregator/directory sites (we want actual vendors)
            aggregator_terms = ["top 10", "best of", "review", "comparison", "vs"]
            for term in aggregator_terms:
                if term in title_lower:
                    score -= 1
            
            scored.append((score, result))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored]
