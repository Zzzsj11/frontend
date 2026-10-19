# 全项目深度代码评审（2026-10-16）

评审基线：`main` @ `c983484`。覆盖后端 `backend/app`（约 2.0 万行）、前端 `src`（约 2.8 万行）、`model-service`（约 1.2 万行）、部署/CI/脚本/文档。四路并行只读审阅，所有 P0/P1 结论均经逐行二次核验。

当前门禁状态：后端 pytest 619 passed / 1 xfailed（129s）；前端 vitest user 209 + admin 43 全绿；`vue-tsc` 0 错误；`eslint --max-warnings=0` 失败 1 条（`base/BaseSelect.vue:93` attributes-order）；Alembic 单 head（`9a3d7f2c6b80`）；仓库无产物/密钥入库。

---

## P0（立即修复）

### P0-1 数字人头像 URL 只校验"是 TOS"，可越权读取他人私有对象
- `backend/app/domain.py:1972-1973`（`create_human`）与 `:1998-2000`（`update_human`）只调用 `is_tos_url`，未调用 `is_user_owned_tos_url`。
- `backend/app/image_download.py:62-71`：若 `DigitalHumanModel.avatar_url == src` 且 `user_id == user.id`，即签发预签名下载 URL。
- 链路：用户 A 用用户 B 的对象键（`users/{B}/...`，可从日志、分享截图、错误详情获得）创建数字人 → `/api/media/download` 拿到 B 私有文件的签名链接。
- 修复：两处改为 `is_user_owned_tos_url(payload.avatar_url, user.id)`（系统数字人走 admin 路径）；`image_download` 的数字人分支额外要求 `is_user_owned_tos_url(human.avatar_url, human.user_id)` 作纵深防御；补一条跨用户 URL 被拒的测试。

### P0-2 Worker 模式下租约过期恢复只在进程启动时执行一次
- `backend/app/worker.py:282` `_recover_stale(kinds, providers)` 仅在 `serve()` 启动时调用；主循环 `:343-347` 只给 `mv_export` 做了 15 秒定时巡检（代码注释本身已指出"不能只在启动时扫描一次"，但只修了导出）。`main.py` 的 `recover_stale_jobs` 仅 inline 模式生效。
- 后果：某个 Worker 崩溃后，其 `running` 的图片/视频/分镜工单即使租约过期也不会被其他存活 Worker 接管，直到任意 Worker 重启。文档"最多自动重放 3 次"在稳态不成立。
- 修复：把 `_recover_stale(kinds, providers)` 并入主循环定时器（间隔约 `worker_stale_seconds/2`），或由 API 进程的 `stale_generation_reaper` 统一巡检；补 fakeredis/sqlite 下的周期恢复测试。

### P0-3 回滚脚本在"含迁移的发布"之后必然失败
- `scripts/rollback.sh:5` 直接 `exec deploy.sh "$version"`；`deploy.sh:48` 用旧镜像起 green 容器；`backend/docker-entrypoint.sh:4` 无条件 `alembic upgrade head`。旧镜像缺少数据库已记录的新 revision，Alembic 报 `Can't locate revision`，green 健康检查失败，部署中止。
- 近 6 个迁移的 `downgrade()` 为 `raise RuntimeError`，不可逆，进一步放大风险；`docs/ROLLBACK.md` 描述的 expand/contract 回滚与实际脚本链路不匹配。
- 修复：`docker-entrypoint.sh` 加 `RUN_MIGRATIONS=${RUN_MIGRATIONS:-1}` 开关，`rollback.sh` 以 `RUN_MIGRATIONS=0` 调用；或把迁移从入口脚本移到 `deploy.sh` 的显式一次性步骤。文档补"回滚不触发迁移"的验证命令。

### P0-4 共享轮询调度器单点异常会挂死全部在途轮询（遗留直连渠道）
- `backend/app/providers.py:492` `await jobs.update_progress(...)` 位于 `_query_one` 的 try 之外；`jobs.py:227-231` 在工单已被 reaper 判败时抛 `JobExpiredError`，经 `:474` 的 `asyncio.gather` 冒泡终止 `_run`，其余 entry 的 future 永不 resolve，deadline 检查也一起停止。
- 影响面：生产 `LLM_CHANNEL=all-in-one` 时 `all_in_one.resume()` 自带循环不走此调度器，当前只影响遗留直连渠道；但缺陷真实存在。
- 修复：`_query_one` 对 `update_progress` 单独 try/except（`JobExpiredError` → `_finish_error`）；`_run` 外层兜底并对剩余 entry `set_exception` 后重建。

