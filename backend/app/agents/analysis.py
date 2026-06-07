# ============================================================
# VendorScout Pro - Comparative Analysis Agent (V2.0)
# ============================================================
# Performs Multi-Criteria Decision Analysis (MCDA) scoring
# on all vendors using data from all assessment agents:
# Core: compliance, financial, risk
# Extended (V2.0): authenticity, price, specification
#
# Produces:
# - Weighted composite scores for each vendor
# - Rankings with justifications
# - Strengths/weaknesses for each vendor
# - Side-by-side comparison matrix
#
# This agent runs AFTER all assessment agents have completed.
# ============================================================

import logging
from typing import Optional

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)

# Weights for MCDA scoring - how much each dimension matters
# These weights reflect typical B2B procurement priorities
# V2.0: Added authenticity, price, and specification dimensions
DEFAULT_WEIGHTS = {
    "relevance": 0.20,      # How well vendor matches requirements
    "compliance": 0.15,     # Certification and regulatory compliance
    "financial": 0.15,      # Financial health and stability
    "risk": 0.10,           # Inverse of risk score (lower risk = better)
    "reputation": 0.08,     # Online reputation and reviews
    "capability": 0.07,     # Product/service capability breadth
    "authenticity": 0.10,   # V2.0: Certification authenticity and trust signals
    "price": 0.08,          # V2.0: Price competitiveness vs market
    "specification": 0.07,  # V2.0: Spec documentation completeness
}

# LLM prompt for generating vendor-by-vendor analysis
VENDOR_ANALYSIS_PROMPT = """Analyze this vendor as a potential procurement partner.

Vendor: {company_name}
Website: {website}
Product Requirements: {product}

Vendor Profile:
{vendor_data}

Compliance Data:
{compliance_data}

Financial Data:
{financial_data}

Risk Data:
{risk_data}

Authenticity Data:
{authenticity_data}

Price Data:
{price_data}

Specification Data:
{specification_data}

Generate a comprehensive vendor analysis. Return ONLY valid JSON:
{{
    "strengths": ["3-5 key strengths of this vendor"],
    "weaknesses": ["2-4 areas of concern or weakness"],
    "unique_selling_points": ["what makes this vendor stand out"],
    "best_for": "ideal use case for this vendor (1 sentence)",
    "concerns": "primary concern about this vendor (1 sentence)",
    "recommendation": "recommended" | "consider" | "caution" | "avoid",
    "recommendation_reason": "1-2 sentence justification for recommendation"
}}"""


