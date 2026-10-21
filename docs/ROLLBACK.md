# 回滚

测试或正式环境的应用回滚（先核对 [环境表](DEPLOYMENT.md#环境对应与发布顺序强制) 和 SSH 目标）：`DEPLOY_ENV=production ./scripts/rollback.sh`，或传入明确旧标签。`production` 是两套服务器沿用的环境文件名，实际环境以 `DEPLOYMENT_TIER` 和域名为准；回滚也必须保留对应平台域名和独立 Key。部署脚本保存 `.previous-version`。

数据库迁移遵循 expand/contract：先加兼容字段，再回填，再切换读写，最后隔多个版本删除旧字段。应用回滚通常不执行 Alembic downgrade。破坏性迁移发布前必须备份并给出专用恢复方案。

回滚后运行 `scripts/online-health-check.sh` 和远程 API/前端核心测试。若新版本已写入不兼容数据，停止写入并按事故手册处理，不得盲目 downgrade。

## 迁移后的应用回滚

`rollback.sh` 自动设置 `RUN_MIGRATIONS=0`，部署叠加 `docker-compose.rollback.yml`，直接启动 ASGI 服务，跳过旧镜像中可能无条件执行迁移的入口脚本。green 和正式 backend 使用同一覆盖配置；worker 入口不执行迁移。数据库保留新版 revision，禁止为通过健康检查而清空 Alembic 版本号。

验收：在数据库升级后回滚兼容的上一镜像，确认 green 健康、正式服务和各类 worker 健康，并检查 `alembic_version` 保持原值。只有满足 expand/contract 兼容约束的版本可以这样回滚；不兼容变更须恢复备份及配套镜像。
