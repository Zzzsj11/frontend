# 部署与 MV 迁移

## 进程与权限边界

四个独立构建上下文、四个版本化镜像运行五个服务，不读取父项目代码：

| 镜像 | 服务 | 主机监听 | 发布组 |
| --- | --- | --- | --- |
| `model-public` | `public-api`、`worker` | `127.0.0.1:8011`；Worker 无端口 | `public` |
| `model-admin` | `admin-api` | `127.0.0.1:8012` | `admin` |
| `model-admin-web` | `admin-web` | `127.0.0.1:5180` | `admin` |
| `model-user-web` | `user-web` | `127.0.0.1:5181` | `user` |

管理 API 只持有管理凭据和自己的数据库账号；供应商、渠道业务与 TOS 凭据只注入公开 API/Worker。本次同机部署不新增公网入口，不修改 MV 根 Compose 或现有网络权限。运维和浏览器验收走 SSH loopback 隧道；数据库不得暴露公网。

沿用现有 MV PostgreSQL **实例**，但新建独立 `model_service` **数据库**与三个互不混用的角色，由运维创建并授权：

- `model_migration`：数据库/schema/迁移对象 owner，负责 Alembic 和 seed；只进入一次性迁移容器。
- `model_public`：公开 API 与 Worker 共用运行角色，读取模型/路由/费率配置，按业务需要读写用户、Key、工单、账本、渠道余额等表。门户已包含用户与额度业务，不能仍只授予 clients 只读权限。
- `model_control`：管理 API 运行角色，管理模型、路由、Key、费率、审计和额度，查询工单并更新恢复状态、读取渠道余额快照。

两个运行角色不得是 owner、superuser 或 migration 角色成员，不授予 DDL/物理 DELETE，也不得访问 MV 业务库。运维须核对现有 `PUBLIC` 权限，分别为目标库/schema、现有表及后续迁移对象配置必要的 CONNECT、USAGE 和 DML 权限；迁移后再次核验授权，不能用 owner 凭据临时顶替运行账号。管理员停用 Key 后新请求立即被拒绝，已接受任务保留对账记录。

`.env.public`、`.env.admin`、`.env.migration` 三份文件权限均为 600，不提交 Git，不复用本机包含全套凭据的 `.env`。前两份按各自 example 填写运行角色，数据库主机均为 `postgres:5432`、数据库均为 `model_service`。`.env.admin` 不含任何供应商/TOS 凭据；`.env.migration` 仅配置 owner 数据库 URL（密码中的特殊字符须 URL 编码），例如：

```dotenv
DATABASE_URL=postgresql+asyncpg://model_migration:<URL-encoded-password>@postgres:5432/model_service
```

`.env.migration` 由 `docker run --env-file` 读取，值两侧不能加引号（Docker 会保留引号，导致数据库 URL 无效）。`.env.public` 和 `.env.admin` 由 Compose 读取，使用单引号保护密码中的 `$` 等字符；两类文件不要混用序列化格式。

内部业务系统得到的是自身专属 Key，不是英和原始 Key。不要将 `.env*` 实值、`.secrets`、数据库、测试视频或 dist 提交 Git，也不要将 `docker inspect` 环境变量或 Compose 展开后的凭据输出到验收报告。

## 同机网络与初始化

`docker-compose.mv.yml` 是独立服务自身的覆盖文件：公开 API、Worker、管理 API 同时保留本项目 `default` 网络并加入既有 external MV 网络。Web 仍只在本项目网络，以 `public-api`/`admin-api` 访问各自 API。公开 API 在 MV 网络声明 `model-public` 别名，数据库 DNS 为既有的 `postgres`。

- 默认 MV 网络：`mv-agent-frontend_default`；如线上项目名不同，显式设置 `MV_DOCKER_NETWORK`。
- **每次同机发布和迁移均设置 `DEPLOY_MV=1`**，避免后续发布漏载覆盖文件而移除跨项目连接。
- 网络和 PostgreSQL 必须已经存在；脚本不创建数据库、角色、网络，不改根 Compose。
- 首次部署前准备数据库、三角色及 TOS 桶/域名，备份现有数据。服务尚未启动时即可在既有 MV 网络运行迁移。

## 显式迁移与独立发布

需要 Docker Compose v2.20+（支持 `up --wait --wait-timeout`）。先准备**同一不可变版本**的四个镜像，以及该版本的 Compose、`migrations/`、`alembic.ini`、`scripts/seed.py` 和运维脚本。`VERSION` 不得为 `latest`，不得覆盖已发布标签。API 镜像故意不包含迁移文件；不要用当前开发目录的迁移去配旧版镜像。

