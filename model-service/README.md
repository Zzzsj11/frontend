# Company Model Service

独立模型服务，覆盖 MV 的 LLM、图片、视频及提示词优化调用。管理端与对外 API 是两个独立 Python 应用，管理前端为 Vue 3。四个目录可以单独复制、构建和发布；均不 import 父项目代码。

```
model-service/
  admin-web/       Vue 管理台，端口 5180
  user-web/        Vue 用户门户、API 文档与积分明细，端口 5181
  public-api/      FastAPI 对外 API + 独立 Worker，端口 8011
  admin-api/       FastAPI 管理 API，端口 8012
  migrations/     独立 Alembic 迁移（显式运行）
  scripts/        初始化、部署与配置导入
  tests/          合同、权限、恢复、浏览器测试
  docs/           API 与迁移文档
  .secrets/       本机内部凭据文档，Git 忽略
```

## 本地启动

需要 Python 3.12+、Node 22+。本机可复用父项目 Python 虚拟环境；服务源代码没有父项目运行时依赖。

```bash
python -m venv .venv
.venv/bin/pip install -r public-api/requirements.txt -r admin-api/requirements.txt
npm ci --prefix admin-web
npm ci --prefix user-web
.venv/bin/python scripts/dev.py start
```

首次启动会在 `.env` 生成随机管理员密码与 JWT Secret，文件权限 600。默认独立 SQLite 仅用于本机单 Worker 验收，不使用 MV 数据库。执行 `scripts/dev.py stop` 停止这一组本机进程。

生成服务须配置渠道密钥及 TOS。`.env.example` 是变量模板；也可显式运行 `scripts/import-mv-config.py --local` 从本机 MV 导入。实际密钥只进入忽略文件，不写管理前端或源码。

## 对外调用

管理员在「调用方密钥」创建公司系统专属 API Key。客户端携带 `Authorization: Bearer ...`、`X-User-Id` 和 `Idempotency-Key`。用户资源同时以 `client_id` 和 `user_id` 隔离。测试专属 Key 强制检查三个 Agent 头。

- `/v1/chat/completions`：OpenAI 兼容非流式/SSE。
- `/v1/messages`：Anthropic 消息协议。
- `/v1/videos`、`/v1/images`：统一参数的异步生成接口，服务端完成不同模型的协议转换。
- `/v1/jobs`：原生 payload 的高级异步工单接口。
- `/v1/jobs/{id}`：查询规范化结果、TOS 资产、原始用量。
- `/providers/{channel}/...`：迁移兼容接口，路径和模型双重白名单。
- `/docs`：自动生成 OpenAPI 文档。

详细协议与逐模型示例：[API-INTEGRATION.md](docs/API-INTEGRATION.md)。部署、迁移及未验证项：[DEPLOYMENT.md](docs/DEPLOYMENT.md)。

渠道余额与币种配置：[CHANNEL-BALANCES.md](docs/CHANNEL-BALANCES.md)。管理后台展示人民币、美元、积分原余额及人民币参考值；美元初始汇率 6.9，积分兑换比例按渠道配置。英和国内与海外共用 `scripts/yinghe-business.py` 查询余额、指定 Key 增量授权模型并复核。

## 独立发布约定

生产使用独立 PostgreSQL 数据库。管理端和对外端可以使用同库不同账号，数据库契约是双方唯一共享依赖。管理端没有供应商或 TOS 密钥，不调用公开服务的 Python 代码。管理模型开关等操作有意影响后续新任务，但单独重启、发布管理端不会重启公开 API 或 Worker。

生产部署前分别复制 `.env.public.example` 和 `.env.admin.example`，填写各自凭据。不要直接使用本机 `.env` 给所有容器注入同一组 Secret。

数据库迁移单独运行，两个应用启动时均不创建或修改表。所有业务表都有三个时间字段，删除操作为软删除；新版本迁移必须向前兼容旧版本两个服务。`db.py` 在两个部署包中明确复制，合同测试检查一致性。

```bash
DATABASE_URL=... .venv/bin/python -m alembic upgrade head
DATABASE_URL=... PYTHONPATH=public-api .venv/bin/python scripts/seed.py
VERSION=<不可变版本> scripts/deploy.sh admin
VERSION=<不可变版本> scripts/deploy.sh public
```

发布脚本只启动所选服务，使用版本化镜像和 `--no-deps`，不执行迁移、不碰 MV 容器。本机 Docker 构建必须同时加载 `docker-compose.yml` 和 `docker-compose.local-build.yml`，不直连 docker.io。

## 可靠性与成本

任务提交先落库。Worker 的提交标记先于上游 POST；提交结果不确定时转 `manual_review`，不自动重发。已有渠道 ID 的查询或 TOS 归档故障转 `recoverable`，管理端可恢复同一任务，不产生第二次生成。Worker 租约过期后，只有明确未提交或已有渠道 ID 的任务自动恢复。

模型并发和调用方并发在 PostgreSQL 事务锁下分配。Worker 与公开 API 必须使用同一个数据库。原始用量记录在工单上，缺失用量保留为空，不伪造零费用；未配置费率的用量不伪造金额。

管理员建号、用户自助创建 Key、账号与 Key 两级月上限、分模型/生成方式费率、月度额度、临时增减与逐任务积分见 [PORTAL-AND-CREDITS.md](docs/PORTAL-AND-CREDITS.md)。1 积分 = ¥0.01；支持实际用量 × 费率计价，保留每任务费率快照与不可覆盖的流水。
