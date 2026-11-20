# 2026-11-19 性能、安全与稳定性修复记录

本次工作以[原审查报告](deep-code-review-2026-11-18.html)中 35 项 P1、56 项 P2 为范围。以下记录对应当前本地工作树。生成供应商调用使用测试替身，媒体处理使用合成素材。数据库、队列和镜像验收使用独占临时资源。

| 范围 | 项数 | 修复与验证证据 |
| --- | ---: | --- |
| 主应用 API | 27 | [逐项证据，以及真实 PostgreSQL 登录与慢 SSE 订阅并发测试](remediation-2026-11-19-api.md) |
| 工单、用量及结算 | 18 | [逐项证据，以及 PostgreSQL 和 Redis 并发验收](remediation-2026-11-19-jobs.md) |
| 工作区与管理前端 | 20 | [逐项证据，以及浏览器场景和运行条件](remediation-2026-11-19-web.md) |
| 发布、备份及依赖 | 14 | 下表 |
| 独立模型网关 | 12 | 下表 |

## 发布、备份及依赖

| 编号 | 生效行为 | 验证 |
| --- | --- | --- |
| OPS-01 | 配置生成和服务启动按明确的部署环境核对应用域名、模型平台的 HTTPS 地址和两种媒体前缀，部署身份由编排层传入。 | 两套环境的正向配置、跨环境地址拒绝和已有配置再运行；见[环境用例](../../backend/tests/test_deployment_environments.py)。 |
| OPS-02 | 迁移引擎直接使用数据库 URL，用户名和口令中的保留字符逐字段转义。 | [独占 PostgreSQL 验收](../../scripts/local_api_concurrency_proof.py)使用带保留字符的角色与口令完成到 head 的迁移，检查成功日志不含原文或 URL 编码口令。 |
| OPS-03 | 旧批量生图入口立即退出，指向工作区人物资产入口。 | [原命令](../../scripts/generate-digital-humans.mjs)的本地冷启动返回非零，没有读取凭据或发出请求。 |
| OPS-04 | 恢复先核对目标文件的 SHA-256，使用 pg_restore 的单一事务，遇错中止。 | 在临时库制造 DDL 依赖冲突后仍读到原值 42，解除依赖后成功恢复为备份值 1。[恢复验收](../../backend/tests/test_backup_recovery.py) |
| OPS-05 | 共用媒体桶按当前环境自动选取备份前缀，使用 SSE-C、私有 ACL、对象摘要及长度核验；拒绝指向另一环境的前缀。 | mock TOS 检查上传地址、加密参数，拒绝错误前缀与错误摘要。[备份回归](../../backend/tests/test_review_remediation.py) |
| OPS-06 | 已部署的前端在绿色后端通过检查前继续提供服务，新前端与正式后端均就绪后才发布版本信息。 | 首次发布、滚动切流、重建失败、切回失败、TLS reload 及首页/API 检查。[部署模拟](../../backend/tests/test_deploy_switch.py) |
| OPS-07 | 发布与回滚共用进程锁，成功后原子写入当前及前一版本，兼容旧版状态文件。 | 失败保留回滚记录，测试覆盖并发竞争、同版本重发及旧记录兼容。[发布入口](../../scripts/deploy.sh) |
| OPS-08 | 每次验备创建 UUID 临时数据库，仅清理本次成功创建的库。 | 并行验证使用不同库名，建库失败和恢复异常均检查清理范围。[备份验收](../../backend/tests/test_backup_recovery.py) |
| OPS-09 | CI 为同一提交实际构建的六个应用镜像分别执行 Trivy。扫描错误或 CRITICAL 命中均使相应任务失败。 | 同一离线漏洞库和门禁参数下，旧前端镜像退出码为 1，更新后的镜像为 0。[CI 矩阵](../../.github/workflows/ci.yml) |
| OPS-10 | 准备新服务器时不再授予固定账号 Agent 记账权限，已有显式授权继续由运维管理。 | 两个环境均验证初始配置不产生默认授权。[配置测试](../../backend/tests/test_deployment_environments.py) |
| OPS-11 | 图片处理依赖锁定 Pillow 13.0.0。 | Python 锁版本核对、上传和缩略图回归、镜像内安装。[PyPI 版本](https://pypi.org/pypi/Pillow/13.0.0/json) |
| OPS-12 | certifi 锁定 2026.10.19。 | 主后端及网关均按锁安装；核对该发行版安全记录。[PyPI 版本](https://pypi.org/pypi/certifi/2026.10.19/json) |
| OPS-13 | OpenTelemetry API 锁定 1.45.2。 | 按锁安装、后端回归及发行版公告核对。[PyPI 版本](https://pypi.org/pypi/opentelemetry-api/1.45.2/json) |
| OPS-14 | 三个前端的 Vite 锁至 8.3.8。 | 三份完整 npm 锁均执行官方注册表 audit，另运行生产构建。 |

## 独立模型网关

| 编号 | 生效行为 | 验证 |
| --- | --- | --- |
| GW-01 | 同步 Chat 在同一事务中检查容量、预留积分并取得租约。满额回滚，旧队列里结果不明的请求转人工核对。原生异步端点拒绝 Chat。 | mock 下同一幂等键首轮满额返回 429、工单数为零，恢复容量后成功一次；原有同步、流式测试核对用量。[服务回归](../../model-service/tests/test_service.py) |
| GW-02 | 从每个资源组合的队首选取候选，失效 Key 与已删除目标分别处理。尚未提交且可证明无费用的工单释放预留，有平台证据的进入人工核对。 | 100 个历史失效工单之后的有效任务仍能在同次领取中获租，核对历史费用未被重算。另验证撤销 Key 后其他租户可领取。[领取代码](../../model-service/public-api/gateway/queue.py) |
| GW-03 | 同步图片保留已成功的供应商结果。管理后台可以只重试归档，不要求原平台返回异步任务号。 | 模拟首次归档失败，从真实管理 API 恢复，结果入库，供应商提交计数始终为 1。[图片归档验收](../../model-service/tests/test_overseas.py) |
| GW-04 | 调度、同一所有者的钱包分别加锁；进度和心跳只锁对应工单；跨账户管理操作保留独占屏障。月度重置分批处理。 | 真实 PostgreSQL 中持有一个钱包锁时，另一个钱包和执行心跳仍可完成；12 次并发回调只产生两笔扣款。[并发验收](../../model-service/tests/postgres-concurrency.py) |
| GW-05 | 只计登录失败，账号与来源分别限流。user-web 覆写来源，仅受信代理对端可以提供该地址，密码计算在数据库事务外执行。 | 同代理下两个账号登录成功不消耗窗口，单账号达到上限不阻断另一个账号，未受信连接不能指定来源。真实门户另验证 A 收到 429 后 B 仍可登录并查看自己的账户。[登录验收](../../model-service/tests/test_portal_password.py) |
| GW-06 | ASGI 在读取请求数据时累计大小，保留原始分块，带长度时可提前拒绝。 | 声明长度和分块累计超过阈值均返回 413，未受理工单。[服务回归](../../model-service/tests/test_service.py) |
| GW-07 | ffprobe 和 FFmpeg 子进程统一限时，取消或超时后终止并回收，日志内存有上限；仅安装 FFmpeg 时用同一次封面提取取得元数据。 | 对真实本地延迟子进程分别取消和超时，均确认 PID 已回收。[媒体验收](../../model-service/tests/test_media.py) |
| GW-08 | Worker 在主循环和数据库往返成功后更新时间戳，持续满载却无完成时停止刷新，退出时撤销就绪。容器检查时间戳新鲜度。 | [Worker 测试](../../model-service/tests/test_worker_shutdown.py)验证空队列仍就绪，数据库中断和进程退出均撤销可用信号；[健康探针](../../model-service/docker-compose.yml)检查 45 秒期限。 |
| GW-09 | 两个门户锁定 source-map-js 1.2.4。 | 两份独立锁的 npm audit 均为零，分别构建管理页和用户页。 |
| GW-10 | 两个独立 API 的基础镜像使用 digest，构建时安装各自适用的 Linux/Python 3.12 完整运行依赖锁。 | 两个 API 镜像分别按锁构建，CI 按提交运行镜像扫描。[公开 API 锁](../../model-service/public-api/requirements.lock) · [管理 API 锁](../../model-service/admin-api/requirements.lock) |
| GW-11 | 独立资产登记有提交租约及幂等保护；新旧中断记录进入人工核对，资产登记不计入生成队列和执行容量。 | 同时存在旧的无租约资产与有效登记时，新生成工单仍可受理并领取；只回收过期的旧记录。[服务回归](../../model-service/tests/test_service.py) |
| GW-12 | 普通 Key 无法自行声明 Agent 费用来源。专用 Key 强制填写三项归因头，混合用途 Key 须按客户端 ID 显式授权。 | 同一组模拟请求分别验证拒绝、显式授权和持久化的费用来源。[归因校验](../../model-service/public-api/gateway/security.py) |

## 本地验收结果

- 最终完整 `make preflight` 以退出码 0 完成，包含 lint、Alembic 单一 head、Python 与前端全量测试、生产构建和临时 PostgreSQL/Redis 验收。54 个前端 Vitest 文件共 296 项通过。
- 主后端在 Python 3.13 上运行全量 pytest，805 项通过，应用覆盖率 74%。常规套件隔离跳过的真实数据库恢复用例，另在独占 PostgreSQL 中通过。SQLite 不能执行的历史外键迁移保留项目原有 xfail，完整迁移链另在 PostgreSQL 上通过。
- 独立模型服务执行 `make -C model-service check`，115 个 Python 用例通过，公开与管理门户分别通过 TypeScript 检查和 Vite 生产构建。
- `python3 scripts/local_runtime.py gateway-postgres` 验证模型池并发上限、钱包隔离及共享账号额度。12 个领取进程拿到 2 份不同租约，12 次费用回调形成 2 条扣费记录。单账号 8 次同时受理只接受 2 次，12 次并发建 Key 后总数为 10。
- 独立网关门户另用两个合成账号从真实浏览器登录，同一来源下 A 被限流时 B 正常查看自己的积分。会话已撤销，工单为零。
- 主项目 Playwright 共收集 35 项，30 个不同用例在本地通过。5 个需要部署数据或外部集成的用例及其条件见[浏览器明细](remediation-2026-11-19-web.md)。
- 三个 npm 锁文件的官方注册表审计结果均为 0。三个 Python 运行依赖锁去重后共 55 组包与版本，查询 PyPI 官方发行记录，均未命中其已记录公告。
- 首轮镜像扫描检出旧 Nginx 基础层在 Brotli 和 OpenSSL 上的 3 个 CRITICAL 包记录，涉及 2 个不同 CVE。三个前端改用同一多架构 Nginx 1.30 Alpine digest，重新构建后均为 0。主界面镜像的 Nginx 配置检查、首页及健康路由也已实际通过。
- 六个交付镜像的 Trivy 复扫均为 **0 项 CRITICAL**。范围包括主应用前后端、独立网关的公开和管理 API，以及两个门户。三个 API 均扫描了系统包和 Python 包。漏洞库更新时间为 2026-11-20 01:04 UTC。该结果仅对应这次构建与扫描的严重等级。
- 主后端镜像在 UID/GID 10001 下通过 Python 依赖检查、原生扩展加载、Argon2、JWT、Pillow，以及上海和洛杉矶冬夏时区检查。FFmpeg 8.1.3 实际编码 H.264/AAC 并烧录中文 ASS 字幕，解码后的画面含字幕，ffprobe 返回了预期的音视频轨。
- 使用最终前后端镜像在独占 Docker 内网启动整站。镜像自带入口将空 PostgreSQL 升级到 `eb617531ca10`，Nginx 成功提供首页，转发的 `/api/health` 返回 `{"ok":true}`。真实 Compose DNS 能解析当前 frontend 容器，ASGI 只接受可信来源的转发信息。本次容器、网络和专用镜像标签已清理。

旧主后端镜像的 FFmpeg 依赖带入 Debian 13 的 libxml2。首轮镜像扫描命中 CVE-2026-6653，Debian 安全跟踪表将该发行版列为受影响。主后端改用固定 digest 的官方 Python 3.12 Alpine 镜像，继续使用发行版维护的 FFmpeg、ffprobe 与 Noto CJK。实测 libxml2 为 2.13.9-r2。Trivy 0.66 的内置生命周期表尚未收录 Alpine 3.24，扫描日志确认该次已按 Alpine 3.24 漏洞库检查 145 个系统包，并执行了 Python 包检查。独立网关的两个 Python 镜像保留原 Debian 基底。[Debian 安全跟踪记录](https://security-tracker.debian.org/tracker/CVE-2026-6653)

## 验收边界

生产及测试服务器均未发布。镜像实测平台为 Linux amd64。固定基础镜像的 manifest 同时包含 arm64，本机未运行 arm64 成片验收。测试没有向模型平台、TOS 或实际用户发起业务请求。真实供应商计价时序、实际入口代理链以及线上负载仍以对应环境的验收为准。
