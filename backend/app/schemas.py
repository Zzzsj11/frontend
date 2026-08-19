from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .media_constraints import DEFAULT_VIDEO_DURATION, MAX_VIDEO_DURATION, MIN_VIDEO_DURATION


class LoginCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=6, max_length=200)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=6, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=120)
    role: Literal["admin", "user"] = "user"
    daily_chat_limit: int | None = Field(default=None, ge=1, le=1_000_000)
    daily_image_limit: int | None = Field(default=None, ge=1, le=1_000_000)
    daily_video_limit: int | None = Field(default=None, ge=1, le=1_000_000)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    role: Literal["admin", "user"] | None = None
    status: Literal["active", "disabled"] | None = None
    daily_chat_limit: int | None = Field(default=None, ge=1, le=1_000_000)
    daily_image_limit: int | None = Field(default=None, ge=1, le=1_000_000)
    daily_video_limit: int | None = Field(default=None, ge=1, le=1_000_000)


class UserAdminRoleUpdate(BaseModel):
    admin_role_code: Literal["none", "ass_admin", "super_admin"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    artist: str | None = Field(default=None, max_length=255)
    song_code: str | None = Field(default=None, max_length=120)
    description: str = Field(default="", max_length=10_000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    artist: str | None = Field(default=None, max_length=255)
    song_code: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=10_000)


class TaskCreate(BaseModel):
    title: str = Field(default="MV 分镜制作", min_length=1, max_length=255)
    storyboard_type: Literal["ass", "general", "manual"] = "manual"
    extra_requirement: str = Field(default="", max_length=20_000)
    overall_prompt: str = Field(default="", max_length=30_000)
    storyboard_config: dict = Field(default_factory=dict)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, max_length=32)
    extra_requirement: str | None = Field(default=None, max_length=20_000)
    overall_prompt: str | None = Field(default=None, max_length=30_000)
    storyboard_config: dict | None = None


class StyleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class DigitalHumanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    style_id: str | None = None
    description: str = Field(default="", max_length=10_000)
    avatar_url: str
    avatar_thumbnail_url: str | None = None
    avatar_prompt: str = Field(default="", max_length=20_000)
    gender: str | None = Field(default=None, max_length=32)
    age_description: str = Field(default="", max_length=255)
    appearance_style: str = Field(default="", max_length=10_000)
    clothing_description: str = Field(default="", max_length=10_000)
    suitable_music_styles: str = Field(default="", max_length=10_000)
    system_prompt: str = Field(default="", max_length=30_000)
    source: Literal["uploaded", "generated"] = "uploaded"


class DigitalHumanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    style_id: str | None = None
    description: str | None = Field(default=None, max_length=10_000)
    avatar_url: str | None = None
    avatar_thumbnail_url: str | None = None
    avatar_prompt: str | None = Field(default=None, max_length=20_000)
    gender: str | None = Field(default=None, max_length=32)
    age_description: str | None = Field(default=None, max_length=255)
    appearance_style: str | None = Field(default=None, max_length=10_000)
    clothing_description: str | None = Field(default=None, max_length=10_000)
    suitable_music_styles: str | None = Field(default=None, max_length=10_000)
    system_prompt: str | None = Field(default=None, max_length=30_000)


class StoryboardLineCreate(BaseModel):
    source: Literal["ass", "general", "manual"] = "manual"
    shot_type: Literal["empty", "character"] | None = None
    planned_duration: float | None = Field(default=None, gt=0)
    lyrics: str = ""
    lyrics_zh: str | None = None
    start_time: float | None = Field(default=None, ge=0)
    end_time: float | None = Field(default=None, ge=0)
    scene_prompt: str = ""
    shot_prompt: str = ""
    shot_options: dict = Field(default_factory=dict)
    digital_human_ids: list[str] = Field(default_factory=list)


class StoryboardLineUpdate(BaseModel):
    shot_type: Literal["empty", "character"] | None = None
    planned_duration: float | None = Field(default=None, gt=0)
    lyrics: str | None = None
    lyrics_zh: str | None = None
    scene_prompt: str | None = None
    shot_prompt: str | None = None
    shot_options: dict | None = None
    digital_human_ids: list[str] | None = None


class ReorderLines(BaseModel):
    line_ids: list[str]


class CastUpdate(BaseModel):
    digital_human_ids: list[str]


class GeneralStoryboardCreate(BaseModel):
    genre: str
    # 部分曲风（戏曲、中文喊麦）无下级分类，允许为空
    secondary_category: str | None = None
    tertiary_category: str | None = None
    season: str
    gender: Literal["女", "男", "男女", "女女", "男男", "多女（三人以上）", "多男（三人以上）", "多人有男有女（三人以上）"]
    age_group: str
    visual_style: str
    ratio: Literal["16:9", "9:16", "1:1", "4:3"] = "16:9"
    resolution: Literal["480p", "720p", "1080p"] = "720p"
    image_model: str = Field(default="gpt-image-2", min_length=1, max_length=160)
    video_model: str = Field(default="doubao-seedance-2.0", min_length=1, max_length=160)
    empty_shot_count: int = Field(ge=0, le=100)
    character_shot_count: int = Field(ge=0, le=100)
    total_duration: float = Field(gt=0, le=3600)
    digital_human_ids: list[str] = Field(default_factory=list)
    extra_requirement: str = Field(default="", max_length=20_000)
    overall_prompt: str = Field(default="", max_length=30_000)


class StoryboardLineGenerate(BaseModel):
    force: bool = False


class ChatSessionCreate(BaseModel):
    """system_prompt 留空时由后端以提示词注册中心的 chat.default_system 填充。"""

    system_prompt: str = Field(default="", max_length=30_000)


class ChatMessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class PortraitPromptParams(BaseModel):
    """数字人定妆照模式：prompt 由后端按注册中心模板拼装，前端只传原始参数。"""

    description: str = Field(default="", max_length=2_000)
    style: str = Field(default="", max_length=200)


class ImageGenerationCreate(BaseModel):
    # prompt 允许为空：portrait 模式下由后端用注册中心模板拼装（二者至少其一，端点内校验）
    prompt: str = Field(default="", max_length=20_000)
    size: str = "1024x1024"
    quality: Literal["auto", "low", "medium", "high"] = "auto"
    n: int = Field(default=1, ge=1, le=4)
    images: list[str] = Field(default_factory=list)
    model: str | None = Field(default=None, max_length=160)
    purpose: Literal["scene", "digital_human", "other"] = "other"
    portrait: PortraitPromptParams | None = None
    project_task_id: str | None = None
    storyboard_line_id: str | None = None


class VideoGenerationCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=30_000)
    duration: int = Field(default=DEFAULT_VIDEO_DURATION, ge=MIN_VIDEO_DURATION, le=MAX_VIDEO_DURATION)
    ratio: Literal["16:9", "9:16", "1:1", "4:3"] = "16:9"
    resolution: Literal["480p", "720p", "1080p"] = "720p"
    image_urls: list[str] = Field(default_factory=list)
    video_urls: list[str] = Field(default_factory=list)
    audio_urls: list[str] = Field(default_factory=list)
    generate_audio: bool = False
    watermark: bool = False
    model: str | None = Field(default=None, max_length=160)
    project_task_id: str | None = None
    storyboard_line_id: str | None = None


class GenerationStatusBatchRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)


class RemoteImportCreate(BaseModel):
    url: str
    category: str = "imports"
    filename: str | None = None
