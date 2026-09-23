"""Versioned database contract; intentionally duplicated in control plane."""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, UniqueConstraint
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


class Model(Record, Base):
    __tablename__ = "models"
    channel: Mapped[str] = mapped_column(String(40))
    provider_model: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(20))
    protocol: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    concurrency: Mapped[int] = mapped_column(Integer, default=4)
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)


class Job(Record, Base):
    __tablename__ = "jobs"
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


class Audit(Record, Base):
    __tablename__ = "audits"
    actor: Mapped[str] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(80))
    target: Mapped[str] = mapped_column(String(160))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
