# ============================================================
# VendorScout Pro - Database Module (V2.0)
# ============================================================
# SQLite database with async access via aiosqlite.
# Schema is designed to be PostgreSQL-compatible for future migration.
# Provides CRUD helpers for research_jobs, vendors, agent_logs,
# and V2.0 tables: authenticity_checks, price_history, specification_corpus.
# ============================================================

import aiosqlite
import json
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Global database connection reference
_db: Optional[aiosqlite.Connection] = None


# ---- Schema Definition ----
# These schemas use standard SQL types compatible with PostgreSQL.
# JSON fields are stored as TEXT in SQLite, parsed in Python.

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS research_jobs (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    requirements TEXT DEFAULT '{}',
    status TEXT DEFAULT 'processing',
    progress INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    demo_mode INTEGER DEFAULT 0,
    total_vendors_found INTEGER DEFAULT 0,
    total_vendors_verified INTEGER DEFAULT 0,
    executive_summary TEXT DEFAULT '',
    comparison_matrix TEXT DEFAULT '{}',
    recommendations TEXT DEFAULT '[]',
    errors TEXT DEFAULT '[]',
    duration_seconds REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS vendors (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    website TEXT DEFAULT '',
    description TEXT DEFAULT '',
    location TEXT DEFAULT '',
    industry TEXT DEFAULT '',
    year_founded INTEGER,
    employee_count INTEGER,
    revenue_indicator TEXT DEFAULT '',
    certifications TEXT DEFAULT '[]',
    products_services TEXT DEFAULT '[]',
    contact_info TEXT DEFAULT '{}',
    data_sources TEXT DEFAULT '[]',
    match_score REAL DEFAULT 0.0,
    compliance_score REAL,
    financial_score REAL,
    risk_score REAL,
    risk_level TEXT DEFAULT 'unknown',
    strengths TEXT DEFAULT '[]',
    weaknesses TEXT DEFAULT '[]',
    compliance_data TEXT DEFAULT '{}',
    financial_data TEXT DEFAULT '{}',
    risk_data TEXT DEFAULT '{}',
    raw_profile TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (job_id) REFERENCES research_jobs(id)
);

CREATE TABLE IF NOT EXISTS agent_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT DEFAULT '',
    findings_count INTEGER DEFAULT 0,
    details TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (job_id) REFERENCES research_jobs(id)
);

CREATE INDEX IF NOT EXISTS idx_vendors_job_id ON vendors(job_id);
CREATE INDEX IF NOT EXISTS idx_agent_logs_job_id ON agent_logs(job_id);
CREATE INDEX IF NOT EXISTS idx_agent_logs_created ON agent_logs(created_at);
"""

# V2.0: Additional columns and tables for authenticity, price, and specification features
SCHEMA_V2_SQL = """
-- Add new columns to vendors table (safe to run multiple times with IF NOT EXISTS-like pattern)
-- SQLite doesn't support IF NOT EXISTS for ALTER TABLE, so we handle via try/except in code

CREATE TABLE IF NOT EXISTS authenticity_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    vendor_website TEXT NOT NULL,
    certification_score REAL DEFAULT 0.0,
    bis_license_found INTEGER DEFAULT 0,
    bis_license_number TEXT DEFAULT '',
    verified_certifications TEXT DEFAULT '[]',
    unverified_claims TEXT DEFAULT '[]',
    trust_indicators TEXT DEFAULT '[]',
    red_flags TEXT DEFAULT '[]',
    summary TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (job_id) REFERENCES research_jobs(id)
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    vendor_website TEXT NOT NULL,
    product_or_service TEXT DEFAULT '',
    source TEXT DEFAULT '',
    price REAL DEFAULT 0.0,
    currency TEXT DEFAULT 'INR',
    url TEXT DEFAULT '',
    scraped_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (job_id) REFERENCES research_jobs(id)
);

CREATE TABLE IF NOT EXISTS price_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    vendor_website TEXT NOT NULL,
    product_or_service TEXT DEFAULT '',
    average_price REAL DEFAULT 0.0,
    median_price REAL DEFAULT 0.0,
    min_price REAL DEFAULT 0.0,
    max_price REAL DEFAULT 0.0,
    price_index REAL DEFAULT 100.0,
    price_competitiveness TEXT DEFAULT 'unknown',
    market_summary TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (job_id) REFERENCES research_jobs(id)
);

CREATE TABLE IF NOT EXISTS specification_corpus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    vendor_website TEXT NOT NULL,
    product_category TEXT DEFAULT '',
    specifications TEXT DEFAULT '[]',
    completeness_score REAL DEFAULT 0.0,
    sources_checked INTEGER DEFAULT 0,
    missing_attributes TEXT DEFAULT '[]',
    summary TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (job_id) REFERENCES research_jobs(id)
);

