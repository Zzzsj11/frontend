# 数字人资产与真人人脸校验说明（asset:// 虚拟资产链路）

> 写给接手开发的程序员 / code-agent。本文档说明人物素材（数字人）图片的存储方式、上游 AIGC 平台的真人人脸校验问题，以及 `asset://` 虚拟资产机制的完整链路：谁在注册、存在哪、生成视频时怎么用、失败了怎么兜底。

## 1. 背景：真人人脸校验问题

人物身份图统一生成 **1024×1536 竖版单人正面头肩大头照**，保留白色圆领 T 恤、
中性灰背景、无饰品的中性造型，完整保留头顶和发型；儿童不成人化、卡通不强制真人化。
默认使用英和 `gpt-image-2.5-sunburst`，可通过 `DIGITAL_HUMAN_IMAGE_MODEL` 覆盖；
显式指定的模型保持优先，模型默认值在创建工单前写入请求快照，Worker 与用量记录使用同一模型。

不再依赖系统人物 001 或其他版式模板。有参考图时只提交一张人物身份原图，私有重生成优先使用
`originalAvatar`；无图时省略 `images`，不使用姓名占位图或系统人物脸兜底。
提示词只接收身份特征，空描述不得回退到人物名称（如“女10”）；资产分类 `style` 只用于归档，不入画。

上传入口依次完成参考图上传 TOS（可选）、创建生图工单、统一轮询、将生成原图及缩略图入库，
最后注册英和资产；不再同步其他渠道的人物资产。`mv:pending-dh` 保存待完成的创建工单，
刷新后等待原工单再入库，不重新提交生图。创建成功只加入资产库，角色阵容仍由用户手动选择。
私有重生成须在 PATCH 成功后才替换本地头像；失败保留旧图及重试入口。系统人物在用户端始终只读。

资产库预览框采用 2:3 比例，完整显示新头肩照；`CharacterPortrait` 对宽高比 ≥1.5 的历史横版身份卡
保留左侧正脸裁切，对新竖图和方图使用居中靠上展示，更换图片后重新判断。
该策略按比例识别，宽幅单人照片也会被视为旧卡。私有旧图不批量迁移，
用户可在详情中手动重新生成；系统人物的受控重生成步骤见 §11。

上游 AIGC 平台（`api-aigc.fzyinghe.com`）在**生成视频**时，会对传入的参考图做人脸检测。如果图片被判定为真实人物，任务直接失败：

```
The request failed because the input image 'content[1]' 'content[2]' may contain real person. Request id: xxx
```

- 后端已把这类英文报错翻译为中文友好提示（见 §6 providers.py `translate_provider_error`），前端直接展示翻译后的文案
- 解决思路参考自 `/Users/local-agent/xwrj/chouka-tools` 项目：先把人物图注册为 AIGC 平台的**虚拟资产**，生成视频时传 `asset://{id}` 引用平台内部已托管素材，从而绕过对原始 URL 图片的直接人脸检测

## 2. 关键概念

| 概念          | 说明                                                                                                                                      |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| TOS 路径      | 原始图片地址（火山引擎对象存储 `media-generate-chouka.tos-cn-beijing.volces.com`），用于前端展示、素材导出等，**永远保留不变**            |
| asset:// 链接 | `asset://asset-xxxxxxxx`，AIGC 平台虚拟资产的引用形式；图片上传到平台后被平台托管（转移到平台自己的存储），生成视频时引用它不触发人脸检测 |
| 字段映射      | `asset_avatar_url` 存英合链接；`avatar_url` / `avatar_thumbnail_url` 始终保留 TOS 路径              |

## 3. 虚拟资产注册 API（AIGC 平台 V3）

素材接口（实现见 `backend/app/providers.py::create_real_face_asset`）：

0. **创建素材组**（一次性，换账户/key 时才需要）：`POST {VIDEO_API_BASE_URL}/v3/asset-groups`，body `{"name": "...", "description": "..."}`，返回 `data.groupId`。素材组按 API Key 所属账户隔离，上传/查询/删除素材时作为 `group_id` 请求头传入。
1. **创建**：`POST {VIDEO_API_BASE_URL}/v3/assets`
   ```json
   {
     "url": "<图片公开URL>",
     "name": "mv-001",
     "assetType": "Image"
   }
   ```
   请求头除 `Authorization: Bearer {VIDEO_API_KEY}` 外，**必须带 `group_id: group-xxxxxxxx`**（配置项 `AIGC_ASSET_GROUP_ID`，当前为 `group-20260817142427-1cfe75`「Seedance 虚拟人物素材」）。返回 `data.id`（状态 Processing）。V3 仅支持虚拟人像素材，**无 Moderation 参数**（旧版 `/virtual/assets/create` 在 CN region 需降级重试的问题不复存在）。
