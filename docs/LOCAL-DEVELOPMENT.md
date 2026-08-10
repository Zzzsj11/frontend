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

常用命令见根目录 `Makefile`。本地数据库和 Redis 端口仅用于开发；服务器测试环境的部署覆盖文件会移除端口映射。

`make preflight` 的 Docker 构建会额外加载 `docker-compose.local-build.yml`，仅将本机 Node/Nginx 基础镜像切换到国内代理，并继续用官方 digest 锁定相同内容。服务器部署脚本不加载该覆盖文件，服务器镜像源和拉取配置不会受影响。

如需临时更换本机代理，可只对当前命令传入变量：

```bash
LOCAL_NODE_BASE_IMAGE='可用镜像地址' \
LOCAL_NGINX_BASE_IMAGE='可用镜像地址' \
make docker-build
```

不要通过本任务修改 Docker Desktop 全局 registry mirror；全局设置会影响本机所有项目，且难以保证与生产构建隔离。