CREATE INDEX IF NOT EXISTS idx_auth_job_id ON authenticity_checks(job_id);
CREATE INDEX IF NOT EXISTS idx_price_hist_job_id ON price_history(job_id);
CREATE INDEX IF NOT EXISTS idx_price_analysis_job_id ON price_analysis(job_id);
CREATE INDEX IF NOT EXISTS idx_spec_job_id ON specification_corpus(job_id);
"""

# V2.2: Signal table for pipeline control (stop, skip, fast-forward)
SCHEMA_SIGNALS_SQL = """
CREATE TABLE IF NOT EXISTS job_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    target TEXT DEFAULT '',
    processed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (job_id) REFERENCES research_jobs(id)
);
CREATE INDEX IF NOT EXISTS idx_signals_job_id ON job_signals(job_id);
"""


async def init_db() -> aiosqlite.Connection:
    """
    Initialize database connection and create tables.
    Creates the data directory if it doesn't exist.
    Returns the database connection for use throughout the app.
    """
    global _db
    
    db_path = Path(settings.DATABASE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Initializing database at {db_path}")
    _db = await aiosqlite.connect(str(db_path))
    _db.row_factory = aiosqlite.Row
    
    # Enable WAL mode for better concurrent read performance
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    
    # Create tables
    await _db.executescript(SCHEMA_SQL)
    
    # V2.0: Create new tables (safe to run multiple times)
    await _db.executescript(SCHEMA_V2_SQL)
    
    # V2.2: Signal table for pipeline control
    await _db.executescript(SCHEMA_SIGNALS_SQL)
    
    # V2.0: Add new columns to vendors table if they don't exist yet
    for col_name, col_def in [
        ("authenticity_data", "TEXT DEFAULT '{}'"),
        ("price_data", "TEXT DEFAULT '{}'"),
        ("specification_data", "TEXT DEFAULT '{}'"),
    ]:
        try:
            await _db.execute(f"ALTER TABLE vendors ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass  # Column already exists
    
    await _db.commit()
    
    logger.info("Database initialized successfully")
    return _db


async def get_db() -> aiosqlite.Connection:
    """Get the active database connection. Initialize if needed."""
    global _db
    if _db is None:
        _db = await init_db()
    return _db


async def close_db():
    """Close the database connection gracefully."""
    global _db
    if _db:
        await _db.close()
        _db = None
        logger.info("Database connection closed")


# ---- Research Jobs CRUD ----

async def create_job(query: str, requirements: dict = None, demo_mode: bool = False, job_id: str = None) -> str:
    """
    Create a new research job and return its ID.
    The job starts in 'processing' status.
    
    Args:
        query: The natural language search query
        requirements: Parsed requirements dict (optional)
        demo_mode: Whether this is a demo/seed data job
        job_id: Optional custom job ID (used for seed data). Auto-generated if not provided.
    """
    db = await get_db()
    if not job_id:
        job_id = f"vs-{uuid.uuid4().hex[:12]}"
    
    await db.execute(
        """INSERT INTO research_jobs (id, query, requirements, demo_mode)
           VALUES (?, ?, ?, ?)""",
        (job_id, query, json.dumps(requirements or {}), int(demo_mode))
    )
    await db.commit()
    
    logger.info(f"Created research job {job_id}: {query[:80]}...")
    return job_id


async def get_job(job_id: str) -> Optional[dict]:
    """Get a research job by ID. Returns None if not found."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM research_jobs WHERE id = ?", (job_id,)
    )
    row = await cursor.fetchone()
    
    if row is None:
        return None
    
    return _row_to_dict(row)


async def update_job_status(
    job_id: str,
    status: str,
    progress: int = None,
    **kwargs
):
    """
    Update job status and optionally other fields.
    Accepts keyword arguments for any column in research_jobs.
    """
    db = await get_db()
    
    updates = {"status": status}
    if progress is not None:
        updates["progress"] = progress
    if status == "completed":
        updates["completed_at"] = datetime.utcnow().isoformat()
    
    updates.update(kwargs)
    
    # Build SET clause dynamically
    set_parts = []
    values = []
    for key, value in updates.items():
        set_parts.append(f"{key} = ?")
        # JSON-encode dicts and lists
        if isinstance(value, (dict, list)):
            values.append(json.dumps(value))
        else:
            values.append(value)
    
    values.append(job_id)
    
    await db.execute(
        f"UPDATE research_jobs SET {', '.join(set_parts)} WHERE id = ?",
        values
    )
    await db.commit()