### P0-5 备份仅落本机磁盘，文档声称的异地同步不存在
- `scripts/backup-postgres.sh:3-7` 仅写 `$root/backups` 并 30 天滚动删除；`install-maintenance-cron.sh` 同样只排本地任务；全部脚本无 TOS/S3/rclone 引用。`docs/BACKUP-RESTORE.md:3` 声称"同步到独立加密 Bucket"。
- 单机磁盘故障 = 数据与备份同时丢失。
- 修复：新增 `scripts/sync-backup-to-tos.sh`（复用 `/run/secrets` 中的 TOS 凭据），接入 cron；或先把文档改为"当前仅本地备份"。

---

## P1（尽快修复）

### 后端：任务与供应商链路
- **P1-1 工单心跳协程无异常保护 → 租约静默过期 → 可能双执行。** `worker.py:319-332` `heartbeat()` 裸 `while True`，任一 DB 瞬断即终止（被 `gather(return_exceptions=True)` 吞掉）。被他人接管后，`jobs.py:526-533` `set_provider_task` 与 `:357-462` `_persist_asset` 无 `worker_id` 围栏，会重复写 `scene_assets/shot_assets/token_usage`。修复：心跳循环捕获非 `JobExpiredError` 并继续；两处写入加 owner 围栏。
- **P1-2 Redis 执行池租约在长任务下整体失效。** `redis_store.py:172` 获取时 `EXPIRE key ttl`（默认 180s），`:201` 续约仅 `ZADD ... xx=True` 不刷新键 TTL。某池 180s 内无新 acquire 时整键过期，后续续约静默无效，分布式并发上限对 2h 视频轮询基本不生效。修复：续约脚本同时 `ZADD`（无 XX 或 XX 失败则重加）+ `EXPIRE`。
- **P1-3 媒体工单 `submitting_provider` 重放采用黑名单且无次数上限。** `worker.py:162-174` 仅排除 toapis/runninghub，其余直连通道都会重放；`attempt += 1` 未与 `MAX_INTERNAL_ATTEMPTS` 比较。改为白名单（all-in-one、yinghe Seedance/gpt-image-2、`_modelGateway`）+ `attempt < 3`。
- **P1-4 遗留通道上游 5xx 被当作"确定拒绝"。** `providers.py:201-223` 对所有 HTTP 错误抛 `ProviderRejectedError(submission_certain=True)`；502/504 时上游可能已建任务并计费，本地直接 `failed` 而非 `manual_review`。`all_in_one.py:137-147` 已正确区分，遗留通道对齐即可。
- **P1-5 all-in-one 图片成功后 TOS 归档失败丢失平台积分用量。** `all_in_one.py:190-194` 先 `record_provider_response("terminal")` 再 `store_result`；归档异常走 `jobs.py:311-337`，写入 usage 为空。视频有 `video_billing.py:163-164` 兜底，图片没有。修复：归档失败时把 `data["usage"]` 挂到异常或从 `_providerTerminalResponse` 回读。
- **P1-6 Worker 主循环无异常保护。** `worker.py:343-360` `_claim` 的 DB 异常直接穿出 `serve()`，进程退出；与 P0-2 叠加放大。

### 后端：安全与数据
- **P1-7 Agent 归因完全由客户端自报。** `agent_attribution.py:19-25`：任意登录用户带 `X-Test-Run-Id` 即标记 `agent_test`，影响 `admin.py:683-684` 的业务/测试费用拆分；反向省略头即混入 business。另 `token_usage_records`/`llm_call_logs` 无 origin 列，无 job 的用量（chat、优化失败路径）无法按来源统计。修复：对 `agent_test` 来源要求专用 service token 或账号白名单，不满足强制 `business`；迁移给 `token_usage_records` 增 `generation_origin/agent_run_id`。
- **P1-8 生产未强制 refresh cookie `Secure`。** `config.py:116` 默认 false，`validate_runtime_security`（`:224-240`）未检查。14 天有效的 refresh token 可能走明文 HTTP。
- **P1-9 登录限流 Redis 故障时 fail-open。** `main.py:399-429` 异常时 `attempts = 1` 放行。改为 503 或进程内令牌桶，并记录告警。
- **P1-10 `PATCH /api/admin/users/{id}` 可改 role/status 但无审计、不作废旧会话。** `domain.py:199-208` 直接 `setattr`；对比 `update_user_admin_role`（`:211-284`）有审计与自降权保护。变更后应 `auth_version += 1` 并撤销 refresh tokens。
- **P1-11 `/api/uploads/import` SSRF 防护有 DNS 重绑定窗口与内存放大。** `storage.py:224-237` 校验 DNS 后 httpx 重新解析；`download_public_url` 最多 500MB 全读入内存。改为固定已校验 IP 的 transport + 流式落盘。
- **P1-12 跨资源引用未做归属校验。** `domain.py:1988-2008` `update_human.style_id` 未验 owner；`:2081-2112` `update_line.optimization_task_id` 仅 `source == "creative"` 时校验。统一用 `owned_*` 辅助函数。

