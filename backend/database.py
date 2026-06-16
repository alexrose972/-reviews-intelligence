"""PostgreSQL models and async DB connection."""

import os
import uuid
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text, text
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

_db_url = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/reviews_intelligence",
)
# Railway provides postgresql:// — asyncpg requires postgresql+asyncpg://
DATABASE_URL = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_name = Column(Text, nullable=False)
    domain = Column(Text, nullable=False)
    triggered_by = Column(Text, nullable=False)
    triggered_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="pending")  # pending|running|complete|failed
    overall_score = Column(Integer)
    grade = Column(String(2))
    scores_json = Column(JSONB)
    signals_json = Column(JSONB)
    recommendations_json = Column(JSONB)
    pitch_angles_json = Column(JSONB)
    llm_probe_json = Column(JSONB)
    detected_platform = Column(Text)
    sf_platform = Column(Text)
    platform_mismatch = Column(Boolean, default=False)
    pdf_path = Column(Text)
    slinger_drafts_json = Column(JSONB)
    screenshots_json = Column(JSONB)
    error_message = Column(Text)
    audit_log_json = Column(JSONB)

    # ── Chrome fallback fields ────────────────────────────────────────────
    scan_mode = Column(Text, default="playwright")
    # 'playwright' | 'chrome' | 'hybrid'

    chrome_job_status = Column(Text)
    # NULL | 'queued' | 'running' | 'complete' | 'failed' | 'timeout'

    chrome_job_queued_at = Column(DateTime)
    chrome_job_started_at = Column(DateTime)
    chrome_job_completed_at = Column(DateTime)
    chrome_raw_data = Column(JSONB)
    chrome_pdps_visited = Column(Integer, default=0)
    chrome_error = Column(Text)
    scan_fallback_reason = Column(Text)
    # 'no_pdps_found' | 'no_reviews_extracted' | 'bot_detection_suspected' | 'manual'


class ChromeJob(Base):
    """Queue of Chrome browser audit jobs (one processed at a time)."""
    __tablename__ = "chrome_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_id = Column(UUID(as_uuid=True), ForeignKey("scan_runs.id"), nullable=False)
    brand_name = Column(Text, nullable=False)
    domain = Column(Text, nullable=False)
    base_url = Column(Text, nullable=False)
    status = Column(Text, default="queued")
    # queued | running | complete | failed | timeout
    priority = Column(Integer, default=1)  # 1=normal, 2=high
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    timeout_at = Column(DateTime)  # created_at + 15 minutes
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=2)
    error = Column(Text)
    result_data = Column(JSONB)


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(Text, unique=True, nullable=False)
    name = Column(Text)
    google_id = Column(Text)
    profile_photo = Column(Text)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Idempotent migrations — safe to run multiple times
        await conn.execute(text(
            "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS audit_log_json JSONB"
        ))
        await conn.execute(text(
            "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS scan_mode TEXT DEFAULT 'playwright'"
        ))
        await conn.execute(text(
            "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS chrome_job_status TEXT DEFAULT NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS chrome_job_queued_at TIMESTAMP DEFAULT NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS chrome_job_started_at TIMESTAMP DEFAULT NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS chrome_job_completed_at TIMESTAMP DEFAULT NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS chrome_raw_data JSONB DEFAULT NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS chrome_pdps_visited INTEGER DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS chrome_error TEXT DEFAULT NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS scan_fallback_reason TEXT DEFAULT NULL"
        ))
