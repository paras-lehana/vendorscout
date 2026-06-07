# ============================================================
# VendorScout Pro - Seed Data Script
# ============================================================
# Pre-populates the database with demo research results.
# This gives the hackathon judges something to see immediately
# without waiting for real API calls.
#
# Creates 3 completed research jobs matching the example queries
# on the landing page, each with 5-8 vendor results.
#
# Usage:
#   python -m app.seed.demo_data
#   (run from the backend/ directory)
# ============================================================

import asyncio
import json
import uuid
from datetime import datetime

# Add parent to path so we can import app modules
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import database as db


def _score_to_risk_level(risk_score: float) -> str:
    """Convert numeric risk score to categorical risk level."""
    if risk_score <= 15:
        return "low"
    elif risk_score <= 30:
        return "medium"
    elif risk_score <= 50:
        return "high"
    return "critical"


# --- Demo Job 1: Lithium Battery Suppliers ---
DEMO_JOB_1 = {
    "id": "demo-lithium-battery-001",
    "query": "Find lithium battery suppliers in Southeast Asia with ISO 9001 certification, minimum 10,000 units/month capacity, and established export history to North America",
    "status": "completed",
    "vendors": [
        {
            "name": "Thai Battery Innovation Co., Ltd",
            "website": "https://thaibattery.co.th",
            "location": "Bangkok, Thailand",
            "overall_score": 87.5,
            "relevance_score": 92,
            "compliance_score": 88,
            "financial_score": 85,
            "risk_score": 15,
            "reputation_score": 84,
            "capability_score": 90,
            "certifications": ["ISO 9001:2015", "ISO 14001", "UL 2054"],
            "strengths": ["Large production capacity (50K units/month)", "Established US export channel", "Modern automated production lines"],
            "weaknesses": ["Higher pricing than competitors", "Limited EV-grade battery experience"],
            "recommendation": "preferred",
            "summary": "Leading Thai lithium battery manufacturer with strong quality systems and proven North American export experience."
        },
        {
            "name": "VietPower Energy JSC",
            "website": "https://vietpower.vn",
            "location": "Ho Chi Minh City, Vietnam",
            "overall_score": 82.3,
            "relevance_score": 88,
            "compliance_score": 85,
            "financial_score": 78,
            "risk_score": 22,
            "reputation_score": 80,
            "capability_score": 82,
            "certifications": ["ISO 9001:2015", "IEC 62133", "UN38.3"],
            "strengths": ["Competitive pricing", "Rapidly growing capacity", "Strong R&D team"],
            "weaknesses": ["Newer to NA export market", "Some quality consistency reports"],
            "recommendation": "recommended",
            "summary": "Fast-growing Vietnamese battery manufacturer offering competitive pricing with solid technical capabilities."
        },
        {
            "name": "Indo Battery Teknologi PT",
            "website": "https://indobattery.co.id",
            "location": "Jakarta, Indonesia",
            "overall_score": 78.1,
            "relevance_score": 80,
            "compliance_score": 82,
            "financial_score": 72,
            "risk_score": 28,
            "reputation_score": 76,
            "capability_score": 78,
            "certifications": ["ISO 9001:2015", "SNI (Indonesian National Standard)"],
            "strengths": ["Government-backed expansion", "Access to nickel supply chain", "Low labor costs"],
            "weaknesses": ["Limited international certifications", "Logistics challenges"],
            "recommendation": "conditional",
            "summary": "Indonesian manufacturer with strong government support and raw material access, but needs more international certifications."
        },
        {
            "name": "PhilCell Energy Corp",
            "website": "https://philcellenergy.ph",
            "location": "Manila, Philippines",
            "overall_score": 74.6,
            "relevance_score": 76,
            "compliance_score": 75,
            "financial_score": 70,
            "risk_score": 30,
            "reputation_score": 74,
            "capability_score": 76,
            "certifications": ["ISO 9001:2015", "PNS (Philippine National Standard)"],
            "strengths": ["English-speaking workforce", "US trade agreement advantages", "Flexible MOQ"],
            "weaknesses": ["Smaller capacity (15K units/month)", "Limited automation"],
            "recommendation": "conditional",
            "summary": "Philippine manufacturer with trade advantages for US market but limited production scale."
        },
        {
            "name": "SG PowerTech Pte Ltd",
            "website": "https://sgpowertech.sg",
            "location": "Singapore",
            "overall_score": 91.2,
            "relevance_score": 85,
            "compliance_score": 95,
            "financial_score": 92,
            "risk_score": 8,
            "reputation_score": 93,
            "capability_score": 88,
            "certifications": ["ISO 9001:2015", "ISO 14001", "UL 2054", "IEC 62133", "IATF 16949"],
            "strengths": ["Best-in-class compliance", "Strong financials", "Premium quality", "Excellent IP protection"],
            "weaknesses": ["Premium pricing (20-30% above regional avg)", "Smaller manufacturing floor"],
            "recommendation": "preferred",
            "summary": "Singapore-based premium battery manufacturer with exceptional quality systems and compliance, ideal for high-value applications."
        }
    ],
    "report": {
        "executive_summary": "Analysis identified 5 qualified lithium battery suppliers across Southeast Asia. SG PowerTech Pte Ltd (Singapore) leads in quality and compliance, while Thai Battery Innovation offers the best balance of capacity and reliability. All candidates hold ISO 9001 certification as required.",
        "total_vendors_analyzed": 12,
        "qualified_vendors": 5,
        "avg_score": 82.7,
        "top_recommendation": "SG PowerTech Pte Ltd for premium applications; Thai Battery Innovation Co. for high-volume standard batteries",
        "risk_summary": "Overall supply chain risk is moderate. Singapore and Thailand offer the most stable regulatory environments. Vietnam shows growth potential but with higher variability.",
        "compliance_overview": "4 of 5 vendors hold ISO 9001:2015. SG PowerTech leads with 5 certifications including automotive-grade IATF 16949. Indo Battery Teknologi needs additional international certifications.",
        "financial_overview": "Combined capacity exceeds 100K units/month. SG PowerTech shows strongest financial health with SGD 45M revenue. VietPower growing at 40% YoY.",
        "methodology": "Multi-criteria decision analysis across 6 dimensions: Relevance (25%), Compliance (20%), Financial Health (20%), Risk (15%), Reputation (10%), Capability (10%)"
    }
}


