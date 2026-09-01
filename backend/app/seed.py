from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_, select, update

from .config import settings
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
    ProjectTaskModel,
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
from .video_estimation import video_estimate_policy


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
            cast_policy = "required" if kind == "genre" and path in {"流行歌曲/爱情积极", "流行歌曲/爱情消极"} else None
            session.add(
                StoryboardOptionItemModel(
                    id=item_id,
                    kind=kind,
                    parent_id=parent_id,
                    name=name,
                    sort_order=sort_order,
                    cast_policy=cast_policy,
                )
            )
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
        ass_role = await session.get(AdminRoleModel, "admin-role-ass")
        if not ass_role:
            ass_role = AdminRoleModel(id="admin-role-ass", code="ass_admin", name="内容配置管理员", description="管理歌曲情感库与通用分类")
            session.add(ass_role)
        else:
            ass_role.name = "内容配置管理员"
            ass_role.description = "管理歌曲情感库与通用分类"
        permissions = [
            ("dashboard.read", "查看仪表盘"),
            ("users.manage", "管理用户"),
            ("models.manage", "管理模型"),
            ("assets.manage", "管理系统资产"),
            ("logs.read", "查看日志"),
            ("song_emotions.read", "查看 ASS 歌曲情感库"),
            ("song_emotions.manage", "管理 ASS 歌曲情感库"),
            ("storyboard_options.read", "查看通用分类"),
            ("storyboard_options.manage", "管理通用分类"),
        ]
        for code, name in permissions:
            pid = f"admin-perm-{code.replace('.', '-')}"
            permission = await session.get(AdminPermissionModel, pid)
            if not permission:
                permission = AdminPermissionModel(id=pid, code=code, name=name)
                session.add(permission)
            super_link = (
                await session.execute(
                    select(AdminRolePermissionModel).where(
                        AdminRolePermissionModel.role_id == role.id,
                        AdminRolePermissionModel.permission_id == pid,
                    )
                )
            ).scalar_one_or_none()
            if not super_link:
                session.add(AdminRolePermissionModel(id=f"arp-super-{code.replace('.', '-')}", role_id=role.id, permission_id=pid))
            if code.startswith(("song_emotions.", "storyboard_options.")):
                ass_link = (
                    await session.execute(
                        select(AdminRolePermissionModel).where(
                            AdminRolePermissionModel.role_id == ass_role.id,
                            AdminRolePermissionModel.permission_id == pid,
                        )
                    )
                ).scalar_one_or_none()
                if not ass_link:
                    session.add(AdminRolePermissionModel(id=f"arp-ass-{code.replace('.', '-')}", role_id=ass_role.id, permission_id=pid))
        admin = (await session.execute(select(UserModel).where(UserModel.username == "admin", UserModel.deleted_at.is_(None)))).scalar_one_or_none()
        if admin and not await session.get(UserAdminRoleModel, f"uar-super-{admin.id}"):
            legacy_link = await session.get(UserAdminRoleModel, f"uar-{admin.id}")
            if legacy_link:
                legacy_link.role_id = role.id
            else:
                session.add(UserAdminRoleModel(id=f"uar-super-{admin.id}", user_id=admin.id, role_id=role.id))
        provider = await session.get(AiProviderModel, "provider-yinghe")
        if not provider:
            provider = AiProviderModel(id="provider-yinghe", code="yinghe", name="银河 API", base_url="", status="active")
            session.add(provider)
        runninghub_provider = await session.get(AiProviderModel, "provider-runninghub")
        if not runninghub_provider:
            runninghub_provider = AiProviderModel(id="provider-runninghub", code="runninghub", name="RunningHub", base_url="", status="active")
            session.add(runninghub_provider)
        ppio_provider = await session.get(AiProviderModel, "provider-ppio")
        if not ppio_provider:
            ppio_provider = AiProviderModel(id="provider-ppio", code="ppio", name="PPIO", base_url="https://api.ppio.com", status="active")
            session.add(ppio_provider)
        defaults = [
            ("model-chat-default", provider.id, "chat-default", "默认 Chat 模型", "chat", "", {"structuredOutput": True}, True),
            ("model-img2", provider.id, "gpt-image-2", "Img2", "image", "gpt-image-2", {"ratios": ["16:9", "9:16", "4:3", "1:1"], "imageToImage": True}, True),
            (
                "model-sd20",
                provider.id,
                "doubao-seedance-2.0",
                "SD2.0（英和）",
                "video",
                "doubao-seedance-2.0",
                {
                    "durations": {"min": 4, "max": 15},
                    "ratios": ["16:9", "9:16", "4:3", "1:1"],
                    "executionPool": "yinghe-generation",
                    "executionConcurrency": 200,
                    "providerCode": "yinghe",
                    "billing": video_estimate_policy("doubao-seedance-2.0").capability(),
                    "sortOrder": 10,
                },
                True,
            ),
            (
                "model-h3-runninghub",
                runninghub_provider.id,
                "minimax-h3-runninghub",
                "H3（RunningHub，2并发，仅测试时用）",
                "video",
                "minimax-h3-ref2va",
                {
                    "durations": {"min": 4, "max": 15},
                    "ratios": ["16:9", "9:16", "4:3", "1:1"],
                    "resolutions": ["480p", "720p", "1080p"],
                    "resolutionLabels": {"720p": "736P"},
                    "providerResolutionMap": {
                        "480p": {"stage1": 0.2, "stage2": 0.4, "label": "0.4MP"},
                        "720p": {"stage1": 0.4, "stage2": 0.9, "label": "0.9MP"},
                        "1080p": {"stage1": 0.9, "stage2": 1.8, "label": "1.8MP"},
                    },
                    "variants": {
                        "t2va": {"images": {"min": 0, "max": 0}},
                        "i2va": {"images": {"min": 1, "max": 1}},
                        "fl2va": {"images": {"min": 2, "max": 2}},
                        "ref2va": {
                            "images": {"min": 0, "max": 6},
                            "videos": {"min": 0, "max": 1, "duration": {"min": 2, "max": 15, "totalMax": 15}},
                            "audios": {"min": 0, "max": 3, "duration": {"min": 2, "max": 15, "totalMax": 15}, "requiresVisual": True},
                            "totalFilesMax": 10,
                        },
                    },
                    "h3Modes": ["auto", "text", "first_frame", "first_last", "reference"],
                    "referenceImage": {"min": 0, "max": 6},
                    "referenceVideo": {"min": 0, "max": 1},
                    "referenceAudio": {"min": 0, "max": 3},
                    "referenceTotalMax": 10,
                    "referenceAudioRequiresVisual": True,
                    "workflowVersion": "runninghub-h3-official-fl2va-ref2va-v3",
                    "promptCompiler": "h3-prompt-writing",
                    "promptCompilerVersion": "1.1.0",
                    "nativeAudio": True,
                    "executionPool": "runninghub-h3",
                    "executionConcurrency": 2,
                    "providerCode": "runninghub",
                    "billing": video_estimate_policy("minimax-h3-runninghub").capability(),
                    "sortOrder": 50,
                },
                False,
            ),
            (
                "model-h3-direct",
                provider.id,
                "minimax-h3",
                "H3（英和）",
                "video",
                "MiniMax-H3",
                {
                    "durations": {"min": 4, "max": 15},
                    "ratios": ["16:9", "9:16", "4:3", "1:1"],
                    "resolutions": ["720p", "1080p"],
                    "resolutionLabels": {"720p": "768P", "1080p": "2K"},
                    "providerResolutionMap": {"720p": "768P", "1080p": "2K"},
                    "h3Modes": ["auto", "text", "first_frame", "first_last", "reference"],
                    "referenceImage": {"min": 0, "max": 6},
                    "referenceVideo": {"min": 0, "max": 1},
                    "referenceAudio": {"min": 0, "max": 3},
                    "referenceTotalMax": 10,
                    "referenceAudioRequiresVisual": True,
                    "workflowVersion": "minimax-h3-direct-v1",
                    "promptCompiler": "h3-prompt-writing",
                    "promptCompilerVersion": "1.2.0",
                    "nativeAudio": True,
                    "executionPool": "yinghe-h3",
                    "executionConcurrency": 200,
                    "providerCode": "yinghe",
                    "billing": video_estimate_policy("minimax-h3").capability(),
                    "sortOrder": 20,
                },
                False,
            ),
            (
                "model-sd20-ppio",
                ppio_provider.id,
                "doubao-seedance-2.0-ppio",
                "SD2.0（PPIO）",
                "video",
                "doubao-seedance-2-0-260128",
                {
                    "durations": {"min": 4, "max": 15},
                    "ratios": ["16:9", "9:16", "4:3", "1:1"],
                    "resolutions": ["480p", "720p", "1080p"],
                    "nativeAudio": True,
                    "executionPool": "ppio-seedance",
                    "executionConcurrency": 200,
                    "providerCode": "ppio",
                    "billing": video_estimate_policy("doubao-seedance-2.0-ppio").capability(),
                    "sortOrder": 30,
                },
                False,
            ),
            (
                "model-h3-ppio",
                ppio_provider.id,
                "minimax-h3-ppio",
                "H3（PPIO）",
                "video",
                "MiniMax-H3",
                {
                    "durations": {"min": 4, "max": 15},
                    "ratios": ["16:9", "9:16", "4:3", "1:1"],
                    "resolutions": ["720p", "1080p"],
                    "resolutionLabels": {"720p": "768P", "1080p": "2K"},
                    "providerResolutionMap": {"720p": "768P", "1080p": "2K"},
                    "h3Modes": ["auto", "text", "first_frame", "first_last", "reference"],
                    "referenceImage": {"min": 0, "max": 6},
                    "referenceVideo": {"min": 0, "max": 1},
                    "referenceAudio": {"min": 0, "max": 3},
                    "referenceTotalMax": 10,
                    "referenceAudioRequiresVisual": True,
                    "workflowVersion": "minimax-h3-ppio-v1",
                    "promptCompiler": "h3-prompt-writing",
                    "promptCompilerVersion": "1.2.0",
                    "nativeAudio": True,
                    "executionPool": "ppio-h3",
                    "executionConcurrency": 200,
                    "providerCode": "ppio",
                    "billing": video_estimate_policy("minimax-h3-ppio").capability(),
                    "sortOrder": 40,
                },
                False,
            ),
        ]
        for mid, model_provider_id, code, name, modality, provider_id, capabilities, is_default in defaults:
            if code in {"doubao-seedance-2.0", "minimax-h3-runninghub", "minimax-h3", "doubao-seedance-2.0-ppio", "minimax-h3-ppio"}:
                capabilities = {**capabilities, "systemManaged": True}
            ppio_model_enabled = not code.endswith("-ppio") or bool(settings.ppio_api_key) or settings.app_env != "production"
            model = await session.get(AiModelModel, mid)
            if not model:
                session.add(
                    AiModelModel(
                        id=mid,
                        provider_id=model_provider_id,
                        code=code,
                        name=name,
                        modality=modality,
                        provider_model_id=provider_id or code,
                        capabilities=capabilities,
                        status="active" if ppio_model_enabled else "inactive",
                        user_visible=True,
                        is_default=is_default,
                    )
                )
            elif code in {"doubao-seedance-2.0", "minimax-h3-runninghub", "minimax-h3", "doubao-seedance-2.0-ppio", "minimax-h3-ppio"}:
                # 模型能力属于系统种子配置；启动时同步升级已有环境，避免仅新库生效。
                model.name = name
                model.provider_model_id = provider_id or code
                model.capabilities = capabilities
                # 系统维护协议与能力；管理员维护启停和可见性，重启不得撤销人工操作。
                if not ppio_model_enabled:
                    model.status = "inactive"
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
                # 已存在的系统人物可能已由受控迁移切换到版本化 TOS 对象；重启时
                # 只补缺失值，不能把新造型回滚到安装包内置旧地址。
                if not human.avatar_url:
                    human.avatar_url = avatar_url
                if not human.avatar_thumbnail_url:
                    human.avatar_thumbnail_url = thumbnail_url
                # 系统人物重制后会重新注册供应商资产；启动 seed 不得用代码中的历史
                # asset:// 覆盖数据库里已经切换完成的新资产。仅为旧库缺失字段兜底。
                if not human.asset_avatar_url:
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
                "lyrics": payload.get("歌词") or "",
                "primary_category": payload.get("一级分类"),
                "secondary_category": payload.get("二级分类"),
                "tertiary_category": payload.get("三级分类"),
                "material_category": payload.get("素材分类") or "",
                "seasons": payload.get("季节") or "",
                "atmosphere": payload.get("氛围基调") or "",
                "character_setting": payload.get("人物设定") or "",
                "status": int(payload.get("状态") or 2),
                "source_payload": payload,
            }
            # 曲库在首次部署时由静态文件初始化；一旦入库即由管理后台维护。
            # 已存在记录（包括软删除记录）绝不能在重启时被覆盖或复活。
            if not profile:
                session.add(SongEmotionProfileModel(song_code=song_code, **values))
        await seed_prompts(session)
        await seed_storyboard_options(session)
        await session.commit()