以下命令在服务器的 `model-service/` 发布目录执行；此处仅为运维入口，不表示线上已完成执行：

```bash
export VERSION=<不可变版本>
export MODEL_IMAGE_REGISTRY=<镜像仓库前缀>
export DEPLOY_MV=1
# 自定义网络时同时 export MV_DOCKER_NETWORK=<已存在网络名>

# 迁移使用已拉取或已构建的 public 镜像；已预装时跳过此命令。
docker pull "$MODEL_IMAGE_REGISTRY/model-public:$VERSION"
scripts/migrate.sh

# 迁移与运行角色授权核验成功后，分组发布；public API 与 Worker 同版。
scripts/deploy.sh public
scripts/deploy.sh admin
scripts/deploy.sh user
```

`migrate.sh` 使用版本化 public 镜像的一次性 `docker run --rm --pull never` 容器，先 `alembic upgrade head`，成功后才执行 seed。仅只读挂载 `migrations/`、`alembic.ini`、`scripts/seed.py` 三个发布产物；不会挂载整个仓库、Secret 目录或运行端 env 文件。`.env.migration` 仅通过 `--env-file` 注入该临时容器，不 source 到宿主 shell，也不进入任何常驻容器。seed 仅补充缺失模型，不覆盖管理端配置。迁移失败立即停止发布；不得自动降级或重新生成工单。

不使用 MV 同机覆盖时，迁移默认连接已存在的 `company-model-service_default` 网络，也可设置 `MIGRATION_DOCKER_NETWORK` 为能访问数据库的既有网络；`DEPLOY_MV=1` 时统一以 `MV_DOCKER_NETWORK` 为准。

已在目标主机构建或预装版本化镜像时，使用 `DEPLOY_SKIP_PULL=1 scripts/deploy.sh public|admin|user`（末尾选择一个组）。该模式不拉取、不构建；缺少所选镜像会失败，不隐式访问仓库。普通模式仅 pull 所选组，随后所有模式均以 `--no-deps --no-build --pull never --wait` 启动所选服务。`user` **仅发布 user-web**，不重启公开 API/Worker 或管理端；管理发布同样不触碰 public。首次发布 Web 前，其代理指向的 API 须已启动。

默认健康等待 120 秒，可用 `DEPLOY_WAIT_TIMEOUT` 调整。两个 API 检查 `/health` 的 `ok=true`（包含数据库查询）；两个 Web 检查本容器 HTTP 首页；Worker 仅验证 PID 1 是存活的 `gateway.queue` 进程，**不证明队列推进、供应商或 TOS 可用**。失败返回非零，不自动回滚、不重启未选服务；`restart: unless-stopped` 也不会仅因 unhealthy 自动重启。Compose 的 CPU/内存上限用于限制同机竞争，须结合线上余量和 OOM/并发指标评估。

回滚使用前一兼容镜像版本重新发布所选组，不降级数据库、不恢复退役配置。升级迁移遵循扩展—迁移—收缩，旧服务须仍能读取新 schema。本机若需 Docker 构建必须额外加载 `docker-compose.local-build.yml` 使用镜像代理；本节服务器发布不加载本机构建覆盖。

## MV 迁移开关

### 首次目录与生成就绪

`0006` 包含冻结的 `migrations/data/catalog-20260922.json`：首次安装选定的 19 个统一模型、38 条供应商路由和参考报价，必须随 migrations 目录发布。新路由保持关闭、待验收，正式扣费规则不由报价推导。已有记录（含软删除）不覆盖；发现统一目录后，旧 seed 不再追加、开启旧目录模型。

「模型供应商 → 登记验收」可关联已有成功 Agent 工单，登记参数、产物与用量审核；服务端验证其归因及路由快照。登记不会生成，也不自动启用。随后单独启用已验收路由，在「生成方式费率」发布正式费率和预占额度。受控 Key 缺少正式费率时继续拒绝提交。

在装有服务依赖的运维环境执行 `python scripts/release-readiness.py --env-file .env.public`。容器内可只读挂载脚本到 `/release/scripts/release-readiness.py`，设置 `PYTHONPATH=/service` 后执行。无可用路由、未登记验收、缺少凭据或正式费率时返回非零；`--catalog-only` 明确仅检查目录/报价阶段，仍报告阻断原因，不表示生成就绪。本检查不代替逐规格验收。

