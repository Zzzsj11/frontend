# 部署指南（v1.0.0 前）

本文给维护人员和 Code Agent 提供可直接照做的部署手册。当前只维护两个环境：

| 环境           | 用途                                     | 入口                         | 数据             |
| -------------- | ---------------------------------------- | ---------------------------- | ---------------- |
| 本地开发环境   | 开发、单元测试、完整预检                 | `http://127.0.0.1:5173`      | 本地 Docker 卷   |
| 服务器测试环境 | 业务方手工验收、远程 API/Playwright 回归 | `http://120.24.38.200`       | 服务器 Docker 卷 |

v1.0.0 完成前不建设预发布或正式生产环境，也不通过域名执行业务回归。远程测试固定使用服务器 IP 和 HTTP `80` 端口。当前发布方式是在服务器从 Git 获取指定提交，并在服务器本地构建带 Git SHA 的版本化镜像。

## 1. 部署原则

- 只部署已经提交并推送到 Git 远端的代码，服务器工作区必须干净。
- 禁止直接在服务器修改源码；修复必须在本地完成、测试、提交、推送后重新部署。
- 镜像标签固定为 `git-<完整 commit SHA>`，便于定位和回滚。
- `.env`、供应商 Token、TOS 密钥、数据库密码和 JWT 密钥只保存在服务器，不提交 Git。
- 数据库结构只通过 Alembic 更新；发布时后端入口会自动执行迁移。
- backend 采用一次性 green 容器平滑切换：新版本先通过健康检查再接管流量，部署窗口不再产生 502；nginx 通过 Docker 内嵌 DNS 运行时解析上游，无需重启即可感知 backend 容器 IP 变化。
- PostgreSQL 和 Redis 不开放公网，维护时使用 SSH 隧道。
- 发布前在本地执行 `make preflight`；发布后执行服务器健康检查和远程自动化测试。

## 2. 本地部署与验证

### 2.1 首次准备

```bash
git clone <仓库地址> mv-agent-frontend
cd mv-agent-frontend
cp backend/.env.example backend/.env
```

填写 `backend/.env`，并按项目现有供应商配置准备 `backend/.provider_config.py`。这两个文件均被 Git 忽略。然后运行：

```bash
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:5173/api/health  # 对外仅返回 {"ok":true}
```

浏览器访问 `http://127.0.0.1:5173`。首次管理员默认为 `admin / 123456`，仅限本地首次启动，登录后立即修改。

### 2.2 发布前验证

```bash
make preflight
git status --short
git rev-parse HEAD
```

`make preflight` 必须通过，`git status --short` 应无输出。涉及用户旅程、API、权限或部署时，继续按 [`TESTING.md`](TESTING.md) 运行对应 Playwright。确认后提交并推送：

```bash
git push origin <当前分支>
```

记录准备部署的完整 SHA；服务器必须检出同一个 SHA，不能仅凭本地文件内容判断版本。

## 3. 登录服务器

当前服务器：

```text
主机：120.24.38.200
用户：ubuntu
项目目录：/opt/mv-agent-frontend
Web 端口：5173
```

### 3.1 配置 SSH 公钥（首次执行）

在开发机检查已有公钥：

```bash
ls -l ~/.ssh/*.pub
```

如没有，创建专用密钥。不要把私钥发给任何人，也不要提交仓库：

```bash
ssh-keygen -t ed25519 -C "mv-agent-deploy" -f ~/.ssh/mv_agent_deploy
```

将公钥安装到服务器（该步骤可能需要输入服务器登录密码）：

```bash
ssh-copy-id -i ~/.ssh/mv_agent_deploy.pub root@120.24.38.200
```

如果开发机没有 `ssh-copy-id`，显示公钥并由服务器管理员把这一整行追加到 `/home/ubuntu/.ssh/authorized_keys`：

```bash
cat ~/.ssh/mv_agent_deploy.pub
```

服务器端权限应为：

```bash
chmod 700 /home/ubuntu/.ssh
chmod 600 /home/ubuntu/.ssh/authorized_keys
chown -R ubuntu:ubuntu /home/ubuntu/.ssh
```

