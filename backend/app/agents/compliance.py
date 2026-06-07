# ============================================================
# VendorScout Pro - Compliance Verification Agent (V1.2)
# ============================================================
# Verifies vendor certifications and regulatory compliance by:
# 1. Searching for certification evidence on vendor websites
# 2. Cross-referencing with certification body databases
# 3. Checking industry-specific regulatory requirements
#
# Uses the browser agent to navigate certification registries and vendor
# compliance pages for real verification (not just self-claimed).
#
# V1.2: Multi-phase goal prompts for deeper cert extraction.
# ============================================================

import asyncio
import json
import logging
from typing import Optional

from app.agents.base import BaseAgent
from app.tools.json_parser import parse_json_robust

logger = logging.getLogger(__name__)

# Multi-phase the browser agent prompt for finding certification evidence (V1.2)
# Inspired by cookbook patterns — PHASE_1 navigates, PHASE_2 extracts deeply
CERT_CHECK_PROMPT = """You are a compliance auditor checking this company's certifications.

PHASE_1 - NAVIGATE TO COMPLIANCE INFO:
- Look for "Certifications", "Quality", "Compliance", "About", or "Trust" pages
- Check the footer for certification logos or badges
- Look for ISO, SOC 2, GDPR, HIPAA, CE, UL, FDA mentions anywhere

PHASE_2 - EXTRACT CERTIFICATION DETAILS:
- For each certification found, extract: name, issuer, certificate number, validity dates
- Note whether evidence is a logo only, text claim, or actual certificate document
- Check for quality management (ISO 9001, ISO 14001)
- Check for security compliance (ISO 27001, SOC 2, GDPR, HIPAA)
- Check for safety certifications (CE, UL, FDA)
- Check for industry-specific accreditations

Return ONLY valid JSON:
{{ "certifications": [{{ "name": "", "issuer": "", "number": "", "valid_until": "", "evidence_type": "logo|text_claim|document" }}], "compliance_pages_found": [], "awards": [] }}"""

# LLM prompt to assess compliance status
COMPLIANCE_ASSESSMENT_PROMPT = """Assess the compliance status of this vendor based on scraped data.

Vendor: {company_name}
Website: {website}
Required Certifications: {required_certs}

Scraped Compliance Data:
{scraped_data}

Vendor Profile Data:
- Self-reported certifications: {self_reported_certs}

Return ONLY valid JSON:
{{
    "verified_certifications": ["list of certifications found with evidence"],
    "unverified_claims": ["certifications claimed but not verified"],
    "missing_required": ["required certifications not found"],
    "compliance_score": 0.0 to 1.0,
    "compliance_summary": "2-3 sentence summary",
    "risks": ["compliance-related risks identified"],
    "evidence_urls": ["URLs where certification evidence was found"]
}}"""


class ComplianceAgent(BaseAgent):
    """
    Verifies vendor certifications and regulatory compliance.
    
    For each vendor discovered by ResearchAgent:
    1. Navigates vendor website via the browser agent to find cert pages
    2. Cross-references with known certification databases
    3. Produces compliance score and risk assessment
    """
    
    name = "compliance"
    description = "Compliance Verification"
    
    async def execute(self, state: dict, job_id: str) -> dict:
        """
        Verify compliance for all discovered vendors.
        
        State input: {"vendors": [...], "parsed_requirements": {...}}
        State output: {"compliance_data": {vendor_url: compliance_assessment}}
        """
        vendors = state.get("vendors", [])
        requirements = state.get("parsed_requirements", {})
        required_certs = requirements.get("certifications_required", [])
        
        if not vendors:
            await self.log_activity(job_id, "running", "No vendors to verify compliance for")
            return {"compliance_data": {}}
        
        await self.log_activity(
            job_id, "running",
            f"Verifying compliance for {len(vendors)} vendors, "
            f"checking for: {', '.join(required_certs) if required_certs else 'general certifications'}"
        )
        
        compliance_data = {}
        
        # Process vendors sequentially to avoid overwhelming the target site
        # (compliance checks are deeper than initial scraping)
        for i, vendor in enumerate(vendors):
            company_name = vendor.get("company_name", "Unknown")
            website = vendor.get("website", "")
            
            await self.log_activity(
                job_id, "running",
                f"Checking compliance [{i+1}/{len(vendors)}]: {company_name}"
            )
            
            assessment = await self._check_vendor_compliance(
                vendor, required_certs, job_id
            )
            
            if assessment:
                compliance_data[website] = assessment
            
            # Brief pause between vendors
            await asyncio.sleep(0.2)
        
        # Calculate summary stats
        verified_count = sum(
            1 for c in compliance_data.values()
            if c.get("compliance_score", 0) > 0.7
        )
        
        await self.log_activity(
            job_id, "running",
            f"Compliance verification complete: {verified_count}/{len(vendors)} vendors "
            f"meet compliance threshold",
            findings_count=verified_count
        )
        
        return {
            "compliance_data": compliance_data,
            "_findings_count": verified_count
        }
    
    async def _check_vendor_compliance(
        self, vendor: dict, required_certs: list, job_id: str
    ) -> Optional[dict]:
        """
        Check a single vendor's compliance status.
        Uses the browser agent to find certification evidence, then the LLM to assess.
        """
        website = vendor.get("website", "")
        company_name = vendor.get("company_name", "Unknown")
        self_reported_certs = vendor.get("certifications", [])
        
        try:
            # Step 1: Use the browser agent to search for certification info on vendor site
            browser_result = await self.browser.run_task(
                url=website,
                goal=CERT_CHECK_PROMPT
            )
            
            if browser_result.success and browser_result.extracted_data:
                scraped_data = json.dumps(browser_result.extracted_data)
            elif browser_result.raw_text:
                # V1.2: Robust JSON parser for the browser agent output
                parsed = parse_json_robust(browser_result.raw_text)
                scraped_data = json.dumps(parsed) if parsed else browser_result.raw_text
            else:
                scraped_data = "No compliance data found on website."
            
            # Step 2: Use the LLM to assess compliance based on all evidence
            assessment = await self.llm.generate_structured(
                COMPLIANCE_ASSESSMENT_PROMPT.format(
                    company_name=company_name,
                    website=website,
                    required_certs=", ".join(required_certs) if required_certs else "None specified",
                    scraped_data=scraped_data[:2000],
                    self_reported_certs=", ".join(self_reported_certs) if self_reported_certs else "None"
                ),
                system_prompt="You are a regulatory compliance analyst. Return only valid JSON."
            )
            
            return assessment
            
        except Exception as e:
            logger.error(f"Compliance check failed for {company_name}: {e}")
            return {
                "verified_certifications": [],
                "unverified_claims": self_reported_certs,
                "missing_required": required_certs,
                "compliance_score": 0.0,
                "compliance_summary": f"Compliance verification failed: {str(e)}",
                "risks": ["Unable to verify compliance status"]
            }