2. **轮询详情**：`POST /v3/assets/detail`，body `{"assetId": "..."}`，间隔 3 秒轮询直到 `status == "Active"`；`Rejected` / `Failed` 视为审核失败；超过 180 秒判超时。

> 2026-08-17 迁移至 V3：旧版 `/virtual/assets/*` 与 `/video/generation/tasks/*` 已停用（素材通道按 key 授权，旧 key 未获 V3 授权）。当前使用 key `yh-ftbq...`（VIDEO_API_KEY/IMAGE_API_KEY），视频任务走 `POST /v3/video/tasks`（Seedance 官方报文：创建返回 `id`，轮询 `GET /v3/video/tasks/{id}`，结果在 `content.video_url` / `content.last_frame_url`，失败原因在 `error.message`），请求带 `return_last_frame: true` 直接拿尾帧做封面。两套体系的素材库不互通，换 key/迁 V3 后所有数字人必须重新注册资产。

## 4. 数据链路：三个入库路径 + 两层兜底

### 4.1 入库路径（人物入库时如何拿到 asset）

| 路径                    | 代码位置                                              | asset 处理                                                                                                |
| ----------------------- | ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| 系统人物 seed（32 个）  | `seed.py::seed_system_data`                           | 直接写入固化的 `SYSTEM_HUMAN_ASSET_URLS` 映射（`system_humans.py`），**100% 带 asset，无需注册等待**      |
| 用户上传/生成数字人     | `domain.py::create_human`（POST /api/digital-humans） | 入库后调 `_sync_human_asset_avatar()` **同步注册**（30 秒超时保护，接口多等 3-6 秒），成功写入 asset 链接 |
| 数字人换图/重新生成形象 | `domain.py::update_human`（PATCH，avatar_url 变化）   | **旧 asset 清空**（旧链接对应旧图，必须失效）→ 用新图重新注册                                             |

> 注意：`/api/uploads` 与 `/api/uploads/import` 只是图片文件上传，不创建数字人记录，不走 asset 流程。

### 4.2 兜底体系（两层，注册失败不阻断）

1. **入库时同步注册**：创建/换图时立即注册；失败只记错误日志（`api_error_logs`，error_type=AssetError），人物正常入库，`asset_avatar_url` 留空，生成视频降级用 TOS 路径（可能撞人脸校验）
2. **cron 每分钟补扫**：独立脚本 `backend/scripts/ensure_asset_avatars.py`，每分钟补齐英合缺失资产（复用 `seed.py::ensure_pending_asset_avatars()`），使临时注册失败可自动恢复

> 注：曾有过"服务启动时再扫一次"的第三层，与 cron 功能重复且无防重入锁（可能与 cron 并发导致同一人物重复注册资产），已移除。补注册统一由 cron 负责，部署新环境时务必同步配置 crontab（见 §5）。

## 5. cron 脚本部署详情

脚本：`backend/scripts/ensure_asset_avatars.py`

- 逻辑：统计活跃且 `asset_avatar_url IS NULL` 的数字人 → 有缺失就逐个注册 → 打印 `handled N pending human(s)`
- 幂等 + 防重入（fcntl 文件锁 `/tmp/mvagent-asset-sync.lock`，同一时刻只允许一个同步进程）

crontab 配置（**宿主机**上，每分钟）：

| 环境           | 命令                                                                                                         | 日志                                                            |
| -------------- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------- |
| 本地（macOS）  | `/usr/local/bin/docker exec mv-agent-frontend-backend-1 python /srv/mvagent/scripts/ensure_asset_avatars.py` | `/tmp/mvagent-asset-sync.log`                                   |
| 线上（Ubuntu） | `PROJECT_DIR=/opt/mv-agent-frontend /opt/mv-agent-frontend/scripts/sync-digital-human-assets.sh`             | `/var/lib/docker/mv-agent-maintenance/logs/asset-sync-cron.log` |

容器内脚本路径：`/srv/mvagent/scripts/ensure_asset_avatars.py`（容器内无 scripts 目录时需要先 `mkdir -p`）。手动执行：`docker exec mv-agent-frontend-backend-1 python /srv/mvagent/scripts/ensure_asset_avatars.py`。

## 6. 生成视频时的 URL 映射（前端零改动）

`main.py::create_video_generation`（POST /api/generations/videos）中，提交给供应商前调用 `_resolve_asset_avatar_urls()`：

- 遍历 `payload.image_urls`，英合 SD2.0 的数字人头像 URL 使用 `asset_avatar_url` 替换；其他模型按自身参考素材协议处理，不套用英合资产 ID
- 场景图等其他 URL 查不到映射，**原样保留**
- 前端照旧传 TOS URL，无需感知 asset 机制