### 3.2 建议的本机 SSH 配置

在 `~/.ssh/config` 添加以下内容，并执行 `chmod 600 ~/.ssh/config`：

```sshconfig
Host mv-agent-test
  HostName 120.24.38.200
  User root
  IdentityFile ~/.ssh/mv_agent_deploy
  IdentitiesOnly yes
  ServerAliveInterval 30
  ServerAliveCountMax 3
```

之后直接登录：

```bash
ssh mv-agent-test
```

未配置别名时使用：

```bash
ssh -i ~/.ssh/mv_agent_deploy root@120.24.38.200
```

首次连接要核对服务器指纹；不要在不确认主机身份时盲目接受变更后的指纹。登录后先确认身份和主机：

```bash
whoami
hostname
sudo -n true && echo "sudo 可用"
```

## 4. 服务器首次初始化

以下操作只在新服务器首次部署时执行。服务器当前为 Ubuntu，使用 `sudo`，不要假设存在 `root` 登录或 `sudo` 用户组。

### 4.1 安装基础工具和 Docker

优先按照 Docker 官方 Ubuntu 仓库安装 Docker Engine 与 Compose v2。安装后验证：

```bash
docker --version
docker compose version
git --version
curl --version
```

将 `ubuntu` 加入 Docker 用户组，然后重新登录使组权限生效：

```bash
sudo usermod -aG docker ubuntu
exit
```

重新 SSH 登录后：

```bash
docker info >/dev/null && echo "Docker 可用"
```

### 4.2 创建项目目录并克隆

```bash
sudo mkdir -p /opt/mv-agent-frontend
sudo chown ubuntu:ubuntu /opt/mv-agent-frontend
git clone <仓库 SSH 或 HTTPS 地址> /opt/mv-agent-frontend
cd /opt/mv-agent-frontend
```

私有仓库需要给服务器单独配置只读 deploy key 或其他受控 Git 凭证；不要复制个人 Git 私钥到服务器。

#### GitHub 不可达时的服务器裸仓库通道

中国大陆服务器访问 GitHub 可能超时。当前服务器已经准备了专用裸仓库 `/opt/mv-agent-frontend.git`，线上工作区将它配置为 `server` 远端。该通道仍是完整 Git 发布：开发机把已提交的对象推入裸仓库，线上工作区只执行 `fetch` 和 `--ff-only` 快进；禁止用 `scp`、`rsync` 或压缩包直接覆盖线上源码。

新服务器首次配置该通道时，在服务器执行：

```bash
sudo git init --bare /opt/mv-agent-frontend.git
sudo chown -R ubuntu:ubuntu /opt/mv-agent-frontend.git
cd /opt/mv-agent-frontend
git remote add server /opt/mv-agent-frontend.git
git remote -v
```

如果 `server` 已存在，不要重复添加。开发机不必永久增加远端，可以直接使用 SSH URL 推送。先确认开发机已把同一提交推送到 GitHub；随后在开发机执行：

```bash
git status --short
git rev-parse HEAD
git push ssh://root@120.24.38.200/opt/mv-agent-frontend.git main:main
```

如使用 `mv-agent-test` SSH 别名，URL 可写成 `ssh://mv-agent-test/opt/mv-agent-frontend.git`。出现“Git LFS locking API 不受支持”的提示不影响当前仓库，因为发布内容不依赖 Git LFS 锁；真正的推送失败必须处理，不能继续部署。

### 4.3 创建服务器配置

当前脚本内部沿用 `.env.production` 这个历史文件名，但它在 v1.0.0 前仅代表“服务器测试环境”，不代表正式生产环境：

```bash
cd /opt/mv-agent-frontend
cp .env.deploy.example .env.production
cp backend/.env.example backend/.env
chmod 600 .env.production backend/.env
```

编辑 `.env.production`，至少替换：

```dotenv
REGISTRY=mvagent-local
JWT_SECRET=<至少 32 字节的随机值>
POSTGRES_DB=mvagent
POSTGRES_USER=mvagent
POSTGRES_PASSWORD=<强随机密码>
FRONTEND_PORT=80
BACKEND_PORT=8000
```