# ---- Vendors CRUD ----

async def save_vendor(job_id: str, vendor_data: dict) -> str:
    """
    Save a vendor to the database linked to a job.
    Returns the vendor ID.
    """
    db = await get_db()
    vendor_id = vendor_data.get("id", f"v-{uuid.uuid4().hex[:12]}")
    
    await db.execute(
        """INSERT OR REPLACE INTO vendors 
           (id, job_id, company_name, website, description, location, industry,
            year_founded, employee_count, revenue_indicator, certifications,
            products_services, data_sources, match_score, compliance_score,
            financial_score, risk_score, risk_level, strengths, weaknesses,
            compliance_data, financial_data, risk_data, raw_profile,
            authenticity_data, price_data, specification_data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            vendor_id,
            job_id,
            vendor_data.get("company_name", "Unknown"),
            vendor_data.get("website", ""),
            vendor_data.get("description", ""),
            vendor_data.get("location", ""),
            vendor_data.get("industry", ""),
            vendor_data.get("year_founded"),
            vendor_data.get("employee_count"),
            vendor_data.get("revenue_indicator", ""),
            json.dumps(vendor_data.get("certifications", [])),
            json.dumps(vendor_data.get("products_services", [])),
            json.dumps(vendor_data.get("data_sources", [])),
            vendor_data.get("match_score", 0.0),
            vendor_data.get("compliance_score"),
            vendor_data.get("financial_score"),
            vendor_data.get("risk_score"),
            vendor_data.get("risk_level", "unknown"),
            json.dumps(vendor_data.get("strengths", [])),
            json.dumps(vendor_data.get("weaknesses", [])),
            json.dumps(vendor_data.get("compliance_data", {})),
            json.dumps(vendor_data.get("financial_data", {})),
            json.dumps(vendor_data.get("risk_data", {})),
            json.dumps(vendor_data.get("raw_profile", {})),
            json.dumps(vendor_data.get("authenticity_data", {})),
            json.dumps(vendor_data.get("price_data", {})),
            json.dumps(vendor_data.get("specification_data", {})),
        )
    )
    await db.commit()
    return vendor_id


async def get_vendors_for_job(job_id: str) -> list[dict]:
    """Get all vendors for a research job, sorted by match score descending."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM vendors WHERE job_id = ? ORDER BY match_score DESC",
        (job_id,)
    )
    rows = await cursor.fetchall()
    
    vendors = []
    for row in rows:
        vendor = _row_to_dict(row)
        # Parse JSON fields
        for field in ["certifications", "products_services", "data_sources",
                      "strengths", "weaknesses"]:
            if isinstance(vendor.get(field), str):
                try:
                    vendor[field] = json.loads(vendor[field])
                except (json.JSONDecodeError, TypeError):
                    vendor[field] = []
        for field in ["compliance_data", "financial_data", "risk_data", "raw_profile",
                      "authenticity_data", "price_data", "specification_data"]:
            if isinstance(vendor.get(field), str):
                try:
                    vendor[field] = json.loads(vendor[field])
                except (json.JSONDecodeError, TypeError):
                    vendor[field] = {}
        vendors.append(vendor)
    
    return vendors


# ---- Agent Logs CRUD ----