人物图片在替换为渠道资产前会先识别其参考位置，并由最终视频提示词策略追加“身份参考、不参考服装”硬约束：只保留五官、脸型、肤色、年龄感和发型，不从头肩照推断全身比例，保留儿童与卡通身份；明确忽略白色 T 恤、灰背景、历史卡的浅灰下装与多视图排版、职业与年代暗示。剧情服装来自分镜 `wardrobeByCharacter`，优先级为“用户明确要求 > 季节 > 曲风 > 歌词与叙事 > 场景和动作 > 光线、色彩与视觉风格”；H3 编译器还会把对应 Picture 标注为 `identity_only`，该规则对英合与 RunningHub 共用。

## 7. 相关文件清单

| 文件                                            | 职责                                                                                                    |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `backend/app/providers.py`                      | `create_real_face_asset()` 资产注册；`translate_provider_error()` 英文错误翻译                          |
| `backend/app/domain.py`                         | `_sync_human_asset_avatar()` 入库同步注册；create/update_human 接入；`human_json` 暴露 `assetAvatarUrl` |
| `backend/app/main.py`                           | `_resolve_asset_avatar_urls()` 视频生成 URL 映射                                                        |
| `backend/app/seed.py`                           | `ensure_pending_asset_avatars()` 启动/手动兜底；seed_system_data 写入固化 asset                         |
| `backend/app/system_humans.py`                  | `SYSTEM_HUMAN_ASSET_URLS` 32 个系统人物固化 asset 映射                                                  |
| `backend/app/config.py`                         | `aigc_asset_group_id`（默认 `group-20260817142427-1cfe75`，V3 素材组）                                  |
| `backend/app/models.py`                         | `DigitalHumanModel.asset_avatar_url` 字段                                                               |
| `backend/migrations/versions/d4f2b8e6a1c0_*.py` | 英合资产字段的历史加列迁移（非当前 head；保留迁移链）                                                    |
| `backend/scripts/ensure_asset_avatars.py`       | cron 补扫脚本                                                                                           |
| `scripts/sync-digital-human-assets.sh`          | 宿主机 Compose 包装入口，读取当前部署版本后在 backend 容器执行补扫                                      |
| `backend/tests/test_generation_jobs.py`         | 全部相关自动化测试                                                                                      |

## 8. 自动化测试覆盖

- 资产创建：创建成功轮询到 Active / 审核 Rejected 抛友好错误
- URL 映射：头像（原图/缩略图）→ asset，场景图/已是 asset 的 URL 原样保留
- 端到端：POST /api/generations/videos 时 payload 中角色 URL 被替换为 asset://
- 用户数字人：创建时同步注册、换图重注册、注册失败降级不阻断

> 相关测试包括 `test_generation_jobs.py`、`test_prompts.py`、`test_headshot_prompt_migration.py`、`test_identity_headshot_scripts.py`，浏览器回归见 `e2e/user/digital-human-headshot.spec.ts`。它们验证请求与状态流转，不代替真实出图质量审核。

## 9. 注意事项 / 坑

1. **asset 跨环境通用**：asset 由平台托管，同一平台账号（VIDEO_API_KEY 同一 group）下本地/线上注册的链接通用，可固化进 seed
2. **换图必须清旧 asset**：asset 绑定具体图片，形象重新生成后旧链接失效，update_human 已处理
3. **注册失败只降级不阻断**：人物照常入库；期间生成视频可能重新出现"may contain real person"报错，cron 最多 1 分钟内补上
4. **seed 补缺行为**：已存在系统人物的原图、缩略图和 `asset_avatar_url` 仅在为空时由 seed 补齐，不覆盖已迁移地址；名称、身份描述等种子元数据仍会刷新。新环境从内置 TOS 路径及 `SYSTEM_HUMAN_ASSET_URLS` 初始化，换图后必须同步固化匹配的新原图、缩略图与英和资产映射，不能只改其中一个。换 key 时须另外制定经批准的 Alembic 数据迁移、注册和固化流程，禁止直接 SQL 清库。
5. **macOS 打包坑**：tar 打包部署会混入 `._*` AppleDouble 文件（含 null 字节），导致容器内 python 编译报 `SyntaxError: source code string cannot contain null bytes`；部署后执行 `find app migrations -name '._*' -delete`
6. **容器无 scripts 目录**：首次部署脚本需先 `docker exec ... mkdir -p /srv/mvagent/scripts`
7. **cron 环境**：crontab 里 docker 需用绝对路径（本地 `/usr/local/bin/docker`，线上 `/usr/bin/docker`）

## 10. 当前部署状态（2026-08-17）

