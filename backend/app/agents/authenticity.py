# ============================================================
# VendorScout Pro - Authenticity Verification Agent (V2.0)
# ============================================================
# Verifies vendor/product authenticity by:
# 1. Searching for BIS (Bureau of Indian Standards) certifications
# 2. Cross-referencing certification claims with evidence on website
# 3. Checking for ISO/quality marks and their verification status
# 4. Identifying trust indicators and red flags
#
# Uses the browser agent to navigate vendor websites for certification evidence,
# and LLM to assess authenticity based on collected data.
#
# Integration: Runs in parallel with Price Comparison and Specification
# agents during the extended assessment phase, AFTER the main
# Compliance/Financial/Risk parallel stage.
# ============================================================

import asyncio
import json
import logging
from typing import Optional

from app.agents.base import BaseAgent
from app.tools.json_parser import parse_json_robust
from app import database as db

logger = logging.getLogger(__name__)

# the browser agent prompt for finding certification and authenticity evidence
AUTHENTICITY_SCRAPE_PROMPT = """You are a product authenticity investigator examining this company's website.

PHASE_1 - FIND CERTIFICATION EVIDENCE:
- Look for "Quality", "Certifications", "Standards", "About Us", "Trust" pages
- Check footer/sidebar for certification logos, badges, trust seals
- Look for BIS (Bureau of Indian Standards) ISI Mark, CRS registration
- Find ISO certifications (9001, 14001, 27001, 45001, etc.)
- Look for industry-specific certifications (CE, UL, FDA, FSSAI, NABL)

PHASE_2 - ASSESS AUTHENTICITY INDICATORS:
- Company registration details (CIN, GSTIN, DUNS number)
- Physical address and contact information completeness
- Years in business / founding date
- Client logos, testimonials with verifiable names
- Awards and recognitions from known bodies
- Membership in industry associations

PHASE_3 - IDENTIFY RED FLAGS:
- No physical address or only PO Box
- No verifiable contact information
- Stock photos for team/office
- Unverifiable certification claims
- Very new website with old company claims
- No social media presence or very thin presence

Return ONLY valid JSON:
{{ "certifications_found": [{{ "name": "", "issuer": "", "number": "", "evidence_type": "logo|text_claim|document|registry_link" }}], "trust_indicators": ["list of positive trust signals"], "red_flags": ["list of concerning signs"], "company_registration": {{ "cin": "", "gstin": "", "address": "" }}, "bis_references": ["any BIS/ISI/CRS numbers found"] }}"""

# LLM prompt for authenticity assessment synthesis
AUTHENTICITY_ASSESSMENT_PROMPT = """Assess the authenticity and trustworthiness of this vendor.

Vendor: {company_name}
Website: {website}
Industry: {industry}

Scraped Authenticity Data:
{scraped_data}

Vendor Profile (from research):
- Self-reported certifications: {self_reported_certs}
- Location: {location}
- Claimed founding year: {year_founded}

Evaluate and return ONLY valid JSON:
{{
    "certification_score": 0.0 to 1.0,
    "bis_license_found": true/false,
    "bis_license_number": "if found",
    "verified_certifications": [
        {{ "name": "", "issuer": "", "certificate_number": "", "evidence_type": "logo|text_claim|document|registry_verified", "verification_url": "" }}
    ],
    "unverified_claims": ["certifications claimed but no evidence found"],
    "trust_indicators": ["positive signals found"],
    "red_flags": ["concerning indicators"],
    "summary": "2-3 sentence authenticity assessment"
}}"""