### 前端
- **P1-13 轮询聚合请求一次网络抖动把全部在途生成"误判失败"。** `generationPoller.ts:157-160` 捕获后对 batch 内所有 entry `reject`；`client.ts:92` 网络异常只对 GET 重试，而状态聚合是 POST。下游 `project.ts:2158-2168/2230-2239/820-845` 收到非取消错误即标 `failed` 并弹窗，后端其实仍在跑。修复：tick 内网络类错误把 entry 放回并计数，连续 N 次才 reject；或对带 `X-Polling` 的幂等 POST 启用重试。
- **P1-14 `ShotGenerationOptionsPopover` 手写遮罩弹层，Esc 泄漏到父弹窗。** `ShotGenerationOptionsPopover.vue:244-254` 自行 Teleport + overlay，未 `registerModal`、无 Esc 处理；嵌在 `ShotDetailModal` 内时按 Esc 直接关掉整个分镜弹窗，参数草稿丢失。改用 `BaseModal level="nested"`。
- **P1-15 路由守卫与管理台导航权限不一致。** `router.ts:27-32` 仅放行 `isSuperAdmin || song_emotions.read`，`AdminConsoleView.vue:180` 允许 `storyboard_options.read`；仅持后者的管理员功能不可达。抽 `canAccessAdmin(user)` getter 共用。
- **P1-16 `project.ts` 2556 行"上帝 store"，超规范 5 倍。** 可按现有 action 分组切成 task / outline / storyboardLine / digitalHuman / mediaGen / export / player 七个 store，先抽耦合最低的 player 与 export。

### 基础设施
- **P1-17 后端镜像以 root 运行，基础镜像未锁 digest。** `backend/Dockerfile` 无 `USER`；`python:3.12-slim`、`postgres:16`、`redis:7-alpine` 未锁 sha256。model-service 两个 Dockerfile 已做对，可直接对齐。
- **P1-18 Python 依赖未锁定。** `requirements.txt` 全部范围约束，无 lock；同一 git SHA 两次构建依赖集可能不同，与"镜像标签固定为 git-SHA 便于回滚"矛盾。引入 `uv pip compile`/`pip-compile`。
- **P1-19 Worker 健康检查假阳性。** `docker-compose.yml:92` `kill -0 1`，死循环/断库全部 healthy；`deploy.sh:74-82` 与 `online-health-check.sh` 依赖它放行切换。改为检查 `worker_instances` 最近心跳。
- **P1-20 前端生产依赖 3 个 high 漏洞；CI 门槛只到 critical。** `@vue/server-renderer <3.5.42`（当前 vue 3.5.40）、`source-map-js`。`npm update vue vite @vitejs/plugin-vue`；CI 提到 `--audit-level=high`。
- **P1-21 CI 与本地卡口不一致，无 e2e，不含 model-service。** `ci.yml` 只跑 `npm run lint` + `ruff check`，缺 `format:check`、`ruff format --check`、Playwright、`make -C model-service check`；Actions 仅按 major tag 引用。建议 CI 直接调 `make lint migration-check test build` + e2e。
- **P1-22 `backend/.env.example` 重复且缺 `MODEL_GATEWAY_URL/API_KEY`。** `ALL_IN_ONE_*` 出现两次；compose 依赖的两个网关变量缺失。

---

## P2（改进项，摘要）

