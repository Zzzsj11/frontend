from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update

from .database import session_factory
from .models import (
    AdminPermissionModel,
    AdminRoleModel,
    AdminRolePermissionModel,
    AiModelModel,
    AiProviderModel,
    DigitalHumanModel,
    DigitalHumanStyleModel,
    SongEmotionProfileModel,
    StoryboardLineModel,
    UserAdminRoleModel,
    UserModel,
    utcnow,
)
from .song_emotions import SONG_EMOTIONS
from .storage import TosStorage
from .system_humans import SYSTEM_HUMANS


async def seed_system_data() -> None:
    async with session_factory() as session:
        role = await session.get(AdminRoleModel, "admin-role-super")
        if not role:
            role = AdminRoleModel(id="admin-role-super", code="super_admin", name="超级管理员", description="拥有全部后台权限")
            session.add(role)
        for code, name in [
            ("dashboard.read", "查看仪表盘"),
            ("users.manage", "管理用户"),
            ("models.manage", "管理模型"),
            ("assets.manage", "管理系统资产"),
            ("logs.read", "查看日志"),
        ]:
            pid = f"admin-perm-{code.replace('.', '-')}"
            permission = await session.get(AdminPermissionModel, pid)
            if not permission:
                permission = AdminPermissionModel(id=pid, code=code, name=name)
                session.add(permission)
                session.add(AdminRolePermissionModel(id=f"arp-{code.replace('.', '-')}", role_id=role.id, permission_id=pid))
        admin = (await session.execute(select(UserModel).where(UserModel.username == "admin", UserModel.deleted_at.is_(None)))).scalar_one_or_none()
        if admin and not await session.get(UserAdminRoleModel, f"uar-{admin.id}"):
            session.add(UserAdminRoleModel(id=f"uar-{admin.id}", user_id=admin.id, role_id=role.id))
        provider = await session.get(AiProviderModel, "provider-yinghe")
        if not provider:
            provider = AiProviderModel(id="provider-yinghe", code="yinghe", name="银河 API", base_url="", status="active")
            session.add(provider)
        defaults = [
            ("model-chat-default", "chat-default", "默认 Chat 模型", "chat", "", {"structuredOutput": True}),
            ("model-img2", "gpt-image-2", "Img2", "image", "gpt-image-2", {"ratios": ["16:9", "9:16", "4:3", "1:1"], "imageToImage": True}),
            ("model-sd20", "doubao-seedance-2.0", "SD2.0", "video", "doubao-seedance-2.0", {"durations": {"min": 4, "max": 15}, "ratios": ["16:9", "9:16", "4:3", "1:1"]}),
        ]
        for mid, code, name, modality, provider_id, capabilities in defaults:
            model = await session.get(AiModelModel, mid)
            if not model:
                session.add(
                    AiModelModel(
                        id=mid,
                        provider_id=provider.id,
                        code=code,
                        name=name,
                        modality=modality,
                        provider_model_id=provider_id or code,
                        capabilities=capabilities,
                        status="active",
                        user_visible=True,
                        is_default=True,
                    )
                )
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
        old_styles = list(
            (
                await session.execute(
                    select(DigitalHumanStyleModel).where(
                        DigitalHumanStyleModel.scope == "system", DigitalHumanStyleModel.id != style_id, DigitalHumanStyleModel.deleted_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        for old in old_styles:
            old.deleted_at = utcnow()

        for data in SYSTEM_HUMANS:
            human_id = f"dh-system-{data['asset_code']}"
            human = await session.get(DigitalHumanModel, human_id)
            bucket, object_key = TosStorage._bucket_for(f"system/digital-humans/{data['asset_code']}.jpg")
            avatar_url = TosStorage._public_url(bucket, object_key)
            thumbnail_bucket, thumbnail_key = TosStorage._bucket_for(f"system/digital-humans/thumbnails/{data['asset_code']}.jpg")
            thumbnail_url = TosStorage._public_url(thumbnail_bucket, thumbnail_key)
            if not human:
                human = DigitalHumanModel(
                    id=human_id,
                    user_id=None,
                    style_id=style.id,
                    source="builtin",
                    scope="system",
                    status="active",
                    avatar_prompt=data["system_prompt"],
                    description=data["appearance_style"],
                    avatar_url=avatar_url,
                    avatar_thumbnail_url=thumbnail_url,
                    **data,
                )
                session.add(human)
            else:
                human.style_id, human.deleted_at, human.status = style.id, None, "active"
                human.avatar_url, human.avatar_thumbnail_url = avatar_url, thumbnail_url
                human.avatar_prompt, human.description = data["system_prompt"], data["appearance_style"]
                for key, value in data.items():
                    setattr(human, key, value)

        for song_code, payload in SONG_EMOTIONS.items():
            profile = await session.get(SongEmotionProfileModel, song_code)
            values = {
                "song_name": payload.get("歌名") or "",
                "artists": payload.get("歌星") or "",
                "primary_category": payload.get("一级分类"),
                "secondary_category": payload.get("二级分类"),
                "tertiary_category": payload.get("三级分类"),
                "material_category": payload.get("素材分类") or "",
                "seasons": payload.get("季节") or "",
                "atmosphere": payload.get("氛围基调") or "",
                "source_payload": payload,
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
