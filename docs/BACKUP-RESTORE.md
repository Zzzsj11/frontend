# 备份与恢复

`scripts/backup-postgres.sh` 生成 PostgreSQL custom dump 和 SHA-256，默认保留 30 天。服务器测试环境通过 cron 每日执行，并把需要长期保留的备份同步到独立、加密、开启生命周期的 Bucket。预发布和正式生产的备份目标、RPO/RTO 在 v1.0.0 后另行设计。

恢复是破坏性操作：先停止写流量，在隔离数据库执行恢复验证；正式恢复需 `CONFIRM_RESTORE=RESTORE scripts/restore-postgres.sh FILE.dump`。每月至少进行一次隔离恢复演练并记录耗时、行数和迁移版本。

可使用 `scripts/verify-backup.sh FILE.dump` 自动创建临时数据库、恢复、验证用户表并删除临时库。单机维护cron每日备份，并由 `scripts/verify-latest-backup.sh` 在每周日04:15验证最新备份；任务失败必须触发告警。dump与SHA-256文件成对保留30天。