- 已全量迁移至 V3 接口（素材 `/v3/assets*`、视频 `/v3/video/tasks`），key 切换为 `yh-ftbq...`（素材通道已授权），素材组 `group-20260817142427-1cfe75`
- 本地 32 个系统人物 + 5 个用户数字人已全部用 V3 重新注册，`SYSTEM_HUMAN_ASSET_URLS` 已固化新链接（线上部署后 seed 自动同步）
- V3 端到端实测通过：创建任务 `id` → 轮询 `succeeded` → `content.video_url` 落 TOS → `last_frame_url` 直接做封面（免 ffmpeg 抽帧）
- 本地 crontab 已配置；线上发布时需同步线上 `.env` 的 `VIDEO_API_KEY`/`IMAGE_API_KEY`/`AIGC_ASSET_GROUP_ID` 三项

## 11. 系统人物大头照迁移（待单独批准执行）

以下脚本已改造，不代表现有系统人物已经替换；真实生成、TOS 写入、英和注册、目标库变更与部署均须另行确认。

1. 先按 `提示词运营闭环演示手册.md` 第 4.2 节升级提示词元数据并发布三个新版模板。存量 DB 发布正文优先于代码 defaults，只更新代码或元数据不能切换实际出图规则。新版前端开放前须验证最终提示词，避免单图请求仍命中旧双图模板。
2. 经费用确认后使用 `scripts/generate-neutral-identity-manifest.py`。参数为 `--api-base`、`--token`、`--output`、`--run-id`，可加 `--ids`、`--limit`、`--concurrency`；不再接受 `--template`。默认及指定 ID 都只能选系统人物，每人只提交当前身份原图，固定英和 `gpt-image-2.5-sunburst`、`1024x1536`、`n=1`。所有应用请求附带 Agent 三头；输出包含人物 ID、原参考 URL、生成工单 ID 和结果 URL，完成行会复用。
3. 先做少量成人、儿童、卡通样本的人工质量审核，再批准剩余批量；检查头顶未裁、面部清楚、单人正面、白T灰底、无拼图。脚本保留同批已成功结果，但提交后至结果保存前中断的任务不能盲目重跑，必须先核对工单，避免重复费用。
4. `scripts/replace-digital-human-assets.py <manifest> --dry-run` 只校验系统人物范围并在清单旁保存备份，不上传或注册、不修改数据库；它仍需要只读访问目标数据库。私有人物和重复 ID 一律拒绝。实际替换需在批准的数据变更流程中执行：核验生成原图恰为 1024×1536，生成 320×480 缩略图，存入版本化 TOS 路径，仅注册英和资产；全部准备成功后统一写入人物记录。打印每人的 `code/original_url/thumbnail_url/asset_avatar_url` 映射，务必保存。
5. TOS 上传和供应商注册不随数据库事务回滚，失败后须凭备份、日志和工单对账，不要自动重跑。生成清单、备份、测试媒体、Token 和日志不提交仓库。
6. 审核替换结果后，将原图/缩略图路径与 `SYSTEM_HUMAN_ASSET_URLS` 成对固化到种子初始化流程，并同步 `SYSTEM_HUMANS` 的身份文案；脚本不会自动编辑这些源文件。现有库和全新空库都需验证，避免老库正常而新安装仍取旧图，或重启恢复旧身份文案。经完整验证后再版本化构建、发布。

私有人物继续按用户选择逐个手动重生成，绝不参与系统人物批量替换。

### 版本化头肩照发布补充（2026-09-22）

Alembic `e7a3b9c2f104` 在元数据迁移后发布三个模板的新规则，使用冻结的历史版本精确替换，保留无关运营追加内容和全部旧版本/草稿；新版本号取全部已有版本最大值加一。仓库历史中的旧双参考图与“不提交参考图”模板均有兼容转换。无法识别的自定义基础规则或遗漏的额外安全约束使迁移失败并回滚，不能直接覆盖。

`replace-digital-human-assets.py` 准备完成的 mapping 可离线编译成迁移和匹配的新安装种子文件：

```bash
backend/.venv/bin/python scripts/prepare-headshot-migration.py /private/path/prepared-mapping.json \
  --revision <新的唯一revision> --parent <当前Alembic-head> \
  --output /private/path/reviewed_headshots.py \
  --seed-output /private/path/headshot-assets.json
```

脚本不生成、不上传、不写库；仅接受全批次 `prepared`、系统人物、英和注册成功的映射，拒绝覆盖文件。审核后将迁移纳入 `backend/migrations/versions/`，同时将种子产物纳入 `backend/app/headshot-assets.json`，一起构建发布。生成的迁移校验 scope/user_id/deleted_at 及完整旧值，再更新；旧值有变化则整体停止，不覆盖并发编辑。重放同一批次不写入，回退使用原备份生成前向修复。

新安装使用种子产物的原图、缩略图、asset:// 及身份文案；存量库的 URL 只通过迁移切换，启动不会拿旧造型覆盖已版本化头肩照的身份文案。本轮没有生成新系统头像或替换线上资产；该工具链用于审核后的真实成图。
