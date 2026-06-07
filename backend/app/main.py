# ============================================================
# VendorScout Pro - Main FastAPI Application
# ============================================================
# Entry point for the entire application. Configures:
# - FastAPI app with CORS and middleware
# - API routers (search, jobs, reports, health)
# - Jinja2 template rendering for frontend pages
# - Static file serving (CSS, JS)
# - Database initialization on startup
# - Logging configuration
#
# Run with: uvicorn app.main:app --host 0.0.0.0 --port 8000
# ============================================================

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from app.config import settings
from app import database as db
from app.api import search, jobs, reports, health, mission, scout
from version import APP_VERSION, APP_NAME

# ---- Logging Configuration ----
# Configure structured logging for all modules
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


# ---- Application Lifecycle ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown events.
    
    On startup: Initialize database tables
    On shutdown: Cleanup (future: close connection pools)
    """
    logger.info(f"Starting {APP_NAME} v{APP_VERSION}")
    
    # Initialize database tables
    await db.init_db()
    logger.info(f"Database initialized at {settings.DATABASE_PATH}")
    
    yield  # App runs here
    
    logger.info(f"Shutting down {APP_NAME}")


# ---- FastAPI App ----
app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Autonomous AI-powered B2B vendor research platform",
    lifespan=lifespan,
    docs_url="/docs",        # Swagger UI
    redoc_url="/redoc",      # ReDoc
)

# ---- CORS Middleware ----
# Allow requests from the same domain (Traefik handles external access)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to specific domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Static Files & Templates ----
# Serve CSS, JS, and image assets from the static directory
static_dir = Path(settings.STATIC_DIR)
static_dir.mkdir(parents=True, exist_ok=True)

templates_dir = Path(settings.TEMPLATES_DIR)
templates_dir.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates = Jinja2Templates(directory=str(templates_dir))

DEMO_VIDEO_URL = "https://www.youtube.com/watch?v=J6sPIBgOoBw"
DEMO_EMBED_URL = "https://www.youtube-nocookie.com/embed/J6sPIBgOoBw?rel=0"

# ---- API Routers ----
# All API endpoints are prefixed with /api/ (except health)
app.include_router(health.router)     # GET /health
app.include_router(search.router)     # POST /api/search
app.include_router(jobs.router)       # GET /api/jobs/*
app.include_router(reports.router)    # GET /api/reports/*
app.include_router(mission.router)    # POST /api/mission, GET /api/mission/*/stream
app.include_router(scout.router)      # POST /api/scout (the ChatGPT-style agentic flow)


# ---- Frontend Page Routes ----
# These serve HTML pages rendered with Jinja2 templates.
# The frontend uses Alpine.js + HTMX for interactivity without React.

@app.get("/", response_class=HTMLResponse)
async def home_chat(request: Request):
    """
    Home = the ChatGPT-style agentic sourcing chat (single page; only the
    transcript scrolls). Left sidebar holds past sessions (saved on-device).
    """
    return templates.TemplateResponse(
        "chat.html",
        {"request": request, "app_name": APP_NAME, "app_version": APP_VERSION},
    )


@app.get("/learn", response_class=HTMLResponse)
async def learn_page(request: Request):
    """Everything you need to know about evaluating vendors + how the agent works."""
    return templates.TemplateResponse(
        "learn.html",
        {"request": request, "app_name": APP_NAME, "app_version": APP_VERSION},
    )


@app.get("/classic", response_class=HTMLResponse)
async def classic_landing(request: Request):
    """The original multi-agent research landing (kept for reference)."""
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "app_name": APP_NAME, "app_version": APP_VERSION},
    )


@app.get("/mock/supplier", response_class=HTMLResponse)
async def mock_supplier_page(request: Request):
    """A controlled mock B2B supplier 'Send Enquiry' page — a SAFE target for the
    agent to complete a real RFQ transaction (fill + submit) on camera without
    contacting any real supplier."""
    return templates.TemplateResponse("mock_supplier.html", {"request": request})


@app.get("/theater", response_class=HTMLResponse)
async def theater_page(request: Request):
    """
    Live Browser Theater — give the agent a goal + URL and watch it plan,
    browse, act, and recover live (the Agentic Web demo centerpiece).
    """
    return templates.TemplateResponse(
        "theater.html",
        {"request": request, "app_name": APP_NAME, "app_version": APP_VERSION},
    )


@app.get("/research/{job_id}", response_class=HTMLResponse)
async def research_page(request: Request, job_id: str):
    """
    Research results page - shows real-time agent progress
    and final vendor results.
    
    Uses SSE to stream agent updates as they work.
    """
    job = await db.get_job(job_id)
    
    return templates.TemplateResponse(
        "research.html",
        {
            "request": request,
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "job_id": job_id,
            "job": job
        }
    )


@app.get("/demo", response_class=HTMLResponse)
async def demo_page(request: Request):
    """
    Hosted demo page for judges and reviewers.

    Embeds the public YouTube walkthrough behind a stable first-party path
    so the demo link is easy to share in submissions and presentations.
    """
    return templates.TemplateResponse(
        "demo.html",
        {
            "request": request,
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "demo_video_url": DEMO_VIDEO_URL,
            "demo_embed_url": DEMO_EMBED_URL,
        }
    )


@app.get("/report/{job_id}", response_class=HTMLResponse)
async def report_page(request: Request, job_id: str):
    """
    Full report page - displays the comprehensive research report
    with executive summary, rankings, comparisons, etc.
    """
    job = await db.get_job(job_id)
    
    return templates.TemplateResponse(
        "report.html",
        {
            "request": request,
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "job_id": job_id,
            "job": job
        }
    )
