# Code Agent 工作约定

开始工作前依次阅读 `README.md`、`docs/ARCHITECTURE.md`、`docs/LOCAL-DEVELOPMENT.md` 和与任务相关的专题文档。

强制约束：所有新增业务表包含 `created_at`、`updated_at`、`deleted_at`；所有删除均为软删除；用户私有数据必须按 `user_id` 隔离；系统人物只读；媒体原文件和缩略图均进入 TOS；任何模型调用必须记录用量；数据库修改只能通过 Alembic。

交付前执行 `make preflight`。涉及用户旅程、API、部署或权限时，还要运行对应 Playwright 测试。禁止提交 `.env`、密钥、测试媒体、备份和构建产物。禁止直接修改生产服务器源码；发布使用版本化镜像和 `scripts/deploy.sh`。

重要入口：后端 `backend/app/main.py`，领域 API `backend/app/domain.py`，管理 API `backend/app/admin.py`，前端路由 `src/router.ts`，主状态 `src/stores/project.ts`，测试说明 `docs/TESTING.md`。

前端代码须遵循 `docs/FRONTEND-GUIDELINES.md`（组件、样式令牌、弹层与 z-index 层级规范）；格式由 Prettier 统一，`make lint-frontend` 包含 `format:check` 卡口。
