# 回滚

测试或正式环境的应用回滚（先核对 [环境表](DEPLOYMENT.md#环境对应与发布顺序强制) 和 SSH 目标）：`DEPLOY_ENV=production ./scripts/rollback.sh`，或传入明确旧标签。`production` 是两套服务器沿用的环境文件名，实际环境以 `DEPLOYMENT_TIER` 和域名为准；回滚也必须保留对应平台域名和独立 Key。部署和回滚持有同一把进程锁，并从 `.deployment/info.json` 的 `previous` 读取上一个成功版本；重发同版本会保留这个指针。旧格式升级时先从已有版本文件取得缺失的指针。

数据库迁移遵循 expand/contract：先加兼容字段，再回填，再切换读写，最后隔多个版本删除旧字段。应用回滚通常不执行 Alembic downgrade。破坏性迁移发布前必须备份并给出专用恢复方案。

回滚后运行 `scripts/online-health-check.sh` 和远程 API/前端核心测试。若新版本已写入不兼容数据，停止写入并按事故手册处理，不得盲目 downgrade。

## 迁移后的应用回滚

`rollback.sh` 自动设置 `RUN_MIGRATIONS=0`，部署叠加 `docker-compose.rollback.yml`，直接启动 ASGI 服务，跳过旧镜像中可能无条件执行迁移的入口脚本。green 和正式 backend 使用同一覆盖配置；worker 入口不执行迁移。数据库保留新版 revision，禁止为通过健康检查而清空 Alembic 版本号。

回滚覆盖配置从发布检出的 `backend/app/proxy_entrypoint.py` 只读挂载 ASGI 入口。即使上一版本镜像没有该模块，容器仍按当前 Compose `frontend` 的 DNS 地址和显式 `TRUSTED_PROXY_NETWORKS` 识别代理，frontend 重建后的 IP 变化在 5 秒缓存到期后生效。

验收：在数据库升级后回滚兼容的上一镜像，确认 green 健康、正式服务和各类 worker 健康，并检查 `alembic_version` 保持原值。只有满足 expand/contract 兼容约束的版本可以这样回滚；不兼容变更须恢复备份及配套镜像。

### 分镜当前图片的唯一约束

迁移 `eb617531ca10` 在同一事务中锁住 `scene_assets` 的写入、保留每个镜头最新的当前图片，再创建唯一索引。普通查询仍可进行。首次升级采用 Worker 执行模式：先构建镜像，再让旧 `worker-image` 优雅排空并停止，确认旧实例已停止后再启动 green 迁移。API 可继续把图片请求写入队列，新图片 Worker 启动后处理积压。已有图片较多时给去重和建索引预留时间。

回滚应用版本会保留该索引。旧图片 Worker 未按镜头串行交付，同一镜头的两个工单同时完成时其中一个可能触发唯一约束错误。回滚前优雅排空将被替换的图片 Worker。回退到旧代码后，可只运行一个图片 Worker 实例并设置 `IMAGE_WORKER_CONCURRENCY=1`，确认没有其他实例或内联处理器同时认领图片工单。这样用户可以继续提交，工单会依次执行。重新部署带按镜头加锁的 Worker 后可恢复原并发。历史图片及软删除记录均保留。
