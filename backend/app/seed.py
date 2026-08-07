from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update

from .database import session_factory
from .models import DigitalHumanModel, DigitalHumanStyleModel, SongEmotionProfileModel, StoryboardLineModel, utcnow
from .song_emotions import SONG_EMOTIONS
from .storage import TosStorage
from .system_humans import SYSTEM_HUMANS


async def seed_system_data() -> None:
    async with session_factory() as session:
        style_id = "style-system-library"
        style = await session.get(DigitalHumanStyleModel, style_id)
        if not style:
            style = DigitalHumanStyleModel(id=style_id, user_id=None, name="系统人物库", scope="system", sort_order=0)
            session.add(style)
        else:
            style.deleted_at = None
        await session.flush()

        desired_ids = {f"dh-system-{item['asset_code']}" for item in SYSTEM_HUMANS}
        old_humans = list((await session.execute(select(DigitalHumanModel).where(DigitalHumanModel.scope == "system", DigitalHumanModel.deleted_at.is_(None)))).scalars().all())
        for old in old_humans:
            if old.id not in desired_ids:
                old.deleted_at = utcnow()
        old_styles = list((await session.execute(select(DigitalHumanStyleModel).where(DigitalHumanStyleModel.scope == "system", DigitalHumanStyleModel.id != style_id, DigitalHumanStyleModel.deleted_at.is_(None)))).scalars().all())
        for old in old_styles:
            old.deleted_at = utcnow()

        for data in SYSTEM_HUMANS:
            human_id = f"dh-system-{data['asset_code']}"
            human = await session.get(DigitalHumanModel, human_id)
            bucket, object_key = TosStorage._bucket_for(f"system/digital-humans/{data['asset_code']}.png")
            avatar_url = TosStorage._public_url(bucket, object_key)
            if not human:
                human = DigitalHumanModel(
                    id=human_id, user_id=None, style_id=style.id, source="builtin", scope="system",
                    status="active", avatar_prompt=data["system_prompt"], description=data["appearance_style"],
                    avatar_url=avatar_url, **data,
                )
                session.add(human)
            else:
                human.style_id, human.deleted_at, human.status = style.id, None, "active"
                human.avatar_url, human.avatar_prompt, human.description = avatar_url, data["system_prompt"], data["appearance_style"]
                for key, value in data.items():
                    setattr(human, key, value)

        for song_code, payload in SONG_EMOTIONS.items():
            profile = await session.get(SongEmotionProfileModel, song_code)
            values = {
                "song_name": payload.get("歌名") or "", "artists": payload.get("歌星") or "",
                "primary_category": payload.get("一级分类"), "secondary_category": payload.get("二级分类"),
                "tertiary_category": payload.get("三级分类"), "material_category": payload.get("素材分类") or "",
                "seasons": payload.get("季节") or "", "atmosphere": payload.get("氛围基调") or "", "source_payload": payload,
            }
            if not profile:
                session.add(SongEmotionProfileModel(song_code=song_code, **values))
            else:
                profile.deleted_at = None
                for key, value in values.items():
                    setattr(profile, key, value)
        await session.commit()


async def recover_stale_storyboard_generation() -> None:
    """Return abandoned in-flight lines to the resumable queue after a restart."""
    cutoff = utcnow() - timedelta(minutes=10)
    async with session_factory() as session:
        await session.execute(
            update(StoryboardLineModel)
            .where(
                StoryboardLineModel.generation_status == "running",
                StoryboardLineModel.deleted_at.is_(None),
                StoryboardLineModel.updated_at < cutoff,
            )
            .values(generation_status="pending", generation_error="上次生成中断，已恢复等待队列")
        )
        await session.commit()
