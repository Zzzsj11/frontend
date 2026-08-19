from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
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
    auth_version: Mapped[int] = mapped_column(Integer, default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    daily_chat_limit: Mapped[int] = mapped_column(Integer, default=1000)
    daily_image_limit: Mapped[int] = mapped_column(Integer, default=1000)
    daily_video_limit: Mapped[int] = mapped_column(Integer, default=1000)


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
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)


class SongEmotionProfileModel(LifecycleMixin, Base):
    __tablename__ = "song_emotion_profiles"
    song_code: Mapped[str] = mapped_column(String(80), primary_key=True)
    song_name: Mapped[str] = mapped_column(String(255), default="")
    artists: Mapped[str] = mapped_column(Text, default="")
    lyrics: Mapped[str] = mapped_column(Text, default="")
    primary_category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    secondary_category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tertiary_category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    material_category: Mapped[str] = mapped_column(Text, default="")
    seasons: Mapped[str] = mapped_column(String(120), default="")
    atmosphere: Mapped[str] = mapped_column(Text, default="")
    character_setting: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[int] = mapped_column(Integer, default=2, index=True)
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
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


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
    # AIGC 平台虚拟资产链接（asset://xxx）：生成视频时用其替代原始 TOS 路径，以通过真人人脸校验
    asset_avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    __table_args__ = (
        Index(
            "uq_task_cast_human_active", "project_task_id", "digital_human_id", unique=True, postgresql_where=text("deleted_at IS NULL"), sqlite_where=text("deleted_at IS NULL")
        ),
    )
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
    __table_args__ = (
        Index(
            "uq_line_cast_human_active", "storyboard_line_id", "digital_human_id", unique=True, postgresql_where=text("deleted_at IS NULL"), sqlite_where=text("deleted_at IS NULL")
        ),
    )
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
    generation_job_id: Mapped[str | None] = mapped_column(ForeignKey("generation_jobs.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str] = mapped_column(String(120), default="等待导出")
    total_assets: Mapped[int] = mapped_column(Integer, default=0)
    processed_assets: Mapped[int] = mapped_column(Integer, default=0)
    total_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    processed_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    archive_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    archive_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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


class LlmCallLogModel(LifecycleMixin, Base):
    """分镜 LLM 调用全量留痕：请求消息、返回原文、耗时与 token 用量。"""

    __tablename__ = "llm_call_logs"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    project_task_id: Mapped[str | None] = mapped_column(ForeignKey("project_tasks.id"), nullable=True, index=True)
    storyboard_line_id: Mapped[str | None] = mapped_column(ForeignKey("storyboard_lines.id"), nullable=True, index=True)
    generation_job_id: Mapped[str | None] = mapped_column(ForeignKey("generation_jobs.id"), nullable=True, index=True)
    operation: Mapped[str] = mapped_column(String(80), index=True)
    provider: Mapped[str] = mapped_column(String(80), default="")
    model: Mapped[str] = mapped_column(String(160), default="")
    request_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="ok", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    request_messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    response_text: Mapped[str] = mapped_column(Text, default="")
    # 本次调用命中的提示词模板版本（空串/0 表示内置兜底或未接入注册中心）
    prompt_key: Mapped[str] = mapped_column(String(120), default="", index=True)
    prompt_version: Mapped[int] = mapped_column(Integer, default=0)


class DailyUsageQuotaModel(LifecycleMixin, Base):
    __tablename__ = "daily_usage_quotas"
    __table_args__ = (UniqueConstraint("user_id", "usage_date", "category", name="uq_daily_usage_quota_user_date_category"),)
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    usage_date: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)


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


class ApiRequestLogModel(LifecycleMixin, Base):
    """测试流量的 API 请求耗时留痕；仅带 X-Test-Run-Id 头或开启全量开关的请求才会入库。"""

    __tablename__ = "api_request_logs"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(Text)
    query_string: Mapped[str] = mapped_column(Text, default="")
    status_code: Mapped[int] = mapped_column(Integer, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    client_ip: Mapped[str | None] = mapped_column(String(80), nullable=True)


class AdminRoleModel(LifecycleMixin, Base):
    __tablename__ = "admin_roles"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")


class AdminPermissionModel(LifecycleMixin, Base):
    __tablename__ = "admin_permissions"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    code: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))