# --- Demo Job 2: Medical Device Packaging ---
DEMO_JOB_2 = {
    "id": "demo-medical-packaging-002",
    "query": "Evaluate medical device packaging suppliers in Germany and Switzerland with FDA 21 CFR compliance and cleanroom manufacturing capabilities",
    "status": "completed",
    "vendors": [
        {
            "name": "MedPack GmbH",
            "website": "https://medpack.de",
            "location": "Munich, Germany",
            "overall_score": 93.4,
            "relevance_score": 95,
            "compliance_score": 96,
            "financial_score": 90,
            "risk_score": 7,
            "reputation_score": 92,
            "capability_score": 94,
            "certifications": ["ISO 13485:2016", "FDA 21 CFR Part 820", "ISO 14644-1 Class 7", "EU MDR"],
            "strengths": ["Full FDA compliance history", "Class 7 cleanroom", "20+ years medical device experience", "In-house sterilization"],
            "weaknesses": ["Long lead times (8-12 weeks)", "Premium European pricing"],
            "recommendation": "preferred",
            "summary": "Premier German medical device packaging company with comprehensive FDA compliance and advanced cleanroom manufacturing."
        },
        {
            "name": "SwissMedTech Packaging AG",
            "website": "https://swissmedtech-pkg.ch",
            "location": "Zurich, Switzerland",
            "overall_score": 91.8,
            "relevance_score": 93,
            "compliance_score": 94,
            "financial_score": 88,
            "risk_score": 9,
            "reputation_score": 94,
            "capability_score": 90,
            "certifications": ["ISO 13485:2016", "FDA 21 CFR Part 820", "ISO 14644-1 Class 5", "EU MDR", "Swissmedic"],
            "strengths": ["Class 5 cleanroom (highest grade)", "Swiss quality reputation", "Validation documentation expertise"],
            "weaknesses": ["Highest pricing in evaluation", "Limited capacity for large orders"],
            "recommendation": "preferred",
            "summary": "Swiss precision packaging with Class 5 cleanroom - ideal for high-risk medical devices requiring top-tier quality."
        },
        {
            "name": "Berlin Pharma Pack GmbH",
            "website": "https://berlinpharmapack.de",
            "location": "Berlin, Germany",
            "overall_score": 84.2,
            "relevance_score": 86,
            "compliance_score": 88,
            "financial_score": 80,
            "risk_score": 18,
            "reputation_score": 82,
            "capability_score": 84,
            "certifications": ["ISO 13485:2016", "FDA 21 CFR Part 820", "ISO 14644-1 Class 7"],
            "strengths": ["Competitive pricing for EU manufacturer", "Fast prototyping", "Good logistics network"],
            "weaknesses": ["Newer FDA registration", "Smaller cleanroom capacity"],
            "recommendation": "recommended",
            "summary": "Cost-effective German option with solid compliance and rapid prototyping capabilities."
        },
        {
            "name": "Alpine Medical Solutions AG",
            "website": "https://alpinemedical.ch",
            "location": "Basel, Switzerland",
            "overall_score": 88.9,
            "relevance_score": 90,
            "compliance_score": 91,
            "financial_score": 86,
            "risk_score": 12,
            "reputation_score": 88,
            "capability_score": 89,
            "certifications": ["ISO 13485:2016", "FDA 21 CFR Part 820", "ISO 14644-1 Class 7", "ISO 11607"],
            "strengths": ["Sterile barrier system expertise", "FDA audit-ready documentation", "Strong pharma industry connections"],
            "weaknesses": ["Limited to blister and tray packaging", "No flexible packaging capability"],
            "recommendation": "recommended",
            "summary": "Specialized Swiss manufacturer excelling in sterile barrier packaging systems with strong regulatory documentation."
        },
        {
            "name": "Rhein Medizintechnik GmbH",
            "website": "https://rheinmedtech.de",
            "location": "Düsseldorf, Germany",
            "overall_score": 79.5,
            "relevance_score": 82,
            "compliance_score": 80,
            "financial_score": 76,
            "risk_score": 24,
            "reputation_score": 78,
            "capability_score": 80,
            "certifications": ["ISO 13485:2016", "ISO 14644-1 Class 8"],
            "strengths": ["Most competitive pricing", "Large capacity", "Fast turnaround"],
            "weaknesses": ["No direct FDA registration (pending)", "Class 8 cleanroom only"],
            "recommendation": "conditional",
            "summary": "Budget-friendly German manufacturer with large capacity but needs FDA registration completion for full qualification."
        }
    ],
    "report": {
        "executive_summary": "5 medical device packaging suppliers evaluated across Germany and Switzerland. MedPack GmbH and SwissMedTech Packaging AG are top recommendations with full FDA 21 CFR compliance and advanced cleanroom capabilities.",
        "total_vendors_analyzed": 9,
        "qualified_vendors": 5,
        "avg_score": 87.6,
        "top_recommendation": "MedPack GmbH for standard medical devices; SwissMedTech Packaging AG for high-risk devices requiring Class 5 cleanroom",
        "risk_summary": "Very low supply chain risk across all candidates. German and Swiss regulatory frameworks provide excellent compliance infrastructure.",
        "compliance_overview": "4 of 5 vendors have active FDA 21 CFR Part 820 registration. Rhein Medizintechnik's FDA application is pending. All hold ISO 13485:2016.",
        "financial_overview": "All vendors show stable financials with MedPack GmbH leading at EUR 120M revenue. Pricing ranges from EUR 0.15-0.85 per unit depending on complexity.",
        "methodology": "Multi-criteria decision analysis across 6 dimensions: Relevance (25%), Compliance (20%), Financial Health (20%), Risk (15%), Reputation (10%), Capability (10%)"
    }
}