class AuthenticityAgent(BaseAgent):
    """
    Verifies vendor authenticity through certification cross-referencing,
    BIS checks, trust indicator analysis, and red flag identification.
    
    For each vendor discovered by ResearchAgent:
    1. Navigates vendor website via the browser agent to find certification evidence
    2. Uses LLM to synthesize findings into an authenticity score
    3. Stores results in authenticity_checks table
    """
    
    name = "authenticity"
    description = "Authenticity Verification"
    
    async def execute(self, state: dict, job_id: str) -> dict:
        """
        Verify authenticity for all discovered vendors.
        
        State input: {"vendors": [...], "parsed_requirements": {...}}
        State output: {"authenticity_data": {vendor_website: assessment}}
        """
        vendors = state.get("vendors", [])
        requirements = state.get("parsed_requirements", {})
        industry = requirements.get("industry", "General")
        
        if not vendors:
            await self.log_activity(job_id, "running", "No vendors to verify authenticity for")
            return {"authenticity_data": {}}
        
        await self.log_activity(
            job_id, "running",
            f"Verifying authenticity for {len(vendors)} vendors"
        )
        
        authenticity_data = {}
        verified_count = 0
        
        for i, vendor in enumerate(vendors):
            company_name = vendor.get("company_name", "Unknown")
            website = vendor.get("website", "")
            
            await self.log_activity(
                job_id, "running",
                f"Checking authenticity [{i+1}/{len(vendors)}]: {company_name}"
            )
            
            assessment = await self._check_vendor_authenticity(
                vendor, industry, job_id
            )
            
            if assessment:
                authenticity_data[website] = assessment
                
                # Save to database
                await db.save_authenticity_check(job_id, website, assessment)
                
                if assessment.get("certification_score", 0) > 0.6:
                    verified_count += 1
            
            # Brief pause between vendors to avoid overwhelming the target site
            await asyncio.sleep(0.2)
        
        await self.log_activity(
            job_id, "running",
            f"Authenticity verification complete: {verified_count}/{len(vendors)} vendors "
            f"passed trust threshold",
            findings_count=verified_count
        )
        
        return {
            "authenticity_data": authenticity_data,
            "_findings_count": verified_count
        }
    
    async def _check_vendor_authenticity(
        self, vendor: dict, industry: str, job_id: str
    ) -> Optional[dict]:
        """
        Check a single vendor's authenticity.
        Uses the browser agent to find certification evidence, then LLM to synthesize.
        """
        website = vendor.get("website", "")
        company_name = vendor.get("company_name", "Unknown")
        self_reported_certs = vendor.get("certifications", [])
        location = vendor.get("location", "")
        year_founded = vendor.get("year_founded", "Unknown")
        
        try:
            # Step 1: Use the browser agent to scrape certification/authenticity evidence
            browser_result = await self.browser.run_task(
                url=website,
                goal=AUTHENTICITY_SCRAPE_PROMPT
            )
            
            if browser_result.success and browser_result.extracted_data:
                scraped_data = json.dumps(browser_result.extracted_data)
            elif browser_result.raw_text:
                parsed = parse_json_robust(browser_result.raw_text)
                scraped_data = json.dumps(parsed) if parsed else browser_result.raw_text
            else:
                scraped_data = "No authenticity data found on website."
            
            # Step 2: Use LLM to synthesize authenticity assessment
            assessment = await self.llm.generate_structured(
                AUTHENTICITY_ASSESSMENT_PROMPT.format(
                    company_name=company_name,
                    website=website,
                    industry=industry,
                    scraped_data=scraped_data[:3000],
                    self_reported_certs=", ".join(self_reported_certs) if self_reported_certs else "None",
                    location=location,
                    year_founded=year_founded,
                ),
                system_prompt="You are a product authenticity and certification verification expert. Return only valid JSON."
            )
            
            return assessment
            
        except Exception as e:
            logger.error(f"Authenticity check failed for {company_name}: {e}")
            return {
                "certification_score": 0.0,
                "bis_license_found": False,
                "bis_license_number": "",
                "verified_certifications": [],
                "unverified_claims": self_reported_certs,
                "trust_indicators": [],
                "red_flags": [f"Authenticity verification failed: {str(e)}"],
                "summary": f"Unable to verify authenticity for {company_name}: {str(e)}"
            }