Worker 接收 SIGTERM/SIGINT 后停止领取，默认等待 105 秒（`WORKER_DRAIN_SECONDS`，需小于 Compose 的 120 秒停止宽限）。超时的已确认任务排队恢复查询/归档；提交结果不确定的任务转人工核账，不能自动重发。余额采集随停机取消。

### MV 业务配置

MV 增加了 `MODEL_GATEWAY_URL`、`MODEL_GATEWAY_API_KEY`。默认留空，现有线上直连行为不变。开启后英和图片/视频、英和海外、Grok、OpenAI 兼容 LLM 通过网关；用户鉴权和持久化 Worker 都传递真实用户与 Agent 批次。OpenAI SDK 在网关模式下关闭隐式重试。

```dotenv
MODEL_GATEWAY_URL=http://model-public:8011
MODEL_GATEWAY_API_KEY=<MV 专属内部 Key>
```

MV 仍负责项目、大纲、人物和分镜业务。现有视频提示词编译和模型请求格式先留在 MV，通过兼容接口迁移；其他系统可以直接调用统一工单接口，传递文档规定的模型 payload。网关负责供应商连接、持久化生成、用量和归档。

新 MV 图像/视频工单在提交前持久化 `_modelGateway` 路由标识，并保存网关任务 ID。Worker 对没有此标识、且渠道仍受支持的旧供应商工单保持直连恢复，避免仅凭 ID 外形猜测路由。回滚关闭网关时，尚未结束的网关工单会明确拒绝直连恢复；须保留网关配置完成这些任务，不能把同一任务重发供应商。切换窗口内须保留仍受支持渠道的旧凭据，待旧任务全部结束后再移除；不适用于已退役渠道。管理端手工同步历史任务也须先按来源区分，不能跨渠道猜测 ID。

## 退役渠道的前向迁移

PPIO 与 BFL（Black Forest Labs，历史 FLUX 3）的代码、配置入口和 seed 已移除，不得通过网关、直连或旧工单恢复重新启用。删除 seed 不会清理已有数据库，上线前须完成以下前向迁移并核验：

- MV 升级至 `b3f7a1c5e902`：保留历史 Alembic 文件以防断链，仅软删除存量 provider/model/pricing 配置行；保留历史 `ppio_asset_avatar_url` 列及其数据，以兼容滚动发布，**本次不删列**。业务不再读取/写入该退役字段，不等于数据库已经移除它。
- model-service 在独立数据库升级至 `0005`：软删除旧渠道账户及关联模型、路由、费率配置行，停止目录展示、余额采集和新任务受理；不能只更新镜像或重跑 seed。
- 历史财务工单、费用、用量与媒体全部保留，不物理删除，不因退役重算为零或重发生成。迁移仅处理退役配置，不扩展到 HappyHorse、Vidu、Kling 等保留渠道/模型。
- 上述为发布要求，不代表目标数据库已经执行完成；发布验收须分别核对两侧 Alembic 版本、退役行状态以及 MV 历史列仍存在。保留列仅用于 schema 滚动兼容，回滚不得恢复已退役支持。

## Loopback 隧道验收与切流顺序

先在服务器核对五个服务的 health、两侧 Alembic 版本、运行角色无 DDL 权限及退役配置。再从本机连接既有服务器的 SSH 入口，不新增防火墙端口：

```bash
ssh -N \
  -L 18011:127.0.0.1:8011 -L 18012:127.0.0.1:8012 \
  -L 15180:127.0.0.1:5180 -L 15181:127.0.0.1:5181 <运维用户>@<MV服务器>
# 另一个终端，仅做不产生生成费用的连通性检查：
curl --fail http://127.0.0.1:18011/health
curl --fail http://127.0.0.1:18012/health
```

浏览器分别访问 `http://127.0.0.1:15180`（管理）和 `http://127.0.0.1:15181`（用户门户），检查登录、Key 权限、模型目录、额度/费率及账本展示。隧道验证不能代替 MV 容器中的网络验证：切流前从 MV 后端和各 Worker 所在网络确认 `http://model-public:8011/health` 可达，不能将 `127.0.0.1:8011` 配给 MV 容器。

创建 MV 专属内部 Key 并安全写入 MV 配置，再用 MV 自身版本化发布流程更新后端和 Worker 的 `MODEL_GATEWAY_URL`/`MODEL_GATEWAY_API_KEY`，本服务脚本不操作 MV 容器。保留旧工单恢复需要的受支持渠道凭据；先小范围检查合同、用户隔离、费用归因与工单恢复，再扩大流量，不能仅以健康检查通过宣称全量迁移成功。

