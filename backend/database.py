"""PostgreSQL models and async DB connection."""

import os
import uuid
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, String, Text, text
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
        # Idempotent migration — add new columns without dropping anything
        await conn.execute(text(
            "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS audit_log_json JSONB"
        ))
