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


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    role: Literal["admin", "user"] | None = None
    status: Literal["active", "disabled"] | None = None


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
    secondary_category: str
    tertiary_category: str | None = None
    season: str
    singer: str | None = None
    age_group: str
    visual_style: str
    ratio: Literal["16:9", "9:16", "1:1", "4:3"] = "16:9"
    empty_shot_count: int = Field(ge=0, le=100)
    character_shot_count: int = Field(ge=0, le=100)
    total_duration: float = Field(gt=0, le=3600)
    digital_human_ids: list[str] = Field(default_factory=list)
    extra_requirement: str = Field(default="", max_length=20_000)
    overall_prompt: str = Field(default="", max_length=30_000)


class StoryboardLineGenerate(BaseModel):
    force: bool = False


class ChatSessionCreate(BaseModel):
    system_prompt: str = "你是 MV 制作助手，帮助用户规划分镜、场景、角色和视频生成提示词。"


class ChatMessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class ImageGenerationCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    size: str = "1024x1024"
    quality: Literal["auto", "low", "medium", "high"] = "auto"
    n: int = Field(default=1, ge=1, le=4)
    images: list[str] = Field(default_factory=list)
    model: str | None = None
    purpose: Literal["scene", "digital_human", "other"] = "other"
    project_task_id: str | None = None
    storyboard_line_id: str | None = None


class VideoGenerationCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=30_000)
    duration: int = Field(default=DEFAULT_VIDEO_DURATION, ge=MIN_VIDEO_DURATION, le=MAX_VIDEO_DURATION)
    ratio: Literal["16:9", "9:16", "1:1", "4:3"] = "16:9"
    image_urls: list[str] = Field(default_factory=list)
    generate_audio: bool = False
    watermark: bool = False
    model: str | None = None
    project_task_id: str | None = None
    storyboard_line_id: str | None = None


class RemoteImportCreate(BaseModel):
    url: str
    category: str = "imports"
    filename: str | None = None