# --- Demo Job 3: Sustainable Textile Suppliers ---
DEMO_JOB_3 = {
    "id": "demo-sustainable-textile-003",
    "query": "Source sustainable textile suppliers in India with GOTS certification, organic cotton capabilities, and minimum order quantity under 500 units",
    "status": "completed",
    "vendors": [
        {
            "name": "EcoWeave Textiles Pvt Ltd",
            "website": "https://ecoweave.in",
            "location": "Coimbatore, Tamil Nadu, India",
            "overall_score": 89.7,
            "relevance_score": 94,
            "compliance_score": 90,
            "financial_score": 84,
            "risk_score": 14,
            "reputation_score": 88,
            "capability_score": 92,
            "certifications": ["GOTS 7.0", "OEKO-TEX Standard 100", "Fair Trade", "BCI (Better Cotton Initiative)"],
            "strengths": ["Vertically integrated (spinning to finishing)", "MOQ as low as 200 units", "Strong sustainability track record", "Own organic cotton farms"],
            "weaknesses": ["Higher pricing than conventional suppliers", "Limited synthetic blend capability"],
            "recommendation": "preferred",
            "summary": "Leading Indian sustainable textile manufacturer with full vertical integration and GOTS certification. Ideal for brands prioritizing authenticity."
        },
        {
            "name": "GreenThread Industries",
            "website": "https://greenthread.co.in",
            "location": "Tirupur, Tamil Nadu, India",
            "overall_score": 85.3,
            "relevance_score": 90,
            "compliance_score": 86,
            "financial_score": 82,
            "risk_score": 18,
            "reputation_score": 84,
            "capability_score": 86,
            "certifications": ["GOTS 7.0", "OEKO-TEX Standard 100", "SA8000"],
            "strengths": ["Tirupur textile cluster advantages", "200+ export clients", "MOQ from 300 units", "Quick turnaround"],
            "weaknesses": ["Relies on third-party organic cotton", "Limited in-house design capability"],
            "recommendation": "recommended",
            "summary": "Well-established Tirupur-based manufacturer with strong export network and competitive pricing on sustainable textiles."
        },
        {
            "name": "Jaipur Organic Fabrics LLP",
            "website": "https://jaipurorganic.com",
            "location": "Jaipur, Rajasthan, India",
            "overall_score": 81.2,
            "relevance_score": 86,
            "compliance_score": 82,
            "financial_score": 76,
            "risk_score": 22,
            "reputation_score": 82,
            "capability_score": 80,
            "certifications": ["GOTS 7.0", "Fair Trade", "Craftmark"],
            "strengths": ["Artisanal block-printing expertise", "Hand-crafted premium products", "MOQ from 100 units", "Cultural heritage value"],
            "weaknesses": ["Limited capacity for large orders", "Longer lead times for handcrafted items"],
            "recommendation": "recommended",
            "summary": "Artisanal Rajasthani textile producer specializing in hand-block printed organic fabrics with very low MOQ."
        },
        {
            "name": "Mumbai Sustainable Garments",
            "website": "https://mumbaisustainable.com",
            "location": "Mumbai, Maharashtra, India",
            "overall_score": 77.8,
            "relevance_score": 80,
            "compliance_score": 78,
            "financial_score": 74,
            "risk_score": 26,
            "reputation_score": 76,
            "capability_score": 78,
            "certifications": ["GOTS 7.0", "ISO 9001"],
            "strengths": ["Port city logistics advantage", "Full garment manufacturing", "MOQ from 250 units"],
            "weaknesses": ["Newer GOTS certification", "Some worker safety reports", "Less established brand"],
            "recommendation": "conditional",
            "summary": "Mumbai-based manufacturer with logistics advantages and full garment capability, but newer to sustainable space."
        },
        {
            "name": "Kolkata Eco Textiles",
            "website": "https://kolkataeco.in",
            "location": "Kolkata, West Bengal, India",
            "overall_score": 73.4,
            "relevance_score": 76,
            "compliance_score": 74,
            "financial_score": 68,
            "risk_score": 32,
            "reputation_score": 72,
            "capability_score": 74,
            "certifications": ["GOTS 6.0 (upgrading to 7.0)", "OEKO-TEX Standard 100"],
            "strengths": ["Jute and hemp expertise", "Lowest pricing", "MOQ from 150 units", "Government subsidy support"],
            "weaknesses": ["GOTS version behind latest", "Quality consistency varies", "Limited cotton expertise"],
            "recommendation": "conditional",
            "summary": "Eastern Indian manufacturer with unique jute/hemp capabilities and very competitive pricing, best for eco-conscious niche products."
        },
        {
            "name": "Bangalore BioTex Pvt Ltd",
            "website": "https://bangalorebiotex.com",
            "location": "Bangalore, Karnataka, India",
            "overall_score": 83.9,
            "relevance_score": 88,
            "compliance_score": 84,
            "financial_score": 80,
            "risk_score": 20,
            "reputation_score": 83,
            "capability_score": 84,
            "certifications": ["GOTS 7.0", "OEKO-TEX Standard 100", "Bluesign"],
            "strengths": ["Tech-forward approach (IoT-monitored production)", "EU brand partnerships", "MOQ from 200 units", "Innovative dyeing processes"],
            "weaknesses": ["Higher pricing tier", "Newer company (est. 2019)"],
            "recommendation": "recommended",
            "summary": "Tech-savvy Bangalore manufacturer with innovative sustainable dyeing processes and strong EU brand relationships."
        }
    ],
    "report": {
        "executive_summary": "6 sustainable textile suppliers identified across India, all with GOTS certification and sub-500 unit MOQ. EcoWeave Textiles leads with vertical integration and own organic farms. India's textile cluster advantages in Tamil Nadu offer the best combination of sustainability certification and production capability.",
        "total_vendors_analyzed": 15,
        "qualified_vendors": 6,
        "avg_score": 81.9,
        "top_recommendation": "EcoWeave Textiles for premium organic cotton; GreenThread Industries for best price-quality ratio; Jaipur Organic for artisanal/handcrafted products",
        "risk_summary": "Moderate overall risk, primarily around supply consistency during monsoon season and regional infrastructure. Tamil Nadu cluster offers most reliable supply chain.",
        "compliance_overview": "5 of 6 vendors hold current GOTS 7.0 certification. Kolkata Eco Textiles upgrading from 6.0. All meet organic cotton requirements.",
        "financial_overview": "Pricing ranges from $3-15 per unit depending on complexity and handcraft level. EcoWeave and GreenThread show strongest financial stability.",
        "methodology": "Multi-criteria decision analysis across 6 dimensions: Relevance (25%), Compliance (20%), Financial Health (20%), Risk (15%), Reputation (10%), Capability (10%)"
    }
}