async def ensure_pending_asset_avatars() -> None:
    """补齐数字人在英合和 PPIO 两个账号下的 asset://，供 cron 幂等执行。"""
    import asyncio

    from .providers import create_ppio_synthetic_image_asset, create_real_face_asset

    async with session_factory() as session:
        pending = (
            (
                await session.execute(
                    select(DigitalHumanModel).where(
                        DigitalHumanModel.deleted_at.is_(None),
                        or_(DigitalHumanModel.asset_avatar_url.is_(None), DigitalHumanModel.ppio_asset_avatar_url.is_(None)),
                        DigitalHumanModel.avatar_url.isnot(None),
                        DigitalHumanModel.avatar_url != "",
                    )
                )
            )
            .scalars()
            .all()
        )
    semaphore = asyncio.Semaphore(4)

    async def sync_human(human: DigitalHumanModel) -> None:
        registrations = []
        if human.asset_avatar_url is None:
            registrations.append(("yinghe", "asset_avatar_url", "/v3/assets", create_real_face_asset(human.avatar_url, name=f"mv-{human.asset_code or human.id}")))
        if human.ppio_asset_avatar_url is None:
            registrations.append(("ppio", "ppio_asset_avatar_url", "/v3/synthetic-cn/bytedance/ark", create_ppio_synthetic_image_asset(human.avatar_url)))
        async with semaphore:
            results = await asyncio.gather(*(call for _, _, _, call in registrations), return_exceptions=True)
        async with session_factory() as session:
            current = await session.get(DigitalHumanModel, human.id)
            if not current:
                return
            changed = False
            for (provider, field, path, _), result in zip(registrations, results, strict=True):
                if isinstance(result, Exception):
                    await log_background_error(
                        user_id=human.user_id,
                        path=path,
                        error_type="AssetError",
                        message=f"digital human {provider} asset create failed: {human.id}: {result}",
                    )
                    continue
                if getattr(current, field) is None:
                    setattr(current, field, result)
                    changed = True
            if changed:
                await session.commit()

    await asyncio.gather(*(sync_human(human) for human in pending))