后端：`_modelGateway` 工单在提交窗口崩溃且网关下线时仍可能直连（`model_gateway.py:76` 条件改为看 `_modelGateway` 标记）；图片 failover 把内容违规计入模型故障（`all_in_one.py:151-155`），3 条违规提示词即可让全站切 Seedream 2h；`prompt_optimizer.py:247-253` 结构性空响应计入 LLM 故障，且 `:215` 系统指令与用户 prompt 拼在同一 user 消息；`--providers` 过滤在 Python 侧导致 FIFO 饥饿（`worker.py:61-75`）；`providers.py:1681/2018` ffprobe/ffmpeg `communicate()` 无超时；五段轮询函数几乎同构（`_poll_kling/_poll_direct_h3/_poll_gemini_omni/_poll_toapis_video/_poll_runninghub`）、`_query_wan_task`/`_query_happyhorse_task` 完全相同；`seed.py:877-918` `ensure_pending_asset_avatars` 退役残留；`create_material_export`（`domain.py:2904-2968`）check-then-insert 无行锁且可留孤儿 job；refresh token 无 family 重用检测；`/api/aigc/models` 向普通用户泄露 key 后 6 位（`admin.py:1412-1422`）；`chat.py:287` 异常原文直推前端未脱敏；上传仅凭扩展名+客户端 MIME；批量视频逐项扣配额非原子（`main.py:958`）；`SceneAsset/ShotAsset/VoiceAsset` 的 `generation_job_id` 与 `is_current` 无索引；`require_user` 每请求 3 次 DB 查询；`chat.py:120` 本地时区与 `utcnow()` 混用。

前端：逐句提示词等待传 `undefined` signal 切任务后仍后台轮询（`project.ts:611/690/779`）；poller 同 jobId 重复注册覆盖前一 Promise（`generationPoller.ts:211`）；轮询不感知 tab 隐藏；`mv:pending-dh` 未按用户隔离；store 层对 `ApiError` 二次 `reportApiError` 造成"重复 N 次"虚高；余额校验在 `ScriptEditor`/`GeneralStoryboardModal` 各写一份绕过 `auth.loadBalance`；`.vue` 内硬编码色值 204 处、`AdminTopBar` `z-index: 500` 不在层级表、`--z-*` 令牌只有 1 个；SSE 单条畸形事件中断整条流（`domain.ts:374/413`）；`taskScripts` 缓存无上限；`FRONTEND-GUIDELINES.md` 的 `#body` 插槽示例与 `BaseModal` 默认插槽不一致；`BATCH_SHOT_CONCURRENCY=200` 与注释"避免 429"矛盾。

基础设施/文档：开发 compose Postgres 暴露 `0.0.0.0:5433` 且密码硬编码；`docker-compose.yml:30` 与 `e2e/env.ts:13` 硬编码公网 IP；backend 无 `.dockerignore`；`backend/Dockerfile:17-19` python3.14 死代码；backend 服务无 `stop_grace_period`；`Makefile setup` 在 venv 不存在时失败、`stop` 不带 `--profile workers`；`deploy.sh:74-75` 显式指定 worker 服务名会在 inline 模式下也启动 5 个 worker（待确认）；`MEDIA_WORKER_CONCURRENCY` 为死配置；34 张 e2e 截图 PNG 入库占 Top-15 大文件榜。文档漂移：`DEPLOYMENT.md:36` 让本地裸 `docker compose up --build` 违反 AGENTS.md 禁直连 docker.io；端口 80/5173、用户 ubuntu/root、preflight-lite 70s/85s、Python 3.11/3.12 多处口径不一；`LOCAL-DEVELOPMENT.md:31-33` 仍称资产补扫在线上运行并链接到已改为"退役"的 `ASSET-AVATAR.md` §5。

---

## 架构文档声明 vs 代码实际

| 声明 | 结论 | 依据 |
|---|---|---|
| `FOR UPDATE SKIP LOCKED` 领取 | 符合 | `worker.py:53-62` |
| `worker_instances` 心跳 + SIGTERM draining | 符合 | `worker.py:268-313, 361-365` |
| 只有租约过期才恢复、最多重放 3 次 | 部分符合 | 逻辑存在但仅启动执行（P0-2）；媒体重放无上限（P1-3） |
| Idempotency-Key 由工单 ID 派生并先持久化 | 符合 | `all_in_one.py:129-132`、`providers.py:592-603, 717-735`、`jobs.py:598-608` |
| 网关按 (client,user,key) 去重 | 符合 | `model-service/public-api/.../main.py:145-183`，唯一约束 + request_hash |
| 执行池 = 进程内信号量 + Redis 原子租约 | 部分符合 | 获取原子，续约不刷新键 TTL（P1-2） |
| gemini→doubao 5 次 / 2h；Redis 不可用保持主模型 | 符合 | `llm_failover.py:32-60`、`storyboard_prompt.py:845-870` |
| nano→seedream 3 次、按工单去重、备用成功不清零 | 符合（口径有争议） | `image_failover.py:19-45`；内容违规计入见 P2 |
| all-in-one 2h / 其他 20min | 符合 | `generation_constraints.py:9-12`、`jobs.py:464-496` |
| billing_reconcile 每批 500 | 符合 | `video_billing.py:314` |
| 网关缺失时禁止静默回退 | 部分符合 | `model_gateway.py:76` 仅覆盖已有 taskId 的工单 |
| PPIO/BFL 已移除 | 符合 | `backend/app` 无引用；迁移 `b3f7a1c5e902` 已删字段 |
| 备份同步到异地加密 Bucket | 不符合 | 仅本地（P0-5） |
| 回滚不执行 Alembic | 不符合 | 入口脚本无条件 upgrade（P0-3） |

