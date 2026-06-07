# ============================================================
# VendorScout Pro - Report Generation Agent (V2.0)
# ============================================================
# Final agent in the pipeline. Generates comprehensive
# procurement research reports including:
# - Executive summary
# - Vendor comparison table
# - Individual vendor deep-dives
# - Risk matrix
# - Authenticity verification results (V2.0)
# - Price intelligence (V2.0)
# - Specification coverage (V2.0)
# - Recommendations with justifications
#
# Report data is stored in the database and served to the frontend.
# ============================================================

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from app.agents.base import BaseAgent
from app.config import settings
from app import database as db

logger = logging.getLogger(__name__)

# LLM prompt for generating the executive summary
EXECUTIVE_SUMMARY_PROMPT = """Generate an executive summary for a vendor procurement research report.

Query: "{query}"
Product/Service: {product}
Industry: {industry}

Number of vendors analyzed: {vendor_count}
Top vendor: {top_vendor} (score: {top_score})

Key findings:
{key_findings}

Write a professional executive summary (3-4 paragraphs) covering:
1. What was researched and why
2. Key findings and market overview
3. Top recommendation with justification
4. Notable risks or considerations

Write in professional business English. Be specific with data points.
Return ONLY the summary text, no JSON wrapper."""

# LLM prompt for generating per-vendor summaries
VENDOR_SUMMARY_PROMPT = """Write a concise vendor assessment paragraph for a procurement report.

Vendor: {company_name}
Rank: #{rank} of {total}
Score: {score}/1.0
Website: {website}

Strengths: {strengths}
Weaknesses: {weaknesses}
Recommendation: {recommendation}
Best for: {best_for}

Compliance Score: {compliance_score}
Financial Health: {financial_score}
Risk Level: {risk_level}

Write 2-3 professional sentences summarizing this vendor's suitability.
Return ONLY the text, no JSON."""