async def recover_stale_storyboard_generation() -> None:
    """收编已丢失执行协程的大纲和逐句生成任务。"""
    cutoff = utcnow() - timedelta(minutes=10)
    outline_cutoff = utcnow() - timedelta(minutes=5)
    inline_replay_ids: list[str] = []
    async with session_factory() as session:
        active_outline_job = (
            select(GenerationJobModel.id)
            .where(
                GenerationJobModel.project_task_id == ProjectTaskModel.id,
                GenerationJobModel.kind.in_(("ass_outline", "general_outline")),
                GenerationJobModel.status.in_(("queued", "running")),
                GenerationJobModel.deleted_at.is_(None),
            )
            .exists()
        )
        stale_outlines = list(
            (
                await session.execute(
                    select(ProjectTaskModel).where(
                        ProjectTaskModel.status == "outlining",
                        ProjectTaskModel.deleted_at.is_(None),
                        ProjectTaskModel.updated_at < outline_cutoff,
                        ~active_outline_job,
                    )
                )
            )
            .scalars()
            .all()
        )
        for task in stale_outlines:
            config = dict(task.storyboard_config or {})
            progress = dict(config.get("outlineProgress") or {})
            progress.update(phase="error", error="大纲生成进程已中断，请重新生成大纲")
            config["outlineProgress"] = progress
            task.storyboard_config = config
            task.status = "outline_failed"
        # A worker may have persisted a terminal job while its line-level failure
        # transaction was rolled back (for example the historical deadlock bug).
        # Reconcile those stale "running" rows from the durable latest job in every
        # execution mode so the UI never spins forever.
        stale_running_lines = list(
            (
                await session.execute(
                    select(StoryboardLineModel).where(
                        StoryboardLineModel.generation_status == "running",
                        StoryboardLineModel.deleted_at.is_(None),
                        StoryboardLineModel.updated_at < cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )
        stale_line_ids = [line.id for line in stale_running_lines]
        recent_jobs = list(
            (
                await session.execute(
                    select(GenerationJobModel)
                    .where(
                        GenerationJobModel.storyboard_line_id.in_(stale_line_ids) if stale_line_ids else False,
                        GenerationJobModel.kind == "storyboard_line",
                        GenerationJobModel.deleted_at.is_(None),
                    )
                    .order_by(GenerationJobModel.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        latest_job_by_line: dict[str, GenerationJobModel] = {}
        for recent_job in recent_jobs:
            if recent_job.storyboard_line_id:
                latest_job_by_line.setdefault(recent_job.storyboard_line_id, recent_job)
        affected_task_ids: set[str] = set()
        for line in stale_running_lines:
            terminal_job = latest_job_by_line.get(line.id)
            if not terminal_job or terminal_job.status not in {"failed", "cancelled", "succeeded"}:
                continue
            affected_task_ids.add(line.project_task_id)
            if terminal_job.status == "succeeded" and line.scene_prompt and line.shot_prompt:
                line.generation_status, line.generation_error = "succeeded", None
            else:
                line.generation_status = "failed"
                line.generation_error = (terminal_job.error or "上次提示词生成失败，请重新生成")[:2000]
        for task_id in affected_task_ids:
            task = await session.get(ProjectTaskModel, task_id)
            if not task or task.deleted_at is not None:
                continue
            statuses = list(
                (
                    await session.execute(
                        select(StoryboardLineModel.generation_status).where(
                            StoryboardLineModel.project_task_id == task_id,
                            StoryboardLineModel.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if statuses and all(value == "succeeded" for value in statuses):
                task.status = "ready"
            elif any(value == "succeeded" for value in statuses) and any(value == "failed" for value in statuses):
                task.status = "partial"
            elif statuses and all(value == "failed" for value in statuses):
                task.status = "failed"
            else:
                task.status = "generating"
            config = dict(task.storyboard_config or {})
            progress = dict(config.get("outlineProgress") or {})
            progress_job_id = str(progress.get("jobId") or "")
            if any(job.id == progress_job_id and job.status in {"failed", "cancelled", "succeeded"} for job in recent_jobs):
                progress.pop("error", None)
                progress.pop("jobId", None)
                progress["phase"] = "complete"
                config["outlineProgress"] = progress
                task.storyboard_config = config
        # Worker 模式由租约恢复器接管逐镜工单，API 启动不能抢先把可重放任务判失败。
        if settings.job_execution_mode != "worker":
            stale_jobs = list(
                (
                    await session.execute(
                        select(GenerationJobModel).where(
                            GenerationJobModel.kind == "storyboard_line",
                            GenerationJobModel.status.in_(("queued", "running")),
                            GenerationJobModel.deleted_at.is_(None),
                            GenerationJobModel.updated_at < cutoff,
                        )
                    )
                ).scalars()
            )
            replayable_line_ids: set[str] = set()
            for job in stale_jobs:
                request = dict(job.request or {})
                if job.attempt < 3 and request.get("full_context") is not None and request.get("allowed_humans") is not None:
                    job.status, job.phase, job.error = "queued", "queued", None
                    job.started_at = job.finished_at = None
                    job.worker_id = None
                    job.attempt += 1
                    inline_replay_ids.append(job.id)
                    if job.storyboard_line_id:
                        replayable_line_ids.add(job.storyboard_line_id)
                else:
                    job.status = "failed"
                    job.error = "上次生成中断，可重新生成"
                    job.finished_at = utcnow()
            await session.execute(
                update(StoryboardLineModel)
                .where(
                    StoryboardLineModel.generation_status == "running",
                    StoryboardLineModel.deleted_at.is_(None),
                    StoryboardLineModel.updated_at < cutoff,
                    ~StoryboardLineModel.id.in_(replayable_line_ids) if replayable_line_ids else True,
                )
                .values(generation_status="pending", generation_error="上次生成中断，已恢复等待队列")
            )
        await session.commit()
    if inline_replay_ids:
        # 延迟导入避免 seed/domain 初始化环；inline 与外部 Worker 共用同一个快照 runner。
        from .domain import run_storyboard_job
        from .jobs import jobs

        for job_id in inline_replay_ids:
            if job := await jobs.get(job_id):
                await jobs.dispatch(job, run_storyboard_job)