可用以下命令分别生成 JWT 和数据库密码，输出只写入服务器配置，不发到聊天或日志：

```bash
openssl rand -hex 32
openssl rand -base64 36
```

继续填写 `backend/.env` 与 `backend/.provider_config.py` 中的模型、TOS、余额查询等配置：

```bash
chmod 600 backend/.provider_config.py
```

启用单机Worker拆分时，在服务器 `.env.production` 增加：

```dotenv
JOB_EXECUTION_MODE=worker
COMPOSE_PROFILES=workers
MEDIA_WORKER_CONCURRENCY=4
EXPORT_WORKER_CONCURRENCY=1
CHAT_WORKER_CONCURRENCY=2
STORYBOARD_WORKER_CONCURRENCY=2

生产单机建议使用 `sudo PROJECT_DIR=/opt/mv-agent-frontend scripts/install-monitoring-systemd.sh` 安装 30 秒监控 timer；`install-maintenance-cron.sh` 会检测该 timer，仅在未启用时保留一分钟采集兜底。监控字段、容量口径和告警阈值见 `docs/ARCHITECTURE-CAPACITY-AND-OBSERVABILITY.md`。
WORKER_STALE_SECONDS=180
```

`worker-media`、`worker-export`、`worker-chat` 与 `worker-storyboard` 必须和 backend 使用同一个版本化后端镜像。4核测试机上导出并发固定为1，分镜编排并发建议2；不要把 `JOB_EXECUTION_MODE` 切为 `worker` 却遗漏 `COMPOSE_PROFILES=workers`，否则新任务只会排队而无人领取。

统一供应商配置启用 `AIGC_TOKEN` 时，聊天地址和默认文本模型必须来自同一配置组；不要保留指向其他厂商的旧 `LLM_BASE_URL`、`LLM_API_KEY` 或 `LLM_MODEL`。任何核验命令都不得打印 Token。

当前测试服务器安全组/防火墙只需对验收人员开放 SSH `22/tcp` 和 Web `80/tcp`。后端 `8000` 只绑定回环地址，PostgreSQL/Redis 在服务器部署覆盖中不映射宿主机端口。

## 5. 每次发布的标准流程

### 5.1 本地侧

```bash
cd <本机仓库目录>/mv-agent-frontend
make preflight
git status --short
git rev-parse HEAD
git push origin <当前分支>
```

只有目标提交已进入服务器跟踪的分支后才继续。如果采用 `main`，应先通过正常合并流程进入 `main`。

### 5.2 服务器获取精确版本

优先使用 GitHub 远端。在服务器执行：

```bash
ssh mv-agent-test
cd /opt/mv-agent-frontend
git status --short
git fetch --prune origin
git switch main
git pull --ff-only origin main
git rev-parse HEAD
```

若 `git status --short` 有输出，立即停止。不要 stash、覆盖或删除未知文件；先查明服务器为何存在源码改动。确认 `git rev-parse HEAD` 与待发布 SHA 完全一致。

如果 `git fetch origin` 长时间无输出，用带超时的只读命令确认是否为 GitHub 网络问题：

```bash
timeout 20 git ls-remote origin HEAD
curl -I --max-time 10 https://github.com
```

两者均超时时，不要持续重试占用发布窗口，也不要改线上源码。改用上一节的服务器裸仓库通道：先在开发机执行 `git push ssh://root@120.24.38.200/opt/mv-agent-frontend.git main:main`，再在服务器执行：

```bash
cd /opt/mv-agent-frontend
git status --short
git fetch server main
git switch main
git merge --ff-only server/main
git rev-parse HEAD
git status --short
```

最终必须同时满足：服务器完整 SHA 与开发机待发布 SHA 完全一致、服务器 `git status --short` 无输出。不要手工拼写完整 SHA；直接复制 `git rev-parse HEAD` 的输出，或使用以下双端核对方式：

