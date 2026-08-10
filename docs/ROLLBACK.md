# 回滚

当前服务器测试环境的应用回滚：`DEPLOY_ENV=production ./scripts/rollback.sh`，或传入明确旧标签。`production` 是脚本沿用的历史环境文件名，并不代表当前已有正式生产环境。部署脚本保存 `.previous-version`。

数据库迁移遵循 expand/contract：先加兼容字段，再回填，再切换读写，最后隔多个版本删除旧字段。应用回滚通常不执行 Alembic downgrade。破坏性迁移发布前必须备份并给出专用恢复方案。

回滚后运行 `scripts/online-health-check.sh` 和远程 API/前端核心测试。若新版本已写入不兼容数据，停止写入并按事故手册处理，不得盲目 downgrade。
