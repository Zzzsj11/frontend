from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update

from .database import session_factory
from .error_logging import log_background_error
from .models import (
    AdminPermissionModel,
    AdminRoleModel,
    AdminRolePermissionModel,
    AiModelModel,
    AiProviderModel,
    DigitalHumanModel,
    DigitalHumanStyleModel,
    GenerationJobModel,
    PromptTemplateModel,
    PromptVersionModel,
    SongEmotionProfileModel,
    StoryboardLineModel,
    StoryboardOptionItemModel,
    UserAdminRoleModel,
    UserModel,
    utcnow,
)
from .prompts import DEFAULT_PROMPTS
from .song_emotions import SONG_EMOTIONS
from .storage import TosStorage
from .storyboard_options import (
    DEFAULT_AGE_GROUPS,
    DEFAULT_GENRE_TREE,
    DEFAULT_SEASONS,
    DEFAULT_VISUAL_STYLES,
    seed_item_id,
)
from .system_humans import SYSTEM_HUMAN_ASSET_URLS, SYSTEM_HUMANS


async def seed_prompts(session) -> None:
    """内置提示词模板入库（幂等）：仅补缺；已存在的 key 不覆盖，保护后台已编辑内容。"""
    for key, spec in DEFAULT_PROMPTS.items():
        existing = (await session.execute(select(PromptTemplateModel).where(PromptTemplateModel.key == key))).scalar_one_or_none()
        if existing:
            continue
        template_id = f"pt-{key}"
        version_id = f"pv-{key}-v1"
        session.add(
            PromptVersionModel(
                id=version_id,
                template_id=template_id,
                version=1,
                content=spec["content"],
                change_note="内置默认",
                status="published",
                created_by="system",
                published_at=utcnow(),
            )
        )
        session.add(
            PromptTemplateModel(
                id=template_id,
                key=key,
                name=spec["name"],
                description=spec.get("description", ""),
                engine=spec.get("engine", "llm"),
                format=spec.get("format", "text"),
                variables=spec.get("variables", {}),
                required_fragments=spec.get("required_fragments", []),
                current_version_id=version_id,
                status="active",
            )
        )


async def seed_storyboard_options(session) -> None:
    """通用分镜选项入库（幂等）：仅补缺；记录已存在（含被后台软删）则跳过，保护后台编辑与删除。"""

    async def add_item(kind: str, name: str, parent_id: str | None, path: str, sort_order: int) -> str:
        item_id = seed_item_id(kind, path)
        if not await session.get(StoryboardOptionItemModel, item_id):
            session.add(StoryboardOptionItemModel(id=item_id, kind=kind, parent_id=parent_id, name=name, sort_order=sort_order))
        return item_id

    for index, name in enumerate(DEFAULT_SEASONS):
        await add_item("season", name, None, name, index)
    for index, name in enumerate(DEFAULT_AGE_GROUPS):
        await add_item("age_group", name, None, name, index)
    for index, name in enumerate(DEFAULT_VISUAL_STYLES):
        await add_item("visual_style", name, None, name, index)

    async def walk_genre(children: list, parent_id: str | None, parent_path: str) -> None:
        for index, child in enumerate(children):
            name, grandchildren = child if isinstance(child, tuple) else (child, [])
            path = f"{parent_path}/{name}" if parent_path else name
            child_id = await add_item("genre", name, parent_id, path, index)
            if grandchildren:
                await walk_genre(grandchildren, child_id, path)

    await walk_genre(DEFAULT_GENRE_TREE, None, "")


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
        system_style_specs = [
            ("style-system-male", "男", 0),
            ("style-system-female", "女", 1),
            ("style-system-child", "儿童", 2),
        ]
        system_styles = {}
        for style_id, style_name, sort_order in system_style_specs:
            style = await session.get(DigitalHumanStyleModel, style_id)
            if not style:
                style = DigitalHumanStyleModel(id=style_id, user_id=None, name=style_name, scope="system", sort_order=sort_order)
                session.add(style)
            else:
                style.name, style.scope, style.sort_order, style.deleted_at = style_name, "system", sort_order, None
            system_styles[style_name] = style
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
                        DigitalHumanStyleModel.scope == "system",
                        DigitalHumanStyleModel.id.not_in([item[0] for item in system_style_specs]),
                        DigitalHumanStyleModel.deleted_at.is_(None),
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
            style = system_styles[data["category"]]
            bucket, object_key = TosStorage._bucket_for(f"system/digital-humans/{data['asset_code']}.jpg")
            avatar_url = TosStorage._public_url(bucket, object_key)
            thumbnail_bucket, thumbnail_key = TosStorage._bucket_for(f"system/digital-humans/thumbnails/{data['asset_code']}.jpg")
            thumbnail_url = TosStorage._public_url(thumbnail_bucket, thumbnail_key)
            # 平台虚拟资产链接已注册并固化，seed 直接写入（asset:// 由平台托管，跨环境通用）
            asset_avatar_url = SYSTEM_HUMAN_ASSET_URLS.get(data["asset_code"])
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
                    asset_avatar_url=asset_avatar_url,
                    **{key: value for key, value in data.items() if key != "category"},
                )
                session.add(human)
            else:
                human.style_id, human.deleted_at, human.status = style.id, None, "active"
                human.avatar_url, human.avatar_thumbnail_url = avatar_url, thumbnail_url
                human.asset_avatar_url = asset_avatar_url
                human.avatar_prompt, human.description = data["system_prompt"], data["appearance_style"]
                for key, value in data.items():
                    if key == "category":
                        continue
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
        await seed_prompts(session)
        await seed_storyboard_options(session)
        await session.commit()


async def ensure_pending_asset_avatars() -> None:
    """为尚无 asset:// 链接的数字人（系统 + 用户上传）注册 AIGC 平台虚拟资产（幂等，启动后台执行）。

    数字人头像注册到平台后返回 asset:// 链接，生成视频时用它替代原始 TOS 路径，
    可绕过上游对真实人物的直接检测；创建失败只记日志，不影响启动与原有 TOS 路径可用性，
    下次启动会继续补注册（创建接口同步失败的用户头像由此兜底）。
    """
    from .providers import create_real_face_asset

    async with session_factory() as session:
        pending = (
            (
                await session.execute(
                    select(DigitalHumanModel).where(
                        DigitalHumanModel.deleted_at.is_(None),
                        DigitalHumanModel.asset_avatar_url.is_(None),
                        DigitalHumanModel.avatar_url.isnot(None),
                        DigitalHumanModel.avatar_url != "",
                    )
                )
            )
            .scalars()
            .all()
        )
    for human in pending:
        try:
            asset_url = await create_real_face_asset(human.avatar_url, name=f"mv-{human.asset_code or human.id}")
        except Exception as exc:
            await log_background_error(
                user_id=human.user_id,
                path="/virtual/assets/create",
                error_type="AssetError",
                message=f"digital human asset create failed: {human.id}: {exc}",
            )
            continue
        async with session_factory() as session:
            current = await session.get(DigitalHumanModel, human.id)
            if current and current.asset_avatar_url is None:
                current.asset_avatar_url = asset_url
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
        # 同步收编 generation_jobs 里的分镜行僵尸任务（行表恢复后，任务表不能永远停 running）
        await session.execute(
            update(GenerationJobModel)
            .where(
                GenerationJobModel.kind == "storyboard_line",
                GenerationJobModel.status.in_(("queued", "running")),
                GenerationJobModel.deleted_at.is_(None),
                GenerationJobModel.updated_at < cutoff,
            )
            .values(status="failed", error="上次生成中断，可重新生成", finished_at=utcnow())
        )
        await session.commit()
