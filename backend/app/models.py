from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class LifecycleMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class UserModel(LifecycleMixin, Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(32), default="user")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RefreshTokenModel(LifecycleMixin, Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(80), nullable=True)


class ProjectModel(LifecycleMixin, Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    artist: Mapped[str | None] = mapped_column(String(255), nullable=True)
    song_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class SongEmotionProfileModel(LifecycleMixin, Base):
    __tablename__ = "song_emotion_profiles"
    song_code: Mapped[str] = mapped_column(String(80), primary_key=True)
    song_name: Mapped[str] = mapped_column(String(255), default="")
    artists: Mapped[str] = mapped_column(Text, default="")
    primary_category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    secondary_category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tertiary_category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    material_category: Mapped[str] = mapped_column(Text, default="")
    seasons: Mapped[str] = mapped_column(String(120), default="")
    atmosphere: Mapped[str] = mapped_column(Text, default="")
    source_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ProjectTaskModel(LifecycleMixin, Base):
    __tablename__ = "project_tasks"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    storyboard_type: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    source_ass_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_requirement: Mapped[str] = mapped_column(Text, default="")
    overall_prompt: Mapped[str] = mapped_column(Text, default="")
    storyboard_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DigitalHumanStyleModel(LifecycleMixin, Base):
    __tablename__ = "digital_human_styles"
    __table_args__ = (Index("uq_dh_style_user_name_active", "user_id", "name", unique=True, postgresql_where=text("deleted_at IS NULL"), sqlite_where=text("deleted_at IS NULL")),)
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(32), default="private", index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class DigitalHumanModel(LifecycleMixin, Base):
    __tablename__ = "digital_humans"
    __table_args__ = (Index("uq_digital_human_asset_code_active", "asset_code", unique=True, postgresql_where=text("deleted_at IS NULL"), sqlite_where=text("deleted_at IS NULL")),)
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    style_id: Mapped[str | None] = mapped_column(ForeignKey("digital_human_styles.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    avatar_url: Mapped[str] = mapped_column(Text)
    avatar_thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_prompt: Mapped[str] = mapped_column(Text, default="")
    asset_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    gender: Mapped[str | None] = mapped_column(String(32), nullable=True)
    age_description: Mapped[str] = mapped_column(String(255), default="")
    appearance_style: Mapped[str] = mapped_column(Text, default="")
    clothing_description: Mapped[str] = mapped_column(Text, default="")
    suitable_music_styles: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(32), default="uploaded")
    scope: Mapped[str] = mapped_column(String(32), default="private", index=True)
    status: Mapped[str] = mapped_column(String(32), default="active")


class ProjectCastModel(LifecycleMixin, Base):
    __tablename__ = "project_cast"
    __table_args__ = (Index("uq_task_cast_human_active", "project_task_id", "digital_human_id", unique=True, postgresql_where=text("deleted_at IS NULL"), sqlite_where=text("deleted_at IS NULL")),)
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    project_task_id: Mapped[str] = mapped_column(ForeignKey("project_tasks.id"), index=True)
    digital_human_id: Mapped[str] = mapped_column(ForeignKey("digital_humans.id"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class StoryboardLineModel(LifecycleMixin, Base):
    __tablename__ = "storyboard_lines"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    project_task_id: Mapped[str] = mapped_column(ForeignKey("project_tasks.id"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    shot_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    planned_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    lyrics: Mapped[str] = mapped_column(Text, default="")
    lyrics_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    scene_prompt: Mapped[str] = mapped_column(Text, default="")
    shot_prompt: Mapped[str] = mapped_column(Text, default="")
    shot_options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    generation_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    generation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_attempt: Mapped[int] = mapped_column(Integer, default=0)
    prompt_context_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StoryboardLineCastModel(LifecycleMixin, Base):
    __tablename__ = "storyboard_line_cast"
    __table_args__ = (Index("uq_line_cast_human_active", "storyboard_line_id", "digital_human_id", unique=True, postgresql_where=text("deleted_at IS NULL"), sqlite_where=text("deleted_at IS NULL")),)
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    storyboard_line_id: Mapped[str] = mapped_column(ForeignKey("storyboard_lines.id"), index=True)
    digital_human_id: Mapped[str] = mapped_column(ForeignKey("digital_humans.id"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class GenerationJobModel(LifecycleMixin, Base):
    __tablename__ = "generation_jobs"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    project_task_id: Mapped[str | None] = mapped_column(ForeignKey("project_tasks.id"), nullable=True, index=True)
    storyboard_line_id: Mapped[str | None] = mapped_column(ForeignKey("storyboard_lines.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_task_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SceneAssetModel(LifecycleMixin, Base):
    __tablename__ = "scene_assets"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    storyboard_line_id: Mapped[str] = mapped_column(ForeignKey("storyboard_lines.id"), index=True)
    generation_job_id: Mapped[str | None] = mapped_column(ForeignKey("generation_jobs.id"), nullable=True)
    image_url: Mapped[str] = mapped_column(Text)
    image_thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="ready")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class ShotAssetModel(LifecycleMixin, Base):
    __tablename__ = "shot_assets"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    storyboard_line_id: Mapped[str] = mapped_column(ForeignKey("storyboard_lines.id"), index=True)
    generation_job_id: Mapped[str | None] = mapped_column(ForeignKey("generation_jobs.id"), nullable=True)
    cover_url: Mapped[str] = mapped_column(Text)
    cover_thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_url: Mapped[str] = mapped_column(Text)
    duration: Mapped[float] = mapped_column(Float)
    resolution: Mapped[str] = mapped_column(String(32), default="1080p")
    ratio: Mapped[str] = mapped_column(String(32), default="16:9")
    prompt: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="ready")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class VoiceAssetModel(LifecycleMixin, Base):
    __tablename__ = "voice_assets"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    storyboard_line_id: Mapped[str] = mapped_column(ForeignKey("storyboard_lines.id"), index=True)
    generation_job_id: Mapped[str | None] = mapped_column(ForeignKey("generation_jobs.id"), nullable=True)
    audio_url: Mapped[str] = mapped_column(Text)
    duration: Mapped[float] = mapped_column(Float)
    voice_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="ready")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class MaterialExportModel(LifecycleMixin, Base):
    __tablename__ = "material_exports"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    project_task_id: Mapped[str] = mapped_column(ForeignKey("project_tasks.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    archive_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ChatSessionModel(LifecycleMixin, Base):
    __tablename__ = "chat_sessions"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="新对话")
    system_prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="idle", index=True)
    messages: Mapped[list["ChatMessageModel"]] = relationship(back_populates="session", order_by="ChatMessageModel.id")


class ChatMessageModel(LifecycleMixin, Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    session: Mapped[ChatSessionModel] = relationship(back_populates="messages")


class TokenUsageModel(LifecycleMixin, Base):
    __tablename__ = "token_usage_records"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    project_task_id: Mapped[str | None] = mapped_column(ForeignKey("project_tasks.id"), nullable=True, index=True)
    storyboard_line_id: Mapped[str | None] = mapped_column(ForeignKey("storyboard_lines.id"), nullable=True, index=True)
    generation_job_id: Mapped[str | None] = mapped_column(ForeignKey("generation_jobs.id"), nullable=True, index=True)
    chat_session_id: Mapped[str | None] = mapped_column(ForeignKey("chat_sessions.id"), nullable=True, index=True)
    operation: Mapped[str] = mapped_column(String(80), index=True)
    provider: Mapped[str] = mapped_column(String(80), default="")
    model: Mapped[str] = mapped_column(String(160), default="")
    request_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    raw_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ApiErrorLogModel(LifecycleMixin, Base):
    __tablename__ = "api_error_logs"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    error_code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    method: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(Text)
    query_string: Mapped[str] = mapped_column(Text, default="")
    status_code: Mapped[int] = mapped_column(Integer, index=True)
    error_type: Mapped[str] = mapped_column(String(160), index=True)
    message: Mapped[str] = mapped_column(Text)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    traceback: Mapped[str] = mapped_column(Text, default="")
    client_ip: Mapped[str | None] = mapped_column(String(80), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
