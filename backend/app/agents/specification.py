# ============================================================
# VendorScout Pro - Specification Corpus Agent (V2.0)
# ============================================================
# Builds enriched product/service specification profiles by:
# 1. Extracting detailed specifications from vendor websites
# 2. Searching for supplementary specs from manufacturer/third-party sources
# 3. Cross-validating specs across sources for accuracy
# 4. Scoring completeness against category-specific templates
#
# Uses the browser agent to navigate spec tables, feature lists, and datasheets.
# LLM aggregates specs from multiple sources with confidence scoring.
#
# Integration: Runs in parallel with Authenticity and Price Comparison
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

# Category-specific specification templates define expected attributes
# for common B2B product/service categories
CATEGORY_TEMPLATES = {
    "cloud_security": [
        "deployment_model", "encryption_standards", "compliance_frameworks",
        "sla_uptime", "data_residency", "incident_response_time",
        "access_control", "audit_logging", "backup_frequency",
        "support_tiers", "api_availability", "integration_options"
    ],
    "software": [
        "platform_support", "programming_languages", "api_type",
        "scalability", "hosting_options", "data_storage",
        "user_limit", "sla_uptime", "support_channels",
        "update_frequency", "documentation_quality", "security_features"
    ],
    "manufacturing": [
        "production_capacity", "quality_certifications", "material_specs",
        "lead_time", "minimum_order_quantity", "testing_standards",
        "packaging_options", "supply_chain_visibility", "warranty_terms",
        "customization_capability", "export_capabilities"
    ],
    "consulting": [
        "team_size", "domain_expertise", "methodology",
        "engagement_models", "delivery_timeline", "client_references",
        "industry_experience_years", "case_studies_available",
        "nda_compliance", "post_engagement_support"
    ],
    "general": [
        "core_offering", "key_features", "target_market",
        "deployment_options", "support_availability", "pricing_model",
        "scalability", "security_features", "integration_options",
        "compliance_certifications"
    ],
}

# the browser agent prompt for extracting detailed specifications
SPEC_SCRAPE_PROMPT = """You are a technical analyst extracting detailed product/service specifications.

PHASE_1 - FIND SPECIFICATION PAGES:
- Look for "Products", "Services", "Features", "Technical Specs", "Solutions" pages
- Find specification tables, feature comparison charts, datasheet downloads
- Look for "How it works", "Architecture", "Technical Details" sections
- Check for PDF datasheets or whitepaper links

PHASE_2 - EXTRACT SPECIFICATIONS:
For each product/service, extract ALL available specifications:
- Technical specifications (performance, capacity, limits)
- Features and capabilities
- Compliance and security features
- Integration options (APIs, plugins, connectors)
- Support and SLA details
- Deployment options (cloud, on-premise, hybrid)
- Platform/technology stack details

Return ONLY valid JSON:
{{ "products_services": [{{ "name": "", "category": "", "specifications": {{ "key": "value" }}, "features": [], "limitations": [] }}], "technical_docs_available": true/false, "datasheet_urls": [], "technology_stack": [] }}"""

# LLM prompt for specification enrichment and scoring
SPEC_ENRICHMENT_PROMPT = """Enrich and validate the product/service specifications for this vendor.

Vendor: {company_name}
Website: {website}
Product/Service Category: {product_service}
Industry: {industry}

Scraped Specification Data:
{scraped_specs}

Supplementary Market Data:
{market_data}

Expected specifications for this category: {expected_specs}

Tasks:
1. Merge scraped specs with market knowledge for completeness
2. Score confidence for each spec (0.0-1.0) — higher if from official sources
3. Identify missing but expected specifications
4. Assign a product_category from: cloud_security, software, manufacturing, consulting, general

Return ONLY valid JSON:
{{
    "product_category": "category name",
    "specifications": [
        {{ "attribute_name": "", "attribute_value": "", "confidence": 0.0 to 1.0, "source": "vendor_website|market_data|inferred" }}
    ],
    "completeness_score": 0.0 to 1.0,
    "sources_checked": 2,
    "missing_attributes": ["list of expected specs not found"],
    "summary": "2-3 sentence summary of specification completeness and quality"
}}"""