```bash
# 开发机
git rev-parse HEAD

# 服务器
ssh mv-agent-test 'cd /opt/mv-agent-frontend && git rev-parse HEAD && git status --short'
```

### 5.3 构建版本化镜像并部署

```bash
cd /opt/mv-agent-frontend
chmod +x scripts/deploy-local-images.sh scripts/deploy.sh
DEPLOY_ENV=production ./scripts/deploy-local-images.sh
```

这个命令会：

1. 拒绝脏工作区；
2. 读取当前完整 Git SHA；
3. 构建 `mvagent-local/mv-agent-frontend:git-<sha>` 和后端镜像；
4. 不从远程镜像仓库拉取；首次部署会先启动并等待 PostgreSQL、Redis 健康，后续发布为空操作；
5. 先更新 frontend 容器（新 nginx 配置先就绪）；
6. 平滑切换 backend：用新镜像启动一次性 green 容器 `mv-backend-green`（`compose run` 继承服务的环境/密钥/网络别名），健康检查通过后重建正式容器——整个窗口内始终有健康上游，nginx 不会返回 502；green 未通过健康检查则打印其日志并中止部署，当前版本继续服务；
7. 等待正式 backend 健康检查后删除 green 容器，并兜底更新其余服务；
8. 将当前和上一版本写入 `.deployed-version`、`.previous-version`。

切换期间新旧 backend 短暂共存并共同承接流量（共享同一数据库），因此每次发布必须保持 API 向后兼容；数据库迁移遵循 expand/contract。

构建期间另开一个 SSH 会话观察资源，避免误以为进程卡死：

```bash
docker stats
df -h
docker system df
```

不要在构建未结束时重复启动第二次构建。失败时先保留完整日志，根据“8. 排障”处理。

## 6. 发布后验证

### 6.1 服务器内检查

```bash
cd /opt/mv-agent-frontend
export RELEASE_VERSION="$(cat .deployed-version)"
printf 'RELEASE_VERSION=%s\n' "$RELEASE_VERSION"
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.production.yml ps
curl -fsS http://127.0.0.1:8000/api/health
curl -fsS http://127.0.0.1:80/api/health
./scripts/online-health-check.sh
```

检查迁移和最近日志：

```bash
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.production.yml exec backend alembic current
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.production.yml logs --tail=200 backend frontend
```

`docker-compose.production.yml` 的镜像名要求 `RELEASE_VERSION`。若未先从 `.deployed-version` 导出，会出现 `required variable RELEASE_VERSION is missing`；这是检查命令缺少参数，不代表容器故障。

日志中不得出现持续重启、迁移失败、数据库认证失败或供应商密钥缺失。

### 6.2 开发机远程验收

```bash
curl -fsS http://120.24.38.200/api/health
# 凭据写入 e2e/.env（模板见 e2e/.env.example）后免环境变量直跑
npm run test:remote:api && npm run test:remote:frontend
```

真实模型与媒体生成会产生费用，仅在明确需要全链路验收时按 [`TESTING.md`](TESTING.md)「真实生成全链路」显式开启；远程验收命令与上线验收清单见同一文档。

### 6.3 安装维护任务（首次成功部署后）

```bash
cd /opt/mv-agent-frontend
MAINTENANCE_LOG_DIR=/var/lib/docker/mv-agent-maintenance/logs \
BACKUP_DIR=/var/lib/docker/mv-agent-maintenance/backups \
  ./scripts/install-maintenance-cron.sh
crontab -l
```

该脚本安装每5分钟健康检查、每分钟宿主机资源采样、每日03:15 PostgreSQL备份及每周日04:15隔离恢复验证。测试服务器把日志和本机备份放在200 GB数据盘的 `/var/lib/docker/mv-agent-maintenance/`，避免占满40 GB系统盘。资源采样读取默认路由公网网卡，只把发送字节增量计入自然月流量；配额按 `300 × 1024³` 字节计算。备份还需按 [`BACKUP-RESTORE.md`](BACKUP-RESTORE.md) 同步到独立对象存储。

## 7. 数据库和 Redis 安全访问