class AdminRolePermissionModel(LifecycleMixin, Base):
    __tablename__ = "admin_role_permissions"
    __table_args__ = (
        Index(
            "uq_admin_role_permission_active",
            "role_id",
            "permission_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("admin_roles.id"), index=True)
    permission_id: Mapped[str] = mapped_column(ForeignKey("admin_permissions.id"), index=True)


class UserAdminRoleModel(LifecycleMixin, Base):
    __tablename__ = "user_admin_roles"
    __table_args__ = (
        Index(
            "uq_user_admin_role_active",
            "user_id",
            "role_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("admin_roles.id"), index=True)


class AdminOperationLogModel(LifecycleMixin, Base):
    __tablename__ = "admin_operation_logs"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    admin_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    target_type: Mapped[str] = mapped_column(String(80), index=True)
    target_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    before_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    after_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    client_ip: Mapped[str | None] = mapped_column(String(80), nullable=True)


class AiProviderModel(LifecycleMixin, Base):
    __tablename__ = "ai_providers"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)


class H3TestPresetModel(LifecycleMixin, Base):
    """管理员个人的 H3 测试输入与已归档输出。"""

    __tablename__ = "h3_test_presets"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    mode: Mapped[str] = mapped_column(String(32), index=True)
    prompt: Mapped[str] = mapped_column(Text, default="")
    duration: Mapped[float] = mapped_column(Float, default=8)
    aspect_ratio: Mapped[str] = mapped_column(String(80), default="16:9 (Widescreen)")
    input_media: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    output_media: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    task_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    task_status: Mapped[str] = mapped_column(String(32), default="READY", index=True)
    usage_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)


class ServerMetricSampleModel(LifecycleMixin, Base):
    __tablename__ = "server_metric_samples"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source: Mapped[str] = mapped_column(String(120), default="primary", index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    boot_id: Mapped[str] = mapped_column(String(80), default="")
    interface: Mapped[str] = mapped_column(String(80), default="")
    cpu_percent: Mapped[float] = mapped_column(Float, default=0)
    load_1: Mapped[float] = mapped_column(Float, default=0)
    load_5: Mapped[float] = mapped_column(Float, default=0)
    load_15: Mapped[float] = mapped_column(Float, default=0)
    memory_total_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    memory_available_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    disk_total_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    disk_available_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    network_tx_bytes_total: Mapped[int] = mapped_column(BigInteger, default=0)
    network_rx_bytes_total: Mapped[int] = mapped_column(BigInteger, default=0)
    network_tx_bps: Mapped[float] = mapped_column(Float, default=0)
    network_rx_bps: Mapped[float] = mapped_column(Float, default=0)
    containers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class ServerTrafficMonthModel(LifecycleMixin, Base):
    __tablename__ = "server_traffic_months"
    __table_args__ = (UniqueConstraint("source", "month", name="uq_server_traffic_source_month"),)
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source: Mapped[str] = mapped_column(String(120), default="primary", index=True)
    month: Mapped[date] = mapped_column(Date, index=True)
    quota_bytes: Mapped[int] = mapped_column(BigInteger)
    egress_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    last_counter_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    last_boot_id: Mapped[str] = mapped_column(String(80), default="")


class ServerAlertEventModel(LifecycleMixin, Base):
    __tablename__ = "server_alert_events"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source: Mapped[str] = mapped_column(String(120), default="primary", index=True)
    alert_key: Mapped[str] = mapped_column(String(120), index=True)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text, default="")
    current_value: Mapped[float] = mapped_column(Float, default=0)
    threshold_value: Mapped[float] = mapped_column(Float, default=0)
    first_triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ServerMaintenanceRunModel(LifecycleMixin, Base):
    __tablename__ = "server_maintenance_runs"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(120), default="primary", index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    trigger: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AiModelModel(LifecycleMixin, Base):
    __tablename__ = "ai_models"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("ai_providers.id"), index=True)
    code: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    modality: Mapped[str] = mapped_column(String(32), index=True)
    provider_model_id: Mapped[str] = mapped_column(String(200))
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    user_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ModelPriceVersionModel(LifecycleMixin, Base):
    __tablename__ = "model_price_versions"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("ai_models.id"), index=True)
    currency: Mapped[str] = mapped_column(String(16), default="CNY")
    unit: Mapped[str] = mapped_column(String(32), default="request")
    input_price: Mapped[float] = mapped_column(Float, default=0)
    output_price: Mapped[float] = mapped_column(Float, default=0)
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PromptTemplateModel(LifecycleMixin, Base):
    """提示词模板：key 全局唯一；运行时只读 current_version_id 指向的已发布版本。"""

    __tablename__ = "prompt_templates"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    engine: Mapped[str] = mapped_column(String(32), default="llm", index=True)
    format: Mapped[str] = mapped_column(String(16), default="text")
    variables: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    required_fragments: Mapped[list[str]] = mapped_column(JSON, default=list)
    current_version_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)


class PromptVersionModel(LifecycleMixin, Base):
    """提示词版本：published 后内容不可变；回滚 = 以旧版本内容新建版本再发布。"""

    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_prompt_versions_template_version"),)
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("prompt_templates.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    change_note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    created_by: Mapped[str] = mapped_column(String(80), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StoryboardOptionItemModel(LifecycleMixin, Base):
    """通用分镜选项：genre 为三级分类树（parent_id 自引用），season/age_group/visual_style 为平铺列表。

    管理后台维护；删除为软删除，已生成项目 storyboard_config 存中文名不受影响。
    """

    __tablename__ = "storyboard_option_items"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("storyboard_option_items.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