async def seed_demo_data():
    """
    Populate the database with demo research results.
    
    Creates 3 completed research jobs with vendor data,
    matching the example queries on the landing page.
    This allows judges to immediately explore results
    without waiting for live API calls.
    """
    print("🌱 Seeding VendorScout Pro demo data...")
    
    # Initialize the database
    await db.init_db()
    
    for demo_job in [DEMO_JOB_1, DEMO_JOB_2, DEMO_JOB_3]:
        job_id = demo_job["id"]
        
        # Check if this demo job already exists
        existing = await db.get_job(job_id)
        if existing:
            print(f"  ⏭️  Skip: {job_id} already exists")
            continue
        
        # Create the job record
        await db.create_job(
            job_id=job_id,
            query=demo_job["query"]
        )
        
        # Store vendor results - transform keys to match DB schema
        for vendor in demo_job["vendors"]:
            # Map seed data field names to database column names
            db_vendor = {
                "company_name": vendor.get("name", "Unknown"),
                "website": vendor.get("website", ""),
                "description": vendor.get("summary", ""),
                "location": vendor.get("location", ""),
                "certifications": vendor.get("certifications", []),
                "match_score": vendor.get("overall_score", 0.0),
                "compliance_score": vendor.get("compliance_score"),
                "financial_score": vendor.get("financial_score"),
                "risk_score": vendor.get("risk_score"),
                "risk_level": _score_to_risk_level(vendor.get("risk_score", 50)),
                "strengths": vendor.get("strengths", []),
                "weaknesses": vendor.get("weaknesses", []),
                "raw_profile": {
                    "relevance_score": vendor.get("relevance_score"),
                    "reputation_score": vendor.get("reputation_score"),
                    "capability_score": vendor.get("capability_score"),
                    "recommendation": vendor.get("recommendation"),
                }
            }
            await db.save_vendor(
                job_id=job_id,
                vendor_data=db_vendor
            )
        
        # Update job status with report data
        report = demo_job["report"]
        await db.update_job_status(
            job_id=job_id,
            status="completed",
            progress=100,
            total_vendors_found=report.get("total_vendors_analyzed", 0),
            total_vendors_verified=report.get("qualified_vendors", 0),
            executive_summary=report.get("executive_summary", ""),
            recommendations=json.dumps([report.get("top_recommendation", "")]),
            comparison_matrix=json.dumps(report),
            duration_seconds=45.2,  # Simulated duration
        )
        
        # Create agent activity logs for realistic timeline
        agents_sequence = [
            ("orchestrator", "Parsed query into structured requirements"),
            ("research", f"Found {len(demo_job['vendors'])} qualified vendors"),
            ("compliance", "Verified certifications and standards"),
            ("financial", "Assessed financial health and stability"),
            ("risk", "Evaluated supply chain and operational risks"),
            ("analysis", "Scored and ranked all vendors"),
            ("report", "Generated comprehensive research report"),
        ]
        for agent_name, message in agents_sequence:
            await db.log_agent_activity(
                job_id=job_id,
                agent_name=agent_name,
                status="completed",
                message=message,
                findings_count=len(demo_job["vendors"]) if agent_name == "research" else None
            )
        
        print(f"  ✅ Created: {job_id} ({len(demo_job['vendors'])} vendors)")
    
    print("🌱 Demo data seeding complete!")


if __name__ == "__main__":
    asyncio.run(seed_demo_data())
