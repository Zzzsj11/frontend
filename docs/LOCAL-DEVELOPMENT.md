# 本地开发

准备 Node.js 22、Python 3.11+、Docker Desktop。复制后端环境模板并填写本地密钥，密钥不得提交。

```bash
npm ci
python -m venv backend/.venv
backend/.venv/bin/pip install -i https://mirrors.tencent.com/pypi/simple -r backend/requirements-dev.txt
docker compose up -d
make preflight
```

日常流程：从 `main` 创建 `codex/feature-*` 或 `codex/fix-*`；小步提交；修改数据库时生成 Alembic migration；提交前运行 `make preflight`；推送并创建 PR。`main` 应始终可部署。

常用命令见根目录 `Makefile`。本地数据库和 Redis 端口仅用于开发；生产覆盖文件会移除端口映射。