class AnalysisAgent(BaseAgent):
    """
    Multi-Criteria Decision Analysis (MCDA) scoring and ranking.
    
    Takes outputs from all previous agents and produces:
    1. Weighted composite scores per vendor
    2. Ranked vendor list with justifications
    3. Per-vendor strengths/weaknesses analysis
    4. Comparison matrix for side-by-side evaluation
    """
    
    name = "analysis"
    description = "Comparative Analysis & Ranking"
    
    async def execute(self, state: dict, job_id: str) -> dict:
        """
        Score, rank, and analyze all vendors.
        
        State input: All previous agent outputs (vendors, compliance_data, financial_data, risk_data)
        State output: {"rankings": [...], "comparison_matrix": {...}, "analyses": {...}}
        """
        vendors = state.get("vendors", [])
        compliance_data = state.get("compliance_data", {})
        financial_data = state.get("financial_data", {})
        risk_data = state.get("risk_data", {})
        authenticity_data = state.get("authenticity_data", {})
        price_data = state.get("price_data", {})
        specification_data = state.get("specification_data", {})
        requirements = state.get("parsed_requirements", {})
        product = requirements.get("product_or_service", "")
        
        if not vendors:
            await self.log_activity(job_id, "running", "No vendors to analyze")
            return {"rankings": [], "comparison_matrix": {}, "analyses": {}}
        
        await self.log_activity(
            job_id, "running",
            f"Running MCDA analysis across {len(vendors)} vendors with 9 scoring dimensions"
        )
        
        # ---- Step 1: Calculate composite scores ----
        scored_vendors = []
        for vendor in vendors:
            website = vendor.get("website", "")
            scores = self._calculate_scores(
                vendor,
                compliance_data.get(website, {}),
                financial_data.get(website, {}),
                risk_data.get(website, {}),
                authenticity_data.get(website, {}),
                price_data.get(website, {}),
                specification_data.get(website, {}),
            )
            scored_vendors.append({
                "vendor": vendor,
                "scores": scores,
                "composite_score": sum(
                    scores[dim] * weight
                    for dim, weight in DEFAULT_WEIGHTS.items()
                )
            })
        
        # Sort by composite score (highest first)
        scored_vendors.sort(key=lambda x: x["composite_score"], reverse=True)
        
        # ---- Step 2: Generate per-vendor AI analysis ----
        analyses = {}
        for i, sv in enumerate(scored_vendors):
            vendor = sv["vendor"]
            website = vendor.get("website", "")
            company_name = vendor.get("company_name", "Unknown")
            
            await self.log_activity(
                job_id, "running",
                f"Generating analysis [{i+1}/{len(scored_vendors)}]: {company_name} "
                f"(score: {sv['composite_score']:.2f})"
            )
            
            analysis = await self._generate_vendor_analysis(
                vendor, product,
                compliance_data.get(website, {}),
                financial_data.get(website, {}),
                risk_data.get(website, {}),
                authenticity_data.get(website, {}),
                price_data.get(website, {}),
                specification_data.get(website, {}),
            )
            
            if analysis:
                analyses[website] = analysis
        
        # ---- Step 3: Build rankings list ----
        rankings = []
        for rank, sv in enumerate(scored_vendors, 1):
            vendor = sv["vendor"]
            website = vendor.get("website", "")
            vendor_analysis = analyses.get(website, {})
            
            rankings.append({
                "rank": rank,
                "company_name": vendor.get("company_name", "Unknown"),
                "website": website,
                "composite_score": round(sv["composite_score"], 3),
                "dimension_scores": {k: round(v, 3) for k, v in sv["scores"].items()},
                "recommendation": vendor_analysis.get("recommendation", "consider"),
                "recommendation_reason": vendor_analysis.get("recommendation_reason", ""),
                "strengths": vendor_analysis.get("strengths", []),
                "weaknesses": vendor_analysis.get("weaknesses", []),
                "best_for": vendor_analysis.get("best_for", ""),
            })
        
        # ---- Step 4: Build comparison matrix ----
        comparison_matrix = self._build_comparison_matrix(scored_vendors)
        
        await self.log_activity(
            job_id, "running",
            f"Analysis complete. Top vendor: {rankings[0]['company_name']} "
            f"(score: {rankings[0]['composite_score']})" if rankings else "No rankings produced",
            findings_count=len(rankings)
        )
        
        return {
            "rankings": rankings,
            "comparison_matrix": comparison_matrix,
            "analyses": analyses,
            "_findings_count": len(rankings)
        }
    
    def _calculate_scores(
        self, vendor: dict, compliance: dict,
        financial: dict, risk: dict,
        authenticity: dict = None, price: dict = None,
        specification: dict = None,
    ) -> dict:
        """
        Calculate individual dimension scores (0.0 to 1.0) for MCDA.
        
        Each dimension extracts a normalized score from the agent data.
        V2.0: Added authenticity, price, and specification dimensions.
        """
        authenticity = authenticity or {}
        price = price or {}
        specification = specification or {}
        
        # Relevance from research agent's scoring
        relevance = float(vendor.get("relevance_score", 0.5))
        
        # Compliance from compliance agent
        compliance_score = float(compliance.get("compliance_score", 0.5))
        
        # Financial from financial agent
        financial_score = float(financial.get("financial_health_score", 0.5))
        
        # Risk - invert so lower risk = higher score
        risk_raw = float(risk.get("overall_risk_score", 0.5))
        risk_score = 1.0 - risk_raw
        
        # Reputation from risk agent
        reputation = float(risk.get("reputation_score", 0.5))
        
        # Capability - based on product/service diversity
        products = vendor.get("products_services", [])
        capability = min(len(products) / 5.0, 1.0) if products else 0.5
        
        # V2.0: Authenticity from certification verification
        auth_score = float(authenticity.get("certification_score", 0.5))
        
        # V2.0: Price competitiveness (lower price_index = more competitive = higher score)
        price_index = float(price.get("price_index", 100.0))
        # Convert: index 50 → score 1.0, index 100 → score 0.5, index 150 → score 0.0
        price_score = max(0.0, min(1.0, 1.0 - (price_index - 50) / 100))
        
        # V2.0: Specification completeness
        spec_score = float(specification.get("completeness_score", 0.5))
        
        return {
            "relevance": max(0.0, min(1.0, relevance)),
            "compliance": max(0.0, min(1.0, compliance_score)),
            "financial": max(0.0, min(1.0, financial_score)),
            "risk": max(0.0, min(1.0, risk_score)),
            "reputation": max(0.0, min(1.0, reputation)),
            "capability": max(0.0, min(1.0, capability)),
            "authenticity": max(0.0, min(1.0, auth_score)),
            "price": max(0.0, min(1.0, price_score)),
            "specification": max(0.0, min(1.0, spec_score)),
        }
    
    async def _generate_vendor_analysis(
        self, vendor: dict, product: str,
        compliance: dict, financial: dict, risk: dict,
        authenticity: dict = None, price: dict = None,
        specification: dict = None,
    ) -> Optional[dict]:
        """Use LLM to generate qualitative vendor analysis with all data dimensions."""
        try:
            import json
            analysis = await self.llm.generate_structured(
                VENDOR_ANALYSIS_PROMPT.format(
                    company_name=vendor.get("company_name", "Unknown"),
                    website=vendor.get("website", ""),
                    product=product,
                    vendor_data=json.dumps(vendor, indent=2, default=str)[:1500],
                    compliance_data=json.dumps(compliance, indent=2, default=str)[:800],
                    financial_data=json.dumps(financial, indent=2, default=str)[:800],
                    risk_data=json.dumps(risk, indent=2, default=str)[:800],
                    authenticity_data=json.dumps(authenticity or {}, indent=2, default=str)[:600],
                    price_data=json.dumps(price or {}, indent=2, default=str)[:600],
                    specification_data=json.dumps(specification or {}, indent=2, default=str)[:600],
                ),
                system_prompt="You are a procurement advisory analyst. Return only valid JSON."
            )
            return analysis
        except Exception as e:
            logger.error(f"Vendor analysis generation failed: {e}")
            return None
    
    def _build_comparison_matrix(self, scored_vendors: list) -> dict:
        """
        Build a comparison matrix for side-by-side vendor evaluation.
        Used by the frontend to render comparison tables.
        """
        dimensions = list(DEFAULT_WEIGHTS.keys())
        
        matrix = {
            "dimensions": dimensions,
            "weights": DEFAULT_WEIGHTS,
            "vendors": []
        }
        
        for sv in scored_vendors:
            vendor = sv["vendor"]
            matrix["vendors"].append({
                "company_name": vendor.get("company_name", "Unknown"),
                "website": vendor.get("website", ""),
                "composite_score": round(sv["composite_score"], 3),
                "scores": {
                    dim: round(sv["scores"].get(dim, 0), 3)
                    for dim in dimensions
                }
            })
        
        return matrix
