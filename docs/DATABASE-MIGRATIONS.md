# 数据库迁移规范

所有结构变化使用 Alembic；保持单一 head；新增表必须有生命周期三字段；删除必须软删除。上线前运行 `scripts/check-migrations.sh`，并在空数据库和生产结构副本验证升级。

大改动采用 expand/contract。禁止同一版本直接重命名/删除仍被旧代码使用的列。Migration 不依赖外网，不写密钥，不执行不可控的大批量业务逻辑。
