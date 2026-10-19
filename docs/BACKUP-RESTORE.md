# 备份与恢复

`scripts/backup-postgres.sh` 生成 PostgreSQL custom dump 和 SHA-256，默认保留 30 天。服务器测试环境通过 cron 每日执行。目前脚本仅保存在服务器本地，尚未提供异地副本，不能抵御整机或磁盘丢失。按2026-10-19部署要求共用媒体 Bucket，通过环境备份目录隔离，使用 SSE-C AES256 密钥加密，并完成上传、下载及恢复演练。预发布和正式生产的备份目标、RPO/RTO 在 v1.0.0 后另行设计。

恢复是破坏性操作：先停止写流量，在隔离数据库执行恢复验证；正式恢复需 `CONFIRM_RESTORE=RESTORE scripts/restore-postgres.sh FILE.dump`。每月至少进行一次隔离恢复演练并记录耗时、行数和迁移版本。

可使用 `scripts/verify-backup.sh FILE.dump` 自动创建临时数据库、恢复、验证用户表并删除临时库。单机维护cron每日备份，并由 `scripts/verify-latest-backup.sh` 在每周日04:15验证最新备份；任务失败必须触发告警。dump与SHA-256文件成对保留30天。

## 可配置的异地同步

上传器已提供 `scripts/sync-backup-to-tos.sh FILE.dump`。可以配置独立私有 Bucket，或使用现有媒体 Bucket 加 SSE-C 密钥，授予读取该 Bucket ACL/策略及写入对象权限；可在 runtime secret 中配置独立 `BACKUP_TOS_ACCESS_KEY_ID` 与 `BACKUP_TOS_SECRET_ACCESS_KEY`，必须成对填写。跨地域 Bucket 可另设 `BACKUP_TOS_ENDPOINT`、`BACKUP_TOS_REGION`。未单独填写时使用现有 TOS 凭据，共用媒体 Bucket 时必须设置 `BACKUP_TOS_ENCRYPTION_KEY`，且目录仅允许 `mv/production/backups/` 或 `mv/test/backups/` 下的子目录。

```bash
BACKUP_TOS_BUCKET=<现有或独立Bucket> scripts/sync-backup-to-tos.sh /安全目录/FILE.dump
BACKUP_TOS_BUCKET=<现有或独立Bucket> scripts/install-maintenance-cron.sh
```

每日备份先写临时文件、成功后原子改名，再生成 SHA-256；配置 Bucket 后接着同步。独立 Bucket 模式拒绝公开 ACL/通配符策略；共用 Bucket 模式必须携带独立 SSE-C 密钥。两种模式均强制对象私有及 AES256 加密，并核对远端大小、校验信息、加密响应，另存校验文件；失败会使备份任务返回非零。应用回滚时上传器仍从当前版本化宿主目录只读挂载，不依赖旧镜像是否包含新脚本。尚未配置 Bucket 的环境仍只有本地备份，日志会明确提示。

真正启用前必须完成一次远端下载和隔离恢复；备份前缀的保留策略、异地地域及 RPO/RTO 由运维配置。不能把上传器单测通过等同于已获得异地灾备能力。