默认不开放数据库端口。需要从开发机维护 PostgreSQL 时建立 SSH 隧道：

```bash
ssh -N -L 15433:127.0.0.1:5433 mv-agent-test
```

但服务器部署覆盖默认移除了宿主机 PostgreSQL 端口；更稳妥的日常检查是在服务器容器内执行：

```bash
cd /opt/mv-agent-frontend
set -a
source .env.production
set +a
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.production.yml \
  exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

若确需 GUI 隧道访问，应创建只绑定 `127.0.0.1` 的运维覆盖文件，部署后立即移除；禁止将 `5432/5433` 或 `6379/6380` 暴露到 `0.0.0.0`。Redis 检查优先使用：

```bash
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.production.yml exec redis redis-cli ping
```

## 8. 常见故障排查

### SSH 连接失败

```bash
ssh -vvv mv-agent-test
```

依次检查云安全组 `22/tcp`、用户名是否为 `ubuntu`、IdentityFile 是否正确、服务器 `authorized_keys` 权限和磁盘是否已满。`REMOTE HOST IDENTIFICATION HAS CHANGED` 必须先人工核对服务器指纹，不要直接删除 known_hosts 记录后重试。

### Git 更新失败

- `git status --short` 非空：停止部署，确认改动来源。
- `git pull --ff-only` 失败：说明服务器分支发生分叉，禁止强制 reset；在本地整理分支后再部署。
- 私有仓库认证失败：检查服务器 deploy key 是否仍有仓库只读权限。
- 服务器访问 GitHub 超时：按 4.2 和 5.2 使用 `/opt/mv-agent-frontend.git` 裸仓库通道，仍然只允许 Git fast-forward 发布。

### Docker 构建慢或失败

```bash
docker system df
df -h
free -h
journalctl -u docker --since "30 min ago" --no-pager
```

不要同时运行多个构建。只清理确认不再用于回滚的旧镜像；不要执行会删除卷的命令。依赖源变更必须先在本地验证并提交到 Git，禁止只改服务器 Dockerfile。

Compose 输出 `buildx isn't installed` 时会回退到 Docker 默认 builder；只要后续镜像构建完成即可。若要消除警告，应在独立维护窗口安装与当前 Docker Engine 匹配的 Buildx 插件，不要在发布过程中临时切换构建器。

### 服务不健康

```bash
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.production.yml ps
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.production.yml logs --tail=300 backend
curl -v http://127.0.0.1:8000/api/health
```

优先定位迁移、配置、数据库、Redis、磁盘和上游供应商错误，不要反复重启掩盖首个异常。

### 部署中止于 green 健康检查

`deploy.sh` 输出 `green backend health check failed` 表示新版本容器未通过健康检查，脚本已打印 green 容器最后 100 行日志并中止，当前版本仍在正常服务。按日志定位迁移、配置或供应商问题，修复后重新部署；不要跳过失败直接强启旧流程。

## 9. 回滚

先读取版本记录：

```bash
cd /opt/mv-agent-frontend
cat .deployed-version
cat .previous-version
```

服务器本地仍保留上一版本镜像时执行：

```bash
DEPLOY_ENV=production ./scripts/rollback.sh
```

回滚后重复第 6 节全部健康检查和核心远程测试。数据库迁移一般不自动 downgrade；涉及不兼容数据或破坏性迁移时，立即停止写入并按 [`ROLLBACK.md`](ROLLBACK.md) 与 [`INCIDENT-RUNBOOK.md`](INCIDENT-RUNBOOK.md) 处理。

## 10. v1.0.0 后再评估的事项

预发布、正式生产环境、域名/HTTPS、远程镜像仓库、自动发布审批均不属于当前部署路径。backend 已在单机上用一次性 green 容器实现平滑切换（消除部署 502 窗口），多副本蓝绿/滚动发布与发布治理仍在 v1.0.0 后再评估。v1.0.0 功能与验收稳定后，再单独设计环境隔离、Secret 管理、容量、安全和发布治理；在此之前不要让未来方案干扰服务器测试环境的可重复部署。
