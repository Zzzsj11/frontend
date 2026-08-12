# 数字人资产与真人人脸校验说明（asset:// 虚拟资产链路）

> 写给接手开发的程序员 / code-agent。本文档说明人物素材（数字人）图片的存储方式、上游 AIGC 平台的真人人脸校验问题，以及 `asset://` 虚拟资产机制的完整链路：谁在注册、存在哪、生成视频时怎么用、失败了怎么兜底。

## 1. 背景：真人人脸校验问题

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
| 字段映射      | `digital_humans.asset_avatar_url` 存 asset 链接，`avatar_url` / `avatar_thumbnail_url` 仍是 TOS 路径                                      |

## 3. 虚拟资产注册 API（AIGC 平台）

两个接口（实现见 `backend/app/providers.py::create_real_face_asset`）：

1. **创建**：`POST {VIDEO_API_BASE_URL}/virtual/assets/create`
   ```json
   {
     "url": "<图片公开URL>",
     "name": "mv-001",
     "assetType": "Image",
     "Moderation": { "Strategy": "Skip" }
   }
   ```
   请求头除 `Authorization: Bearer {VIDEO_API_KEY}` 外，**必须带 `group_id: 2075463560011292673`**（配置项 `AIGC_ASSET_GROUP_ID`，chouka-tools 同款 group，实测本地 VIDEO_API_KEY 可直接创建）。返回 `data.id`（状态 Processing）。
2. **轮询详情**：`POST /virtual/assets/detail`，body `{"assetId": "..."}`，间隔 3 秒轮询直到 `status == "Active"`；`Rejected` / `Failed` 视为审核失败；超过 180 秒判超时。

> 实测：mv-agent 的 VIDEO_API_KEY（`yh-qu78hnd...`）+ 上述 group_id 可正常创建资产，3-6 秒进入 Active。

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
2. **cron 每分钟补扫**：独立脚本 `backend/scripts/ensure_asset_avatars.py`，每分钟扫一次补齐（复用 `seed.py::ensure_pending_asset_avatars()`），保证上游抖动导致的失败**最多 1 分钟内**被修复

> 注：曾有过"服务启动时再扫一次"的第三层，与 cron 功能重复且无防重入锁（可能与 cron 并发导致同一人物重复注册资产），已移除。补注册统一由 cron 负责，部署新环境时务必同步配置 crontab（见 §5）。

## 5. cron 脚本部署详情

脚本：`backend/scripts/ensure_asset_avatars.py`

- 逻辑：统计活跃且 `asset_avatar_url IS NULL` 的数字人 → 有缺失就逐个注册 → 打印 `handled N pending human(s)`
- 幂等 + 防重入（fcntl 文件锁 `/tmp/mvagent-asset-sync.lock`，同一时刻只允许一个同步进程）

crontab 配置（**宿主机**上，每分钟）：

| 环境           | 命令                                                                                                         | 日志                                              |
| -------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------- |
| 本地（macOS）  | `/usr/local/bin/docker exec mv-agent-frontend-backend-1 python /srv/mvagent/scripts/ensure_asset_avatars.py` | `/tmp/mvagent-asset-sync.log`                     |
| 线上（Ubuntu） | `docker exec mv-agent-frontend-backend-1 python /srv/mvagent/scripts/ensure_asset_avatars.py`                | `/opt/mv-agent-frontend/logs/asset-sync-cron.log` |

容器内脚本路径：`/srv/mvagent/scripts/ensure_asset_avatars.py`（容器内无 scripts 目录时需要先 `mkdir -p`）。手动执行：`docker exec mv-agent-frontend-backend-1 python /srv/mvagent/scripts/ensure_asset_avatars.py`。

## 6. 生成视频时的 URL 映射（前端零改动）

`main.py::create_video_generation`（POST /api/generations/videos）中，提交给供应商前调用 `_resolve_asset_avatar_urls()`：

- 遍历 `payload.image_urls`，**数字人头像 URL（原图或缩略图）→ 替换为对应 `asset_avatar_url`**（asset:// 链接）
- 场景图等其他 URL 查不到映射，**原样保留**
- 前端照旧传 TOS URL，无需感知 asset 机制

## 7. 相关文件清单

| 文件                                            | 职责                                                                                                    |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `backend/app/providers.py`                      | `create_real_face_asset()` 资产注册；`translate_provider_error()` 英文错误翻译                          |
| `backend/app/domain.py`                         | `_sync_human_asset_avatar()` 入库同步注册；create/update_human 接入；`human_json` 暴露 `assetAvatarUrl` |
| `backend/app/main.py`                           | `_resolve_asset_avatar_urls()` 视频生成 URL 映射                                                        |
| `backend/app/seed.py`                           | `ensure_pending_asset_avatars()` 启动/手动兜底；seed_system_data 写入固化 asset                         |
| `backend/app/system_humans.py`                  | `SYSTEM_HUMAN_ASSET_URLS` 32 个系统人物固化 asset 映射                                                  |
| `backend/app/config.py`                         | `aigc_asset_group_id`（默认 `2075463560011292673`）                                                     |
| `backend/app/models.py`                         | `DigitalHumanModel.asset_avatar_url` 字段                                                               |
| `backend/migrations/versions/d4f2b8e6a1c0_*.py` | 加列迁移（head：d4f2b8e6a1c0）                                                                          |
| `backend/scripts/ensure_asset_avatars.py`       | cron 补扫脚本                                                                                           |
| `backend/tests/test_generation_jobs.py`         | 全部相关自动化测试                                                                                      |

## 8. 自动化测试覆盖

- 资产创建：创建成功轮询到 Active / 审核 Rejected 抛友好错误
- URL 映射：头像（原图/缩略图）→ asset，场景图/已是 asset 的 URL 原样保留
- 端到端：POST /api/generations/videos 时 payload 中角色 URL 被替换为 asset://
- 用户数字人：创建时同步注册、换图重注册、注册失败降级不阻断

> 全套后端测试 91 个通过（`cd backend && .venv/bin/python -m pytest tests/ -q`）

## 9. 注意事项 / 坑

1. **asset 跨环境通用**：asset 由平台托管，同一平台账号（VIDEO_API_KEY 同一 group）下本地/线上注册的链接通用，可固化进 seed
2. **换图必须清旧 asset**：asset 绑定具体图片，形象重新生成后旧链接失效，update_human 已处理
3. **注册失败只降级不阻断**：人物照常入库；期间生成视频可能重新出现"may contain real person"报错，cron 最多 1 分钟内补上
4. **seed 覆盖行为**：每次启动 seed 会把系统人物的 `asset_avatar_url` 覆盖回固化值——若平台资产被删导致失效，需要更新 `SYSTEM_HUMAN_ASSET_URLS` 重新固化（或依赖 cron 补新值，但重启后会被还原）
5. **macOS 打包坑**：tar 打包部署会混入 `._*` AppleDouble 文件（含 null 字节），导致容器内 python 编译报 `SyntaxError: source code string cannot contain null bytes`；部署后执行 `find app migrations -name '._*' -delete`
6. **容器无 scripts 目录**：首次部署脚本需先 `docker exec ... mkdir -p /srv/mvagent/scripts`
7. **cron 环境**：crontab 里 docker 需用绝对路径（本地 `/usr/local/bin/docker`，线上 `/usr/bin/docker`）

## 10. 当前部署状态（2026-08-12）

- 本地 + 线上均已完成代码部署与数据重建
- 线上数据已清空重建：保留 3 个初始用户（admin / dev01 / mv-test-01），32 个系统人物全部带 asset:// 链接
- 本地 + 线上 crontab 均已配置并验证实际执行
