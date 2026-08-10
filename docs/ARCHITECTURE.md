# 技术架构

项目是 Vue 3 + TypeScript 前端、FastAPI + SQLAlchemy 后端、PostgreSQL 持久化、Redis 缓存/任务状态、TOS 媒体存储的 MV AI 生产平台。Nginx 托管前端并代理 `/api`。

主要领域：认证和多用户隔离、项目/子项目、ASS 与通用分镜、系统及私有人物、场景/视频/音频资产、模型注册、生成任务、Token 用量、错误日志、管理后台。

生成链路：前端提交任务，后端校验用户和模型，创建 `generation_jobs`，调用供应商，原媒体及缩略图导入 TOS，资产记录入 PostgreSQL，用量写入账本。列表只加载缩略图，用户交互时才加载原图或视频。

统一供应商配置通过 Docker Secret `provider_config` 挂载。检测到其中的 `AIGC_TOKEN` 时，文本模型 Token、聊天 API 地址和默认模型作为同一个配置组生效，优先于遗留的 `LLM_*` 环境变量，避免共享 Token 被误发往其他供应商；只有未配置统一供应商 Secret 时才启用独立 `LLM_*` 配置。

当前任务执行仍在 API 进程内。后续迁移 Worker 时必须保持 `generation_jobs` 状态机和接口契约，先双写/灰度，再切换执行器；详见 `TODO_MODEL_EXPANSION.md`。