class ReportAgent(BaseAgent):
    """
    Generates the final procurement research report.
    
    Takes all analyzed data and produces:
    1. Executive summary (AI-generated)
    2. Structured report data for frontend rendering
    3. Individual vendor summaries
    4. Saves final results to database
    """
    
    name = "report"
    description = "Report Generation"
    
    async def execute(self, state: dict, job_id: str) -> dict:
        """
        Generate comprehensive research report.
        
        State input: All previous agent outputs (rankings, analyses, all raw data)
        State output: {"report": {full report data}}
        """
        rankings = state.get("rankings", [])
        comparison_matrix = state.get("comparison_matrix", {})
        analyses = state.get("analyses", {})
        compliance_data = state.get("compliance_data", {})
        financial_data = state.get("financial_data", {})
        risk_data = state.get("risk_data", {})
        authenticity_data = state.get("authenticity_data", {})
        price_data = state.get("price_data", {})
        specification_data = state.get("specification_data", {})
        requirements = state.get("parsed_requirements", {})
        vendors = state.get("vendors", [])
        query = state.get("query", "")
        
        product = requirements.get("product_or_service", "")
        industry = requirements.get("industry", "General")
        
        await self.log_activity(
            job_id, "running",
            f"Generating comprehensive report for {len(rankings)} ranked vendors"
        )
        
        # ---- Step 1: Generate executive summary ----
        await self.log_activity(job_id, "running", "Writing executive summary...")
        executive_summary = await self._generate_executive_summary(
            query, product, industry, rankings, risk_data
        )
        
        # ---- Step 2: Generate individual vendor summaries ----
        await self.log_activity(job_id, "running", "Writing vendor assessments...")
        vendor_summaries = {}
        for ranking in rankings:
            website = ranking.get("website", "")
            summary = await self._generate_vendor_summary(ranking, len(rankings), risk_data.get(website, {}))
            vendor_summaries[website] = summary
        
        # ---- Step 3: Compile full report ----
        report = {
            "report_id": job_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "product_or_service": product,
            "industry": industry,
            "requirements": requirements,
            "executive_summary": executive_summary,
            "total_vendors_found": state.get("search_results_count", 0),
            "vendors_analyzed": len(rankings),
            "rankings": rankings,
            "comparison_matrix": comparison_matrix,
            "vendor_summaries": vendor_summaries,
            "compliance_overview": self._compile_compliance_overview(compliance_data),
            "risk_overview": self._compile_risk_overview(risk_data),
            "financial_overview": self._compile_financial_overview(financial_data),
            "authenticity_overview": self._compile_authenticity_overview(authenticity_data),
            "price_overview": self._compile_price_overview(price_data),
            "specification_overview": self._compile_specification_overview(specification_data),
            "methodology": {
                "scoring_weights": {
                    "relevance": 0.25,
                    "compliance": 0.20,
                    "financial": 0.20,
                    "risk": 0.15,
                    "reputation": 0.10,
                    "capability": 0.10
                },
                "data_sources": [
                    "Google Search (via SerperDev)" if settings.SERPER_API_KEY else "Live marketplace discovery (Playwright browser agent)",
                    "Self-hosted Playwright browser agent (live navigation + actions)",
                    (f"Azure OpenAI · {settings.AZURE_OPENAI_DEPLOYMENT} (Azure AI Foundry)"
                     if settings.use_azure else f"{settings.LLM_MODEL} (OpenAI-compatible)"),
                ],
                "agents_used": [
                    "Orchestrator", "Research", "Compliance",
                    "Financial", "Risk", "Authenticity",
                    "Price Comparison", "Specification", "Analysis", "Report"
                ]
            }
        }
        
        # ---- Step 4: Save vendor results to database ----
        await self.log_activity(job_id, "running", "Saving results to database...")
        
        for ranking in rankings:
            website = ranking.get("website", "")
            vendor_data = next(
                (v for v in vendors if v.get("website") == website), {}
            )
            
            await db.save_vendor(
                job_id=job_id,
                vendor_data={
                    "company_name": ranking.get("company_name", "Unknown"),
                    "website": website,
                    "description": vendor_data.get("description", ""),
                    "products_services": vendor_data.get("products_services", []),
                    "certifications": vendor_data.get("certifications", []),
                    "match_score": ranking.get("composite_score", 0),
                    "compliance_score": ranking.get("dimension_scores", {}).get("compliance"),
                    "financial_score": ranking.get("dimension_scores", {}).get("financial"),
                    "risk_score": ranking.get("dimension_scores", {}).get("risk"),
                    "risk_level": ranking.get("recommendation", "unknown"),
                    "strengths": ranking.get("strengths", []),
                    "weaknesses": ranking.get("weaknesses", []),
                    "compliance_data": compliance_data.get(website, {}),
                    "financial_data": financial_data.get(website, {}),
                    "risk_data": risk_data.get(website, {}),
                    "authenticity_data": authenticity_data.get(website, {}),
                    "price_data": price_data.get(website, {}),
                    "specification_data": specification_data.get(website, {}),
                    "raw_profile": {
                        "rank": ranking.get("rank", 0),
                        "recommendation": ranking.get("recommendation", "consider"),
                        "dimension_scores": ranking.get("dimension_scores", {}),
                    }
                }
            )
        
        # Update job status to completed with report data stored in schema columns
        top_recommendations = []
        for r in rankings[:3]:
            top_recommendations.append(
                f"#{r.get('rank', '?')} {r.get('company_name', 'Unknown')} - {r.get('recommendation', 'N/A')}"
            )
        
        await db.update_job_status(
            job_id,
            "completed",
            progress=100,
            total_vendors_found=report.get("total_vendors_found", 0),
            total_vendors_verified=report.get("vendors_analyzed", 0),
            executive_summary=report.get("executive_summary", ""),
            recommendations=json.dumps(top_recommendations),
            comparison_matrix=json.dumps(report.get("comparison_matrix", {})),
        )
        
        await self.log_activity(
            job_id, "running",
            f"Report generated: {len(rankings)} vendors ranked, "
            f"top pick: {rankings[0]['company_name'] if rankings else 'N/A'}",
            findings_count=len(rankings)
        )
        
        return {
            "report": report,
            "_findings_count": len(rankings)
        }
    
    async def _generate_executive_summary(
        self, query: str, product: str, industry: str,
        rankings: list, risk_data: dict
    ) -> str:
        """Generate AI-written executive summary for the report."""
        try:
            # Compile key findings for the prompt
            key_findings_parts = []
            
            for r in rankings[:3]:  # Top 3 vendors
                key_findings_parts.append(
                    f"- {r['company_name']} (Rank #{r['rank']}, Score: {r['composite_score']:.2f}): "
                    f"{r.get('recommendation', 'N/A')} - {r.get('recommendation_reason', '')}"
                )
            
            # Add risk highlights
            high_risk_count = sum(
                1 for rd in risk_data.values()
                if rd.get("risk_level") in ("high", "critical")
            )
            if high_risk_count:
                key_findings_parts.append(f"- {high_risk_count} vendor(s) flagged as high risk")
            
            key_findings = "\n".join(key_findings_parts)
            
            top_vendor = rankings[0]["company_name"] if rankings else "N/A"
            top_score = f"{rankings[0]['composite_score']:.2f}" if rankings else "N/A"
            
            summary = await self.llm.generate_text(
                EXECUTIVE_SUMMARY_PROMPT.format(
                    query=query,
                    product=product,
                    industry=industry,
                    vendor_count=len(rankings),
                    top_vendor=top_vendor,
                    top_score=top_score,
                    key_findings=key_findings
                ),
                system_prompt="You are a senior procurement consultant writing an executive report."
            )
            
            return summary or "Executive summary generation failed. Please review vendor rankings below."
            
        except Exception as e:
            logger.error(f"Executive summary generation failed: {e}")
            return f"Report covers {len(rankings)} vendors for '{product}' in {industry} industry."
    
    async def _generate_vendor_summary(
        self, ranking: dict, total: int, risk: dict
    ) -> str:
        """Generate a brief vendor assessment paragraph."""
        try:
            summary = await self.llm.generate_text(
                VENDOR_SUMMARY_PROMPT.format(
                    company_name=ranking.get("company_name", "Unknown"),
                    rank=ranking.get("rank", "?"),
                    total=total,
                    score=f"{ranking.get('composite_score', 0):.2f}",
                    website=ranking.get("website", ""),
                    strengths=", ".join(ranking.get("strengths", ["None identified"])),
                    weaknesses=", ".join(ranking.get("weaknesses", ["None identified"])),
                    recommendation=ranking.get("recommendation", "consider"),
                    best_for=ranking.get("best_for", "General use"),
                    compliance_score=f"{ranking.get('dimension_scores', {}).get('compliance', 0):.2f}",
                    financial_score=f"{ranking.get('dimension_scores', {}).get('financial', 0):.2f}",
                    risk_level=risk.get("risk_level", "unknown")
                ),
                system_prompt="You are a procurement analyst. Write concise vendor assessments."
            )
            return summary or f"{ranking.get('company_name', 'Unknown')} ranked #{ranking.get('rank', '?')}."
        except Exception as e:
            return f"{ranking.get('company_name', 'Unknown')} ranked #{ranking.get('rank', '?')}."
    
    def _compile_compliance_overview(self, compliance_data: dict) -> dict:
        """Compile compliance stats across all vendors."""
        if not compliance_data:
            return {"total_checked": 0}
        
        scores = [c.get("compliance_score", 0) for c in compliance_data.values()]
        return {
            "total_checked": len(compliance_data),
            "average_score": round(sum(scores) / len(scores), 3) if scores else 0,
            "fully_compliant": sum(1 for s in scores if s >= 0.8),
            "partially_compliant": sum(1 for s in scores if 0.4 <= s < 0.8),
            "non_compliant": sum(1 for s in scores if s < 0.4),
        }
    
    def _compile_risk_overview(self, risk_data: dict) -> dict:
        """Compile risk stats across all vendors."""
        if not risk_data:
            return {"total_assessed": 0}
        
        levels = [r.get("risk_level", "unknown") for r in risk_data.values()]
        return {
            "total_assessed": len(risk_data),
            "low_risk": levels.count("low"),
            "medium_risk": levels.count("medium"),
            "high_risk": levels.count("high"),
            "critical_risk": levels.count("critical"),
        }
    
    def _compile_financial_overview(self, financial_data: dict) -> dict:
        """Compile financial health stats across all vendors."""
        if not financial_data:
            return {"total_assessed": 0}
        
        scores = [f.get("financial_health_score", 0) for f in financial_data.values()]
        return {
            "total_assessed": len(financial_data),
            "average_health_score": round(sum(scores) / len(scores), 3) if scores else 0,
            "strong": sum(1 for s in scores if s >= 0.7),
            "moderate": sum(1 for s in scores if 0.4 <= s < 0.7),
            "weak": sum(1 for s in scores if s < 0.4),
        }
    
    def _compile_authenticity_overview(self, authenticity_data: dict) -> dict:
        """Compile authenticity verification stats across all vendors."""
        if not authenticity_data:
            return {"total_checked": 0}
        
        scores = [a.get("certification_score", 0) for a in authenticity_data.values()]
        bis_found = sum(1 for a in authenticity_data.values() if a.get("bis_license_found"))
        return {
            "total_checked": len(authenticity_data),
            "average_trust_score": round(sum(scores) / len(scores), 3) if scores else 0,
            "high_trust": sum(1 for s in scores if s >= 0.7),
            "moderate_trust": sum(1 for s in scores if 0.4 <= s < 0.7),
            "low_trust": sum(1 for s in scores if s < 0.4),
            "bis_licenses_found": bis_found,
        }
    
    def _compile_price_overview(self, price_data: dict) -> dict:
        """Compile pricing intelligence stats across all vendors."""
        if not price_data:
            return {"total_analyzed": 0}
        
        indices = [p.get("price_index", 100) for p in price_data.values() if p.get("price_index")]
        competitiveness = [p.get("price_competitiveness", "unknown") for p in price_data.values()]
        return {
            "total_analyzed": len(price_data),
            "average_price_index": round(sum(indices) / len(indices), 1) if indices else 100.0,
            "very_competitive": competitiveness.count("very_competitive"),
            "competitive": competitiveness.count("competitive"),
            "average": competitiveness.count("average"),
            "premium": competitiveness.count("premium"),
        }
    
    def _compile_specification_overview(self, specification_data: dict) -> dict:
        """Compile specification coverage stats across all vendors."""
        if not specification_data:
            return {"total_analyzed": 0}
        
        scores = [s.get("completeness_score", 0) for s in specification_data.values()]
        return {
            "total_analyzed": len(specification_data),
            "average_completeness": round(sum(scores) / len(scores), 3) if scores else 0,
            "well_documented": sum(1 for s in scores if s >= 0.7),
            "partially_documented": sum(1 for s in scores if 0.3 <= s < 0.7),
            "poorly_documented": sum(1 for s in scores if s < 0.3),
        }
