# ============================================================
# VendorScout Pro - Pydantic Data Models (Schemas) (V2.0)
# ============================================================
# Defines all request/response models and internal data structures.
# These ensure type safety and automatic validation across the app.
# Models are used by API endpoints, agents, database, and frontend.
#
# V1.3: Added detail_level parameter for tiered research depth.
# V2.0: Added models for Authenticity Verification, Price Comparison,
#        and Specification Corpus features.
# ============================================================

from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field


# ---- API Request Models ----

class SearchRequest(BaseModel):
    """
    User's vendor search request.
    The 'query' field accepts natural language descriptions
    which the Orchestrator Agent parses into structured requirements.
    """
    query: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Natural language vendor search query",
        examples=["Find ISO 27001 certified cloud security vendors in EU under €1M revenue"]
    )
    max_vendors: int = Field(
        default=20,
        ge=5,
        le=50,
        description="Maximum number of vendors to research"
    )
    detail_level: Literal["low", "medium", "high"] = Field(
        default="medium",
        description=(
            "Controls research depth vs speed trade-off. "
            "low=quick scan (5 vendors, 60s timeout), "
            "medium=standard (8 vendors, 120s), "
            "high=deep extraction (12 vendors, 180s)"
        )
    )
    demo_mode: bool = Field(
        default=False,
        description="If True, return pre-cached demo results instantly"
    )


# ---- API Response Models ----

class SearchResponse(BaseModel):
    """Response returned immediately when a search job is created."""
    job_id: str
    status: str = "processing"
    message: str = "Research agents deployed. Working on your query."
    estimated_time: int = 180  # seconds


class AgentStatusResponse(BaseModel):
    """Status of a single agent within a research job."""
    name: str  # "orchestrator", "research", "compliance", etc.
    status: str = "pending"  # "pending", "running", "completed", "failed"
    message: str = ""
    findings_count: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class JobStatusResponse(BaseModel):
    """Full status of a research job including all agents."""
    job_id: str
    status: str  # "processing", "completed", "failed"
    progress: int = 0  # 0-100
    query: str = ""
    agents: list[AgentStatusResponse] = []
    vendors_found: int = 0
    vendors_verified: int = 0
    created_at: str = ""
    completed_at: Optional[str] = None


# ---- Vendor Data Models ----

class VendorResult(BaseModel):
    """
    A single vendor in the research results.
    Contains aggregated data from all agents.
    """
    id: str
    company_name: str
    website: str = ""
    description: str = ""
    location: str = ""
    industry: str = ""
    year_founded: Optional[int] = None
    employee_count: Optional[int] = None
    revenue_indicator: str = ""  # "< $1M", "$1M-$10M", "$10M-$50M", etc.
    
    # Scores from agents (0-100)
    match_score: float = 0.0
    compliance_score: Optional[float] = None
    financial_score: Optional[float] = None
    risk_score: Optional[float] = None
    
    risk_level: str = "unknown"  # "low", "medium", "high"
    
    certifications: list[str] = []
    products_services: list[str] = []
    strengths: list[str] = []
    weaknesses: list[str] = []
    data_sources: list[str] = []  # URLs where information was found
    
    # Detailed data from each agent
    compliance_data: Optional[dict] = None
    financial_data: Optional[dict] = None
    risk_data: Optional[dict] = None
    
    # V2.0: Extended assessment data
    authenticity_data: Optional[dict] = None
    price_data: Optional[dict] = None
    specification_data: Optional[dict] = None


class ResearchReport(BaseModel):
    """
    Complete research report combining all agent outputs.
    This is the final deliverable for a vendor search job.
    """
    job_id: str
    query: str
    executive_summary: str = ""
    
    vendor_shortlist: list[VendorResult] = []
    
    comparison_matrix: dict = {}  # {criterion: {vendor_id: score}}
    recommendations: list[str] = []
    
    # Metadata
    total_sources_searched: int = 0
    total_vendors_found: int = 0
    total_vendors_verified: int = 0
    research_duration_seconds: float = 0.0
    agents_used: list[str] = []
    created_at: str = ""


# ---- Agent Internal Models ----

class ParsedRequirements(BaseModel):
    """
    Structured requirements extracted from natural language query.
    The Orchestrator Agent produces this from the user's query.
    Field names match the LLM prompt output and orchestrator builder.
    """
    product_or_service: str = ""
    industry: str = "General"
    budget_range: Optional[str] = None
    certifications_required: list[str] = []
    geographic_preference: Optional[str] = None
    quantity: Optional[str] = None
    timeline: Optional[str] = None
    quality_requirements: list[str] = []
    additional_constraints: list[str] = []
    search_keywords: list[str] = []


# ---- Authenticity Verification Models (V2.0) ----

class CertificationRecord(BaseModel):
    """A single certification or quality mark found on a vendor/product."""
    name: str = ""
    issuer: str = ""
    certificate_number: str = ""
    valid_until: Optional[str] = None
    evidence_type: str = "text_claim"  # "logo", "text_claim", "document", "registry_verified"
    verification_url: str = ""


class AuthenticityResult(BaseModel):
    """
    Result of authenticity verification for a vendor.
    Includes BIS/ISI checks, certification cross-referencing, and trust scoring.
    """
    vendor_website: str = ""
    verified_certifications: list[CertificationRecord] = []
    unverified_claims: list[str] = []
    bis_license_found: bool = False
    bis_license_number: str = ""
    certification_score: float = 0.0  # 0.0-1.0
    trust_indicators: list[str] = []
    red_flags: list[str] = []
    summary: str = ""


# ---- Price Comparison Models (V2.0) ----

class PriceDataPoint(BaseModel):
    """A price observation from a specific source."""
    source: str = ""  # "amazon_in", "flipkart", "vendor_website"
    price: float = 0.0
    currency: str = "INR"
    url: str = ""
    scraped_at: str = ""


class PriceAnalysis(BaseModel):
    """
    Price intelligence for a vendor's products/services.
    Includes multi-source comparison and market positioning.
    """
    vendor_website: str = ""
    product_or_service: str = ""
    prices_found: list[PriceDataPoint] = []
    average_price: float = 0.0
    median_price: float = 0.0
    min_price: float = 0.0
    max_price: float = 0.0
    price_index: float = 100.0  # <100 = below market, >100 = above market
    price_competitiveness: str = "unknown"  # "very_competitive", "competitive", "average", "premium", "overpriced"
    market_summary: str = ""


# ---- Specification Corpus Models (V2.0) ----

class ProductSpecification(BaseModel):
    """A single extracted specification attribute with confidence score."""
    attribute_name: str = ""
    attribute_value: str = ""
    confidence: float = 0.0  # 0.0-1.0
    source: str = ""  # where this spec was found


class SpecificationResult(BaseModel):
    """
    Enriched specification corpus for a vendor's products.
    Aggregated from multiple sources with confidence scoring.
    """
    vendor_website: str = ""
    product_category: str = ""
    specifications: list[ProductSpecification] = []
    completeness_score: float = 0.0  # 0.0-1.0 how many expected specs were found
    sources_checked: int = 0
    missing_attributes: list[str] = []
    summary: str = ""


class SSEEvent(BaseModel):
    """Server-Sent Event data structure for real-time updates."""
    agent: str
    status: str
    message: str
    findings_count: int = 0
    progress: int = 0
    timestamp: str = ""


# ---- Health Check ----

class HealthResponse(BaseModel):
    """Standard health check response."""
    status: str = "healthy"
    service: str = "vendorscout-pro"
    version: str = "1.0"
    uptime_seconds: float = 0.0
    database: str = "connected"
