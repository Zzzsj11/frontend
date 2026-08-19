# 技术架构

项目是 Vue 3 + TypeScript 前端、FastAPI + SQLAlchemy 后端、PostgreSQL 持久化、Redis 缓存/任务状态、TOS 媒体存储的 MV AI 生产平台。Nginx 托管前端并代理 `/api`。

主要领域：认证和多用户隔离、项目/子项目、ASS 与通用分镜、系统及私有人物、场景/视频/音频资产、模型注册、生成任务、Token 用量、错误日志、管理后台。

生成链路：前端提交任务，后端校验用户和模型，创建 `generation_jobs`，调用供应商，原媒体及缩略图导入 TOS，资产记录入 PostgreSQL，用量写入账本。列表只加载缩略图，用户交互时才加载原图或视频。

统一供应商配置通过 Docker Secret `provider_config` 挂载。检测到其中的 `AIGC_TOKEN` 时，文本模型 Token、聊天 API 地址和默认模型作为同一个配置组生效，优先于遗留的 `LLM_*` 环境变量，避免共享 Token 被误发往其他供应商；只有未配置统一供应商 Secret 时才启用独立 `LLM_*` 配置。

当前任务执行仍在 API 进程内。H3 已按模型级并发上限 2 排队，但多进程/多实例时进程内信号量不能提供全局上限；后续迁移 Worker 时必须保持 `generation_jobs` 状态机和接口契约，以 Redis/队列实现“供应商 + 模型”全局并发配额，先双写/灰度，再切换执行器。新模型接入现状和剩余清单见 `TODO_MODEL_EXPANSION.md`。

数据库结构只由 Alembic 管理，应用启动仅验证连接；测试用 SQLite 可在隔离数据库中由 metadata 建表。认证采用短 access token、数据库 refresh token 与 `users.auth_version`，改密可即时撤销历史会话。

素材导出使用 `material_exports` 保存用户、子项目、进度阶段、字节数和 TOS 归档地址，并关联 `generation_jobs`。每次导出拥有独立 ID、临时目录和 TOS 对象键；不同子项目可并行执行且前端状态按 `taskId` 隔离。浏览器通过带 Access Token 的流式 Fetch 订阅 SSE，断线或刷新后以 PostgreSQL 状态恢复，SSE 只承担实时通知而不是事实存储。

ASS 大纲采用三层提示词结构：系统安全与技术约束、歌曲级视觉圣经、当前镜头执行契约。视觉圣经统一时间、天气、色彩和人物服装，同时规划多个可连续移动的场景位置及有限次数的视觉母题；每镜契约固定人物、地点、动作、情绪重点和镜头目的。
