# 技术架构

项目是 Vue 3 + TypeScript 前端、FastAPI + SQLAlchemy 后端、PostgreSQL 持久化、Redis 缓存/任务状态、TOS 媒体存储的 MV AI 生产平台。Nginx 托管前端并代理 `/api`。

主要领域：认证和多用户隔离、项目/子项目、ASS 与通用分镜、系统及私有人物、场景/视频/音频资产、模型注册、生成任务、Token 用量、错误日志、管理后台。

生成链路：前端提交任务，后端校验用户和模型，创建 `generation_jobs`，调用供应商，原媒体及缩略图导入 TOS，资产记录入 PostgreSQL，用量写入账本。列表只加载缩略图，用户交互时才加载原图或视频。

统一供应商配置通过 Docker Secret `provider_config` 挂载。检测到其中的 `AIGC_TOKEN` 时，文本模型 Token、聊天 API 地址和默认模型作为同一个配置组生效，优先于遗留的 `LLM_*` 环境变量，避免共享 Token 被误发往其他供应商；只有未配置统一供应商 Secret 时才启用独立 `LLM_*` 配置。

Chat对话、媒体生成、素材导出、ASS/通用大纲、逐镜提示词和ASS场景段重试支持两种执行模式：默认 `inline` 保持本地单进程行为；服务器设置 `JOB_EXECUTION_MODE=worker` 后，API只在同一事务中写领域状态和 `generation_jobs`，`worker-chat`、`worker-image`、`worker-media`（仅视频）、`worker-export` 与 `worker-storyboard` 使用 PostgreSQL `FOR UPDATE SKIP LOCKED` 领取。图片和视频使用独立执行池，避免长视频轮询占满图片槽；单机默认分别为32并发。分镜工单的完整人物、上下文、大纲和重试快照保存在 `generation_jobs.request`，进度与心跳同时落PostgreSQL；Worker中断后最多自动重放3次。Redis承担低延迟 Worker 唤醒、Chat跨进程取消、热状态与事件，短暂不可用不会丢失数据库工单。模型注册中心的 `executionPool/executionConcurrency` 同时由进程内信号量和 Redis 原子租约约束，多 Worker 或多节点共享同一并发上限；Redis不可用时降级为进程内限制。新模型接入现状和剩余清单见 `TODO_MODEL_EXPANSION.md`。

单机 Worker 可靠性以 PostgreSQL 租约为准：`worker_instances` 记录进程版本、`running/draining/drained` 状态、心跳与在途任务数；`generation_jobs` 记录 `worker_id/claimed_at/heartbeat_at/lease_expires_at/phase/provider_submitted_at`。SIGTERM 后 Worker 先持久化 `draining` 并停止领取，现有任务继续心跳直至结束。只有租约过期的任务可被恢复；已有 `provider_task_id` 的媒体任务只恢复轮询。当前供应商不支持创建幂等键，因此处于 `submitting_provider` 且没有 taskId 的崩溃任务一律转为 `manual_review`，禁止自动重提，避免重复计费。这个极短窗口无法由客户端完全消除，只能依赖供应商未来提供幂等创建或按本地 job ID 查询任务。

数据库结构只由 Alembic 管理，应用启动仅验证连接；测试用 SQLite 可在隔离数据库中由 metadata 建表。认证采用短 access token、数据库 refresh token 与 `users.auth_version`，改密可即时撤销历史会话。

素材导出使用 `material_exports` 保存用户、子项目、进度阶段、字节数和 TOS 归档地址，并关联 `generation_jobs`。每次导出拥有独立 ID、临时目录和 TOS 对象键；不同子项目可并行执行且前端状态按 `taskId` 隔离。浏览器通过带 Access Token 的流式 Fetch 订阅 SSE，断线或刷新后以 PostgreSQL 状态恢复，SSE 只承担实时通知而不是事实存储。

ASS 大纲采用三层提示词结构：系统安全与技术约束、歌曲级视觉圣经、当前镜头执行契约。视觉圣经统一人物面部身份、时间、天气和色彩，并在 `scenePlan.wardrobeByCharacter` 中为每个大场景规划独立服装；同一大场景内服装连续，切换大场景时换装。每镜契约固定人物、地点、动作、情绪重点、服装和镜头目的。通用 MV 保留大纲中的人物镜人数/性别语义，但视频生成时不发送数字人头像，每个人物镜可独立生成不同人物与服装。