async def log_agent_activity(
    job_id: str,
    agent_name: str,
    status: str,
    message: str = "",
    findings_count: int = 0,
    details: dict = None
):
    """
    Log an agent activity event. These logs power the SSE streaming
    and the agent timeline UI on the research page.
    """
    db = await get_db()
    
    await db.execute(
        """INSERT INTO agent_logs (job_id, agent_name, status, message, findings_count, details)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (job_id, agent_name, status, message, findings_count, json.dumps(details or {}))
    )
    await db.commit()


async def get_agent_logs(job_id: str, since_id: int = 0) -> list[dict]:
    """
    Get agent logs for a job, optionally only those after a given log ID.
    Used by SSE endpoint to send only new events to the frontend.
    """
    db = await get_db()
    cursor = await db.execute(
        """SELECT * FROM agent_logs 
           WHERE job_id = ? AND id > ?
           ORDER BY id ASC""",
        (job_id, since_id)
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(row) for row in rows]


async def get_latest_agent_statuses(job_id: str) -> list[dict]:
    """
    Get the latest status for each agent in a job.
    Used for the job status API endpoint.
    """
    db = await get_db()
    cursor = await db.execute(
        """SELECT agent_name, status, message, findings_count, 
                  MIN(created_at) as started_at, MAX(created_at) as last_update
           FROM agent_logs
           WHERE job_id = ?
           GROUP BY agent_name
           ORDER BY MIN(id) ASC""",
        (job_id,)
    )
    rows = await cursor.fetchall()
    
    agents = []
    for row in rows:
        row_dict = _row_to_dict(row)
        agents.append({
            "name": row_dict["agent_name"],
            "status": row_dict["status"],
            "message": row_dict["message"],
            "findings_count": row_dict["findings_count"],
            "started_at": row_dict["started_at"],
            "completed_at": row_dict["last_update"] if row_dict["status"] in ("completed", "failed") else None
        })
    
    return agents


# ---- Utility ----

def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
    if row is None:
        return {}
    return dict(row)


# ---- V2.0: Authenticity Checks CRUD ----

async def save_authenticity_check(job_id: str, vendor_website: str, data: dict):
    """Save an authenticity verification result for a vendor."""
    db = await get_db()
    await db.execute(
        """INSERT INTO authenticity_checks 
           (job_id, vendor_website, certification_score, bis_license_found,
            bis_license_number, verified_certifications, unverified_claims,
            trust_indicators, red_flags, summary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job_id,
            vendor_website,
            data.get("certification_score", 0.0),
            int(data.get("bis_license_found", False)),
            data.get("bis_license_number", ""),
            json.dumps(data.get("verified_certifications", [])),
            json.dumps(data.get("unverified_claims", [])),
            json.dumps(data.get("trust_indicators", [])),
            json.dumps(data.get("red_flags", [])),
            data.get("summary", ""),
        )
    )
    await db.commit()


# ---- V2.2: Job Signals CRUD (pipeline control) ----

async def add_job_signal(job_id: str, signal_type: str, target: str = "") -> int:
    """
    Add a control signal for a running job.
    
    Signal types:
    - 'stop': Halt pipeline, no report generated
    - 'fast_forward': Skip remaining assessments, proceed to analysis + report
    - 'skip_agent': Skip a specific agent (target = agent name)
    """
    conn = await get_db()
    cursor = await conn.execute(
        "INSERT INTO job_signals (job_id, signal_type, target) VALUES (?, ?, ?)",
        (job_id, signal_type, target)
    )
    await conn.commit()
    logger.info(f"Signal added for job {job_id}: {signal_type} target={target}")
    return cursor.lastrowid


async def has_signal(job_id: str, signal_type: str, target: str = None) -> bool:
    """Check if an unprocessed signal of given type exists for a job."""
    conn = await get_db()
    query = "SELECT COUNT(*) FROM job_signals WHERE job_id = ? AND signal_type = ? AND processed = 0"
    params = [job_id, signal_type]
    if target is not None:
        query += " AND target = ?"
        params.append(target)
    cursor = await conn.execute(query, params)
    row = await cursor.fetchone()
    return row[0] > 0


async def mark_signals_processed(job_id: str, signal_type: str = None):
    """Mark signals as processed after the pipeline has acted on them."""
    conn = await get_db()
    query = "UPDATE job_signals SET processed = 1 WHERE job_id = ?"
    params = [job_id]
    if signal_type:
        query += " AND signal_type = ?"
        params.append(signal_type)
    await conn.execute(query, params)
    await conn.commit()


# ---- V2.0: Price Data CRUD ----

async def save_price_analysis(job_id: str, vendor_website: str, data: dict):
    """Save price analysis results for a vendor."""
    db = await get_db()
    await db.execute(
        """INSERT INTO price_analysis 
           (job_id, vendor_website, product_or_service, average_price,
            median_price, min_price, max_price, price_index,
            price_competitiveness, market_summary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job_id,
            vendor_website,
            data.get("product_or_service", ""),
            data.get("average_price", 0.0),
            data.get("median_price", 0.0),
            data.get("min_price", 0.0),
            data.get("max_price", 0.0),
            data.get("price_index", 100.0),
            data.get("price_competitiveness", "unknown"),
            data.get("market_summary", ""),
        )
    )
    await db.commit()


# ---- V2.0: Specification Corpus CRUD ----

async def save_specification_corpus(job_id: str, vendor_website: str, data: dict):
    """Save specification corpus results for a vendor."""
    db = await get_db()
    await db.execute(
        """INSERT INTO specification_corpus 
           (job_id, vendor_website, product_category, specifications,
            completeness_score, sources_checked, missing_attributes, summary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job_id,
            vendor_website,
            data.get("product_category", ""),
            json.dumps(data.get("specifications", [])),
            data.get("completeness_score", 0.0),
            data.get("sources_checked", 0),
            json.dumps(data.get("missing_attributes", [])),
            data.get("summary", ""),
        )
    )
    await db.commit()
