# 本地开发

准备 Node.js 22、Python 3.11+、Docker Desktop。复制后端环境模板并填写本地密钥，密钥不得提交。

```bash
npm ci
python -m venv backend/.venv
backend/.venv/bin/pip install -i https://mirrors.tencent.com/pypi/simple -r backend/requirements-dev.txt
make dev          # 等价于组合加载 local-build 覆盖后 docker compose up -d
make preflight
```

日常流程：从 `main` 创建 `codex/feature-*` 或 `codex/fix-*`；小步提交；修改数据库时生成 Alembic migration；提交前运行 `make preflight-lite`（跳过 Docker 构建，约 85s），推送发布前运行完整 `make preflight`；推送并创建 PR。`main` 应始终可部署。按改动范围选择更小验证集的分层策略见 [`TESTING.md`](TESTING.md#耗时与针对性验证本机实测)。

常用命令见根目录 `Makefile`。本地数据库和 Redis 端口仅用于开发；服务器测试环境的部署覆盖文件会移除端口映射。

本机所有 docker compose 入口（`make dev`、`make docker-build`、`make preflight`）都会额外加载 `docker-compose.local-build.yml`，仅将本机 Node/Nginx 基础镜像切换到国内代理（默认 docker.1ms.run），并继续用官方 digest 锁定相同内容。手动执行 docker compose 命令时也必须带 `-f docker-compose.yml -f docker-compose.local-build.yml`——裸 `docker compose up -d --build` 直连 docker.io，拉取超时后可能静默失败、旧容器继续运行，造成“构建成功”的假象（判断依据：`docker compose ps` 的 Up 时间未重置）。服务器部署脚本不加载该覆盖文件，服务器镜像源和拉取配置不会受影响。

线上服务器使用的是腾讯云内网镜像加速器（mirror.ccs.tencentyun.com），仅限腾讯云 CVM 内网访问；本机不在腾讯云网络内，实测不可达，因此本机固定使用公网代理，不要照搬线上配置。

如需临时更换本机代理，可只对当前命令传入变量：

```bash
LOCAL_NODE_BASE_IMAGE='可用镜像地址' \
LOCAL_NGINX_BASE_IMAGE='可用镜像地址' \
make docker-build
```

不要通过本任务修改 Docker Desktop 全局 registry mirror；全局设置会影响本机所有项目，且难以保证与生产构建隔离。
