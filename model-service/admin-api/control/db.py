"""Versioned database contract; intentionally duplicated in control plane."""

import os
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Client(Record, Base):
    __tablename__ = "clients"
    name: Mapped[str] = mapped_column(String(160))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    key_prefix: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    allowed_models: Mapped[list] = mapped_column(JSON, default=list)
    concurrency: Mapped[int] = mapped_column(Integer, default=4)
    require_agent: Mapped[bool] = mapped_column(Boolean, default=False)
    billing_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    user_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    monthly_points: Mapped[float] = mapped_column(Numeric(24, 6), default=0, server_default="0")
    monthly_balance: Mapped[float] = mapped_column(Numeric(24, 6), default=0, server_default="0")
    extra_balance: Mapped[float] = mapped_column(Numeric(24, 6), default=0, server_default="0")
    billing_month: Mapped[str] = mapped_column(String(7), default="", server_default="")


class Model(Record, Base):
    __tablename__ = "models"
    channel: Mapped[str] = mapped_column(String(40))
    provider_model: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(20))
    protocol: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    concurrency: Mapped[int] = mapped_column(Integer, default=4)
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)


class ModelRoute(Record, Base):
    __tablename__ = "model_routes"
    model_id: Mapped[str] = mapped_column(String(160), index=True)
    supplier: Mapped[str] = mapped_column(String(40))
    channel: Mapped[str] = mapped_column(String(40))
    provider_model: Mapped[str] = mapped_column(String(160))
    protocol: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    concurrency: Mapped[int] = mapped_column(Integer, default=2)
    verification: Mapped[str] = mapped_column(String(40), default="pending")
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    pricing: Mapped[dict] = mapped_column(JSON, default=dict)


class Job(Record, Base):
    __tablename__ = "jobs"
    route_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    routing_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    __table_args__ = (UniqueConstraint("client_id", "user_id", "idempotency_key"),)
    client_id: Mapped[str] = mapped_column(String(160), index=True)
    user_id: Mapped[str] = mapped_column(String(160), index=True)
    model_id: Mapped[str] = mapped_column(String(160), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    channel: Mapped[str] = mapped_column(String(40))
    protocol: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    request_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    provider_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_response: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str] = mapped_column(String(20), default="business", index=True)
    agent_name: Mapped[str] = mapped_column(String(80), default="")
    agent_run_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    test_run_id: Mapped[str] = mapped_column(String(160), default="")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    reserved_points: Mapped[float] = mapped_column(Numeric(24, 6), default=0, server_default="0")
    charged_points: Mapped[float | None] = mapped_column(Numeric(24, 6), nullable=True)
    billing_status: Mapped[str] = mapped_column(String(40), default="pending", server_default="pending")
    pricing_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class Audit(Record, Base):
    __tablename__ = "audits"
    actor: Mapped[str] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(80))
    target: Mapped[str] = mapped_column(String(160))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class User(Record, Base):
    __tablename__ = "portal_users"
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class UserSession(Record, Base):
    __tablename__ = "portal_sessions"
    user_id: Mapped[str] = mapped_column(String(160), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PricingRule(Record, Base):
    __tablename__ = "pricing_rules"
    model_id: Mapped[str] = mapped_column(String(160), index=True)
    config: Mapped[dict] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(160))


class Ledger(Record, Base):
    __tablename__ = "credit_ledger"
    __table_args__ = (UniqueConstraint("client_id", "operation_id"),)
    client_id: Mapped[str] = mapped_column(String(160), index=True)
    user_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    job_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    operation_id: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40))
    points: Mapped[float] = mapped_column(Numeric(24, 6))
    monthly_after: Mapped[float] = mapped_column(Numeric(24, 6))
    extra_after: Mapped[float] = mapped_column(Numeric(24, 6))
    actor: Mapped[str] = mapped_column(String(160))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class ChannelAccount(Record, Base):
    __tablename__ = "channel_accounts"
    channel: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(160))
    key_env: Mapped[str] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(10))
    usd_cny: Mapped[float] = mapped_column(Numeric(24, 8), default=6.9)
    points_per_unit: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    points_currency: Mapped[str] = mapped_column(String(10), default="CNY")
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    queried_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)