---

## 做得好的地方

- 安全基线：生产禁默认 JWT secret、禁 CORS `*`、secrets 文件权限校验；argon2、15 分钟 access token 含 `auth_version`、refresh token sha256 存储 + httpOnly + 路径限定 + 使用即轮换；57 条 `/api/admin/*` 全部挂 `require_admin`/`require_permission`；前端 access token 仅内存、全仓无 `v-html`/`console`、`any` 为 0、vue-tsc strict 全绿。
- 数据纪律：所有表走 `LifecycleMixin`，全库无 ORM 硬删除；`owned_project/owned_task/owned_line/visible_humans` 联表隔离；Alembic 单 head，`check-migrations.sh` 在 CI 与 preflight 强制；`consume_daily_quota` 用 `ON CONFLICT ... WHERE` 原子扣减。
- 任务链路：幂等键"先持久化再发请求"；`_persist/update_progress` 带 worker_id 围栏；reaper 判败后在途协程以 `JobExpiredError` 优雅退出；Redis 全部 best-effort 降级；`all_in_one.generate` 区分确定/不确定失败并尝试 `x-job-id` 恢复；提示词模板用正则占位替换、用户文本只进 user 消息。
- 前端架构：`taskLoadVersion` 单调序号防旧响应覆盖；几乎所有异步写回带 `activeTaskId === taskId` 守卫；单一 3s tick 聚合轮询 + 按任务 AbortController；`BaseModal` 的 Teleport/inert/焦点环/焦点归还/滚动锁质量高；admin 视图已按路由懒加载拆 chunk；缩略图不挂 `<video>` 的修复仍成立。
- 运维：Docker secrets 注入、`validate-secret-layout.sh`；green 容器 + 健康检查 + 失败自动中止的平滑发布；按类排空 worker 匹配 `stop_grace_period`；nginx 运行时 DNS 解析、安全头 + CSP、SSE 关缓冲；前端镜像锁 digest；备份带 SHA-256 与隔离库恢复验证；model-service 的非 root、127.0.0.1 绑定、资源限制、真实健康检查可作为主 backend 对齐模板。
- 测试：后端 619 用例、前端 252 用例全绿；幂等重放、执行池、调度器分摊、failover、refresh 轮换、限流共享计数均有覆盖。

## 关键测试缺口

后端：Worker draining/`worker_instances` 状态流转；心跳异常后他人接管的写入围栏；`ProviderPollScheduler` 遇异常后其余 entry 仍能结束；Redis 租约键过期后续约语义；稳态周期 `_recover_stale`；遗留通道 5xx 归 manual_review；图片归档失败保留 usage；`auth_version` 失效；Redis 故障时限流；跨用户 TOS URL 创建数字人；伪造 `X-Test-Run-Id`；`style_id`/`optimization_task_id` 跨用户引用；`create_material_export` 并发。

前端：`router.ts` 守卫、`LoginView`、`ChangePasswordView`、`SongSidebar`、`AssetLibrary`（1242 行零覆盖）、`ShotMediaCards`、`AdminConsoleView`/`AdminSideNav` 无单测；poller 聚合请求网络失败与重复注册路径；`appHeader.test.ts` 缺 router stub 产生 warn；真实生成 e2e 仅 `REAL_GENERATION_E2E=1` 门控。

## 建议修复顺序

1. P0-1（越权读取）、P0-3（回滚失败）——一天内可完成，改动极小。
2. P0-2 + P1-1 + P1-2 + P1-6（Worker 恢复/心跳/租约/主循环四件套）——同一文件域，一次 PR 合并处理并补测试。
3. P0-5 备份异地同步、P1-19 worker 真实健康检查、P1-17/18 镜像加固与依赖锁。
4. P1-7/8/9/10 认证与归因加固；P1-13/14/15 前端三项小改动。
5. P1-4/5、P2 中的 failover 口径与 5xx 归类——涉及计费与可用性判断，动手前对齐业务口径。
6. 长线：`project.ts` 与 `domain.py`/`admin.py`/`providers.py` 拆分、色值令牌化、CI 对齐 Makefile 卡口、文档漂移清理。