任何 Code Agent/自动化/E2E 的真实模型验收都必须同时携带 `X-Agent-Name: code-agent`、本次唯一 `X-Agent-Run-Id` 与 `X-Test-Run-Id`，使用受控低成本任务并核对服务工单、MV 工单和费用记录的 Agent 来源、名称和批次。缺少标识不得真实生成；本部署脚本自身不发起模型调用。

## 验收范围与边界

- 独立服务原始能力验证与之前的供应商模型测试是两件事。之前 5/5 成片不等于新网关已对每个模型完成真实验收。
- SQLite 用于本机单 Worker；生产多进程并发以 PostgreSQL advisory transaction lock + row locks 为准。
- Veo 本服务允许最多 3 图，历史实际测试最多 2 图。Kling 默认停用，未完成主体 element 接入。
- HappyHorse、Vidu 按此前决定不启用，不能把它们计为迁移通过。Flux-api 仅沿用历史暂停标记；现有文档未提供独立渠道标识，不能仅凭名称认定它是 BFL 的别名，也不能据此启用。PPIO 与 BFL（历史 FLUX 3）已从 MV 与本服务中移除支持，不是暂停或待迁移渠道。
- MV 仍有专用工作流和后台工具，必须逐个合同验证后才能宣称所有入口迁移完成；完整清单与当前结论以验收报告为准。
- 原始用量账本已实现；供应商余额、人民币费率管理和自动财务对账并非原始用量的替代，不将未定价任务展示为免费。
- 出口网络影响渠道查询和成片归档。恢复必须复用 provider_task_id；无 ID 的超时提交须先核对渠道，不能“失败即重试”。

## 本机代理的 Fake-IP DNS

本机代理可能将公网域名解析为 198.18/15 等保留地址。默认下载器会拒绝，不能关闭内网检查。可仅在本机设置 `MEDIA_DNS_OVER_HTTPS=true`、`MEDIA_DNS_PROXY=http://127.0.0.1:7897`：通过固定 HTTPS DNS 服务解析，校验所有地址均为公网，再将真实 TCP 连接固定到已校验的地址；TLS SNI 和证书校验仍使用原域名。所有重定向重复校验。生产通常不需要该设置，也不能照搬本机代理地址。

连接层适配锁定 httpx 0.28/httpcore 1.x；升级依赖须重新执行公网 IP 固定连接与私网拒绝测试。


## 用户门户与账本升级

先执行 Alembic `upgrade head`（0002），再独立部署两个 API 和 Worker，最后更新两个 Vue 包。新增 `user-web` 镜像/目录可单独发布，不重启生成 API。本机端口 5181，容器 8080。用户前端构建不需要任何供应商密钥或管理凭据。

现有系统 Key 升级保持原行为，控制台明确显示额度控制未启用；新建 Key 默认启用额度控制。管理员为旧 Key 设置额度或临时调整后开启控制。面向用户开放之前，需在管理后台按模型和生成方式填写真实适用费率并发布，否则其生成请求会因费率未配置而被拒绝。不得把测试库虚构费率迁入实际库。详见 [PORTAL-AND-CREDITS.md](PORTAL-AND-CREDITS.md)。

## 渠道余额升级

执行 Alembic 0003 后再更新管理 API/Web 与公开 Worker。新增 `channel_accounts` 的读写权限须授予管理与执行数据库角色；供应商业务凭据仅进入 `.env.public` 或本机 Worker 环境，不进入管理 API。管理页面读取数据库快照，Worker 每 5 分钟自动采集 `yinghe`（英和国内）、`yseeai`（英和海外）与 `toapis`。人工快照、积分换算和双站模型授权工具见 [CHANNEL-BALANCES.md](CHANNEL-BALANCES.md)。

### 0010 英和视频模型路由限额

按用户提供限额设置当前保留的英和国内/海外视频路由：Seedance 2.0 / Mini / Fast 为 50，Wan 3.0 / Prime 为 100，Gemini Omni Flash 为 8。范围取下限；不新增已移除模型，不修改 Seedance 2.5 或其他供应商，不修改启停及验证状态。变更前后值进入审计。此迁移只执行一次，后续后台人工修改不会在重启时被覆盖。「模型供应商」的渠道并发可设置 1–200；模型、调用方、渠道全局限额仍独立生效。