class SpecificationAgent(BaseAgent):
    """
    Builds enriched specification corpus for vendor products/services.
    
    For each vendor discovered by ResearchAgent:
    1. Scrapes vendor website for detailed specs via the browser agent
    2. Searches for supplementary technical data
    3. Merges and validates specs with confidence scoring
    4. Stores enriched spec corpus in specification_corpus table
    """
    
    name = "specification"
    description = "Specification Enrichment"
    
    async def execute(self, state: dict, job_id: str) -> dict:
        """
        Build specification corpus for all discovered vendors.
        
        State input: {"vendors": [...], "parsed_requirements": {...}}
        State output: {"specification_data": {vendor_website: spec_result}}
        """
        vendors = state.get("vendors", [])
        requirements = state.get("parsed_requirements", {})
        product_service = requirements.get("product_or_service", "")
        industry = requirements.get("industry", "General")
        
        if not vendors:
            await self.log_activity(job_id, "running", "No vendors to build specification corpus for")
            return {"specification_data": {}}
        
        await self.log_activity(
            job_id, "running",
            f"Building specification corpus for {len(vendors)} vendors"
        )
        
        specification_data = {}
        enriched_count = 0
        
        for i, vendor in enumerate(vendors):
            company_name = vendor.get("company_name", "Unknown")
            website = vendor.get("website", "")
            
            await self.log_activity(
                job_id, "running",
                f"Extracting specifications [{i+1}/{len(vendors)}]: {company_name}"
            )
            
            spec_result = await self._build_vendor_specs(
                vendor, product_service, industry, job_id
            )
            
            if spec_result:
                specification_data[website] = spec_result
                
                # Save to database
                await db.save_specification_corpus(job_id, website, spec_result)
                
                if spec_result.get("completeness_score", 0) > 0.3:
                    enriched_count += 1
            
            await asyncio.sleep(0.2)
        
        await self.log_activity(
            job_id, "running",
            f"Specification enrichment complete: {enriched_count}/{len(vendors)} vendors "
            f"have adequate specification data",
            findings_count=enriched_count
        )
        
        return {
            "specification_data": specification_data,
            "_findings_count": enriched_count
        }
    
    def _get_expected_specs(self, product_service: str, industry: str) -> list[str]:
        """
        Determine which specification template to use based on product/industry.
        Returns list of expected specification attribute names.
        """
        # Try to match industry/product to a known category
        search_text = f"{product_service} {industry}".lower()
        
        if any(term in search_text for term in ["security", "cyber", "firewall", "cloud"]):
            return CATEGORY_TEMPLATES["cloud_security"]
        elif any(term in search_text for term in ["software", "saas", "platform", "app"]):
            return CATEGORY_TEMPLATES["software"]
        elif any(term in search_text for term in ["manufactur", "production", "factory"]):
            return CATEGORY_TEMPLATES["manufacturing"]
        elif any(term in search_text for term in ["consult", "advisory", "professional service"]):
            return CATEGORY_TEMPLATES["consulting"]
        
        return CATEGORY_TEMPLATES["general"]
    
    async def _build_vendor_specs(
        self, vendor: dict, product_service: str, industry: str, job_id: str
    ) -> Optional[dict]:
        """
        Build the specification profile for a single vendor.
        """
        website = vendor.get("website", "")
        company_name = vendor.get("company_name", "Unknown")
        
        expected_specs = self._get_expected_specs(product_service, industry)
        
        try:
            # Step 1: Scrape vendor website for specifications
            browser_result = await self.browser.run_task(
                url=website,
                goal=SPEC_SCRAPE_PROMPT
            )
            
            if browser_result.success and browser_result.extracted_data:
                scraped_specs = json.dumps(browser_result.extracted_data)
            elif browser_result.raw_text:
                parsed = parse_json_robust(browser_result.raw_text)
                scraped_specs = json.dumps(parsed) if parsed else browser_result.raw_text
            else:
                scraped_specs = "No specification data found on vendor website."
            
            # Step 2: Search for supplementary technical data
            market_data = await self._search_supplementary_specs(company_name, product_service)
            
            # Step 3: Use LLM to enrich and validate specifications
            spec_result = await self.llm.generate_structured(
                SPEC_ENRICHMENT_PROMPT.format(
                    company_name=company_name,
                    website=website,
                    product_service=product_service or "general services",
                    industry=industry,
                    scraped_specs=scraped_specs[:3000],
                    market_data=market_data[:1500],
                    expected_specs=", ".join(expected_specs),
                ),
                system_prompt="You are a technical product analyst. Extract and enrich specifications accurately. Return only valid JSON."
            )
            
            return spec_result
            
        except Exception as e:
            logger.error(f"Specification extraction failed for {company_name}: {e}")
            return {
                "product_category": "general",
                "specifications": [],
                "completeness_score": 0.0,
                "sources_checked": 0,
                "missing_attributes": expected_specs,
                "summary": f"Specification extraction failed for {company_name}: {str(e)}"
            }
    
    async def _search_supplementary_specs(self, company_name: str, product_service: str) -> str:
        """
        Search for supplementary technical data from third-party sources.
        """
        if not product_service:
            return "No product/service specified for supplementary search."
        
        try:
            query = f"{company_name} {product_service} technical specifications features"
            results = await self.search.search(query, num_results=3)
            
            if results:
                snippets = []
                for r in results[:3]:
                    title = r.title if hasattr(r, 'title') else str(r)
                    snippet_text = r.snippet if hasattr(r, 'snippet') else ""
                    snippets.append(f"- {title}: {snippet_text}")
                return "\n".join(snippets)
            
            return "No supplementary specification data found."
            
        except Exception as e:
            logger.warning(f"Supplementary spec search failed: {e}")
            return "Supplementary specification search unavailable."
