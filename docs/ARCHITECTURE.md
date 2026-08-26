# 技术架构

项目是 Vue 3 + TypeScript 前端、FastAPI + SQLAlchemy 后端、PostgreSQL 持久化、Redis 缓存/任务状态、TOS 媒体存储的 MV AI 生产平台。Nginx 托管前端并代理 `/api`。

主要领域：认证和多用户隔离、项目/子项目、ASS 与通用分镜、系统及私有人物、场景/视频/音频资产、模型注册、生成任务、Token 用量、错误日志、管理后台。

生成链路：前端提交任务，后端校验用户和模型，创建 `generation_jobs`，调用供应商，原媒体及缩略图导入 TOS，资产记录入 PostgreSQL，用量写入账本。列表只加载缩略图，用户交互时才加载原图或视频。

统一供应商配置通过 Docker Secret `provider_config` 挂载。检测到其中的 `AIGC_TOKEN` 时，文本模型 Token、聊天 API 地址和默认模型作为同一个配置组生效，优先于遗留的 `LLM_*` 环境变量，避免共享 Token 被误发往其他供应商；只有未配置统一供应商 Secret 时才启用独立 `LLM_*` 配置。

ASS 与定制通用分镜默认使用 `OUTLINE_PROTOCOL_VERSION=v2` 的紧凑大纲协议。定制通用一次输出全片导演决策骨架；ASS 固定为一次大场景规划加一次全曲镜头骨架，不再按大场景并行重复提交人物长描述。后续逐镜提示词仍消费兼容的标准大纲字段，因此无需改动下游图片、视频和导出链路。紧急回滚可将该变量设为 `v1`，恢复旧提示词和旧调用编排。

Chat对话、媒体生成、素材导出、ASS/通用大纲、逐镜提示词和ASS场景段重试支持两种执行模式：默认 `inline` 保持本地单进程行为；服务器设置 `JOB_EXECUTION_MODE=worker` 后，API只在同一事务中写领域状态和 `generation_jobs`，`worker-chat`、`worker-image`、`worker-media`（仅视频）、`worker-export` 与 `worker-storyboard` 使用 PostgreSQL `FOR UPDATE SKIP LOCKED` 领取。图片和视频使用独立执行池，避免长视频轮询占满图片槽；单机默认分别为32并发。分镜工单的完整人物、上下文、大纲和重试快照保存在 `generation_jobs.request`，进度与心跳同时落PostgreSQL；Worker中断后最多自动重放3次。Redis承担低延迟 Worker 唤醒、Chat跨进程取消、热状态与事件，短暂不可用不会丢失数据库工单。模型注册中心的 `executionPool/executionConcurrency` 同时由进程内信号量和 Redis 原子租约约束，多 Worker 或多节点共享同一并发上限；Redis不可用时降级为进程内限制。视频生成按供应商和模型拆分执行池：英和提供 SD2.0 与 MiniMax-H3 直连，PPIO 提供 Seedance 2.0 标准版与 MiniMax-H3 原厂协议，RunningHub H3 保留为并发 2 的测试通道。人物入库或换图时，同一 TOS 原图并行注册为英合与 PPIO 两份独立虚拟人物资产；生成 Seedance 视频时再按模型渠道选择对应 `asset://`，原始 TOS URL 始终保留用于展示和对账。各 H3 通道共享提示词编译与参考素材约束，但分别适配创建、查询、恢复和结果解析协议。顶部余额接口聚合英和与 PPIO 两个供应商，批量任务按模型所属渠道分别估价和预检余额，禁止跨渠道余额兜底。新模型接入现状和剩余清单见 `TODO_MODEL_EXPANSION.md`。

ASS 与定制通用的逐镜提示词采用服务端批量受理：页面一次提交最多100条，Worker默认64并发执行，浏览器不再以4条长轮询限制吞吐。每条模型请求只携带当前场景、当前镜头、前后两镜、局部歌词和实际出演人物，不再重复发送全片镜头数组；模型等待期间释放数据库连接，只在读取和结果回填时开启短事务。随机通用创建完成后通过视频批量端点一次持久化全部纯文本视频工单，随后由 Seedance 模型池的170并发上限统一调度。

单机 Worker 可靠性以 PostgreSQL 租约为准：`worker_instances` 记录进程版本、`running/draining/drained` 状态、心跳与在途任务数；`generation_jobs` 记录 `worker_id/claimed_at/heartbeat_at/lease_expires_at/phase/provider_submitted_at`。SIGTERM 后 Worker 先持久化 `draining` 并停止领取，现有任务继续心跳直至结束。只有租约过期的任务可被恢复；已有 `provider_task_id` 的媒体任务只恢复轮询。gpt-image-2 图片和 Seedance 视频在供应商创建请求的 `Idempotency-Key` Header 中发送由本地工单 ID 派生的稳定键，并在发请求前持久化；处于 `submitting_provider` 且没有 taskId 的崩溃任务可以用原键安全重放，不会重复创建。其他未声明幂等能力的供应商仍转为 `manual_review`，禁止自动重提。

数据库结构只由 Alembic 管理，应用启动仅验证连接；测试用 SQLite 可在隔离数据库中由 metadata 建表。认证采用短 access token、数据库 refresh token 与 `users.auth_version`，改密可即时撤销历史会话。

素材导出使用 `material_exports` 保存用户、子项目、进度阶段、字节数和 TOS 归档地址，并关联 `generation_jobs`。每次导出拥有独立 ID、临时目录和 TOS 对象键；不同子项目可并行执行且前端状态按 `taskId` 隔离。浏览器通过带 Access Token 的流式 Fetch 订阅 SSE，断线或刷新后以 PostgreSQL 状态恢复，SSE 只承担实时通知而不是事实存储。

ASS 大纲采用三层提示词结构：系统安全与技术约束、歌曲级视觉圣经、当前镜头执行契约。视觉圣经统一人物面部身份、时间、天气和色彩，并在 `scenePlan.wardrobeByCharacter` 中为每个大场景规划独立服装；同一大场景内服装连续，切换大场景时换装。每镜契约固定人物、地点、动作、情绪重点、服装和镜头目的。通用 MV 保留大纲中的人物镜人数/性别语义，但视频生成时不发送数字人头像，每个人物镜可独立生成不同人物与服装。
