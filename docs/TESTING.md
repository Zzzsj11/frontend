# 测试指南

测试分层：后端 pytest 验证权限、隔离、软删除、模型、资产和业务旅程；Vitest 验证前端 Store/约束/错误处理；Playwright 验证 API 契约与真实浏览器旅程。

浏览器 Agent 验收可在入口链接添加 `?agent_test_run_id=<本次唯一批次>`。前端将批次保存在当前页签的 sessionStorage，并为 API 请求携带 `X-Agent-Name: code-agent`、`X-Agent-Run-Id`、`X-Test-Run-Id`；导航和刷新后仍保留。结束后访问 `?agent_test_run_id=off` 清除该页签标记。批次只允许 1–160 位字母、数字、点、下划线和连字符；它不改变登录身份或权限。测试页签的写请求遇到 502/503 不自动重放，须核对工单后再处理，避免一次性生成验收产生重复请求。真实生成前必须确认部署版本已支持此入口，并在工单及费用记录中核对归因。

```bash
make test        # 后端 pytest + 前端 vitest
make test-e2e    # 本地 Playwright（mock 链路）
make smoke       # 重大调整后的无费用主流程冒烟
make preflight-lite # 本机检查，无 Docker
make preflight   # 本机检查 + 一次性 PostgreSQL/Redis 验收
make docker-build # 显式镜像构建验收，结束删除本次标签
```

前端测试按「用户侧 / 管理后台」分组存放，可独立运行以缩短反馈时间：

```
tests/
  user/    # 用户侧组件/Store/工具单测
  admin/   # 管理后台面板单测
e2e/
  user/    # 用户侧旅程、远程冒烟、真实生成全链路
  admin/   # 管理后台 API 契约 + 控制台 UI
```

```bash
npm run test:unit:user    # 仅用户侧单测
npm run test:unit:admin   # 仅管理后台单测
npm run test:e2e:user     # 仅用户侧 e2e（带开关的 spec 仍需对应环境变量）
npm run test:admin        # 管理后台 e2e（API 契约 + 控制台 UI）
```

新增测试按归属放入对应子目录；`npm test` / `npm run test:e2e` 仍跑全量，`make preflight-lite` 不依赖容器；`make preflight` 追加临时数据依赖的集成验收。

## 最小冒烟（重大调整后必跑）

`make smoke` 是不调用真实模型、可反复执行的主流程卡口，组合以下三层：

- 后端完整用户旅程：建项目 → 上传 → ASS 大纲/逐镜提示词 → 场景图/视频工单 → 用量 → 素材导出 → 对话；供应商与存储使用测试替身。
- 后端关键边界：用户私有数据隔离、无人物通用分镜、普通用户管理权限与模型选项。
- 浏览器旅程：登录 → ASS 上传 → 分镜可编辑 → 通用/随机/创意入口，并验证 Nano Banana 2.1 / Seedream Pro均可选择。

它不替代 `make preflight-lite` 或发布前 `make preflight`，也不验证 PostgreSQL、Redis、Worker、TOS 和真实供应商。涉及供应商、模型请求格式、异步任务或部署的大调整，在 `make smoke` 通过后再运行低成本真实冒烟：

```bash
PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 make smoke-real
```

真实冒烟会明确检查目标地址，未设置 `PLAYWRIGHT_BASE_URL` 或 `REMOTE_API_BASE_URL` 时拒绝启动。它用一条 5 秒通用空镜验证真实文本提示词、当前默认图片模型、视频、播放器与素材导出；ASS 主流程由无费用集成冒烟覆盖，完整真实 E2E 仍可单独执行 ASS 阶段。所有请求自动携带本次唯一的 `X-Test-Run-Id`、`X-Agent-Name: code-agent`、`X-Agent-Run-Id`，会产生真实费用。

## 耗时与针对性验证

测试数量与耗时以本次输出为准。`make preflight-lite` 直接使用本机 Python/Node：lint、Alembic 单 head 检查、临时 SQLite/fakeredis 单测及前端构建。它不创建 Docker 资源，也不对既有数据库执行迁移。

`make preflight` 在上述结果之外运行 `make test-middleware`：创建本次独有的临时 PostgreSQL/Redis，执行从空库到 head 的全部迁移，再验证真实数据库的并发领取、失租恢复、软删除排除，以及 Redis 原子执行名额。供应商请求被网络限制阻止，模型调用为零。结束、失败或中断都删除本次容器、网络和测试数据；不接入本地已有业务库。

`make migration-check` 单独验证临时 PostgreSQL 的完整迁移。Dockerfile、系统依赖或容器行为变化时追加 `make docker-build`，使用唯一临时镜像标签并在结束后删除；日常全量检查不再重复构建应用镜像。实际服务器发布仍需构建和验证不可变版本镜像。

e2e 不在 preflight 内，按需触发：`test:e2e:user`（本地 mock 链路）约 6s；`test:admin` 约 10s；`test:remote:*` 分钟级；`test:e2e:real` 上限 90 分钟且产生真实费用。

日常小改不必每次全量，按改动范围选最小验证集：

| 改动范围                | 最小验证命令                                                       | 耗时       |
| ----------------------- | ------------------------------------------------------------------ | ---------- |
| 前端单组件/composable   | `npx vitest run tests/user/xxx.test.ts`                            | ~3s        |
| 前端用户侧 src          | `npm run test:unit:user`                                           | ~9s        |
| 前端管理后台 src        | `npm run test:unit:admin`                                          | ~6s        |
| 后端单模块              | `cd backend && .venv/bin/pytest -q tests/test_xxx.py`              | 2~10s      |
| 权限/隔离/API 契约      | 上述 + `tests/test_multi_user.py` `tests/test_api.py`              | ~10s       |
| models.py 或 migrations | `make migration-check` + 相关 pytest 文件                          | ~15s       |
| 日常提交前              | `make preflight-lite`（全程无 Docker）                             | ~3 分钟    |
| 发布前                  | `make preflight` 全量 + 相关 e2e；容器变更另跑 `make docker-build` | ~3min      |
| 用户旅程关键链路        | 追加 `npm run test:e2e:user`                                       | ~6s        |
| 重大调整后的主流程      | `make smoke`（无真实模型费用）                                     | 分钟内     |
| 管理后台 UI/契约        | 追加 `npm run test:admin`                                          | ~10s       |
| 供应商/提示词/生成链路  | 按需 `npm run test:e2e:real`（有成本）                             | 上限 90min |

约束：新增后端功能必须补集成测试（对应 pytest 文件必跑）；涉及用户旅程、API、部署或权限的改动必须加跑对应 e2e；`make preflight` 是发布前唯一全量卡口，不得用 preflight-lite 替代发布验证。

不适合自动化的点（需人工验收）：

| 功能                   | 原因                          |
| ---------------------- | ----------------------------- |
| 图片/视频生成质量      | 需要视觉判断                  |
| 拖拽排序动画、卡片动效 | CSS 动效，Playwright 难以验证 |
| 数字人生成进度         | 依赖真实 AI 服务，耗时长      |

新增功能必须优先补后端集成测试；关键页面再补 Playwright，避免只依靠脆弱的端到端测试。失败产物在 `test-results/`，远程截图在 `test-artifacts/remote/runs/`。

## e2e 凭据约定（强制）

所有远程 spec 统一从 `e2e/env.ts` 取凭据：

- 目标非 localhost 时必须显式提供 `REMOTE_E2E_PASSWORD`，否则启动即报错（fail-fast，防止静默回退到本地开发密码白跑一轮）。
- 推荐方式：复制 `e2e/.env.example` 为 `e2e/.env` 填一次（已 gitignore，playwright.config.ts 自动加载），之后所有 `test:remote*` 命令免环境变量直跑。
- 禁止把真实密码写进任何入库文件。
- 本地后端测试环境首次以 admin/123456 完成强制改密，随后固定使用测试专用密码；仅存在于一次性 SQLite，不用于服务器环境。

## API 耗时采集与性能观测

完整文档见 [`PERFORMANCE-MONITORING.md`](PERFORMANCE-MONITORING.md)：三层观测体系
（后端全量请求日志 / 前端会话埋点 / 管理后台「性能」页），可回答「卡顿是接口慢
还是渲染慢」。

- 默认仅对带 `X-Test-Run-Id` 请求头的流量入库（测试流量）；置 `API_REQUEST_LOG_ALL=true`
  后全量记录正式流量（线上已开启）。变量写在 `backend/.env`（容器 `env_file`），
  写 `.env.production` 不会注入容器。
- **轮询/SSE 长连接请求统一打 `X-Polling: 1` 头，后端中间件直接跳过**——新增轮询点
  时必须打标（前端打标清单见性能文档 3.3），否则会刷日志。
- pytest 全量测试由 conftest 自动注入批次头；e2e 的 API 级 spec 注入 `extraHTTPHeaders`，UI 级 spec 通过 `page.route('**/api/**')` 注入。
- 管理后台查看：批次列表（次数/均峰值/错误数）→ 单批请求表格（≥1s 高亮）→ 单条详情
  （脱敏后的输入参数与输出原文）；「性能」页含后端慢请求 TOP、24h 接口耗时聚合
  （count/avg/P95/max）、本浏览器会话的 API 耗时拆分（网络 vs 解析）、主线程长任务
  与整页加载计时。
- 请求/响应体仅 JSON 且 ≤8KB 入库；SSE/流式/二进制只记元信息。密码等敏感字段自动脱敏为 `***`。
- 回归测试：后端 `backend/tests/test_request_logging.py`（9 个：轮询跳过/minMs 过滤/
  duration 排序/聚合/脱敏/权限），前端 `tests/user/perf.test.ts`（4 个：聚合计算/阈值过滤/
  标记识别/埋点集成）。

## 远程验收（对已部署环境）

远程验收显式指定 `REMOTE_API_BASE_URL=https://mv-test.epaipix.com`，确认该环境连接 `https://mg-test.epaipix.com`。非紧急变更先完成测试环境验收；正式发布获明确授权后，才指定 `REMOTE_API_BASE_URL=https://mv.epaipix.com` 做正式冒烟，正式只连接 `https://mg.epaipix.com`。禁止隐式使用正式目标；完整规则见 [部署手册](DEPLOYMENT.md#环境对应与发布顺序强制)。域名、容器及依赖健康由 `scripts/online-health-check.sh` 验证。带远程开关（`REMOTE_*`/`ADMIN_*`）运行时 playwright.config.ts 自动以 `e2e/env.ts` 的 `targetBaseURL()` 为目标且不在本地起服务，无需再设 `PLAYWRIGHT_BASE_URL`（设置了则可覆盖目标）。

```bash
npm run test:remote:api        # API 契约/鉴权/隔离/软删除（不消耗生成 Token）
npm run test:remote:frontend   # Chromium 操作线上前端冒烟（ASS 上传会触发数条真实提示词生成，有小额费用）
npm run test:admin:api         # 管理后台 API 契约
npm run test:admin:frontend    # 管理后台 UI
REMOTE_REAL_GENERATION=1 npm run test:remote:api   # 含真实生成分支（产生费用）
```

成功标准：退出码 0；公开健康检查严格返回 `{"ok":true}`；普通用户不能访问管理员 API 或他人任务；临时密码用户必须改密后才能进入业务接口；上传返回 TOS HTTPS URL；删除后资源不可再读；页面无全局错误弹窗。测试创建的用户/项目结束时走产品 API 软删除，不得物理删除业务记录。

## 真实生成全链路（有真实成本）

`e2e/user/full-real-generation.spec.ts` 覆盖：登录 → 建项目 → ASS 上传/情感匹配/选角/逐条提示词 → 通用分镜 → 场景图 → 视频 → 播放器 → 素材 ZIP 导出，全程截图并断言无错误弹窗。默认跳过，`REAL_GENERATION_E2E=1` 才运行。

```bash
npx playwright install chromium   # 首次
make dev                        # 临时数据依赖 + 本机应用，Ctrl-C 清理
export REAL_E2E_PROJECT_SUFFIX="$(date +%Y%m%d-%H%M%S)"
npm run test:e2e:real             # 完整模式，上限 90 分钟
npm run test:e2e:smoke-real       # 最小真实模式：通用文本 + 1 图 + 1 个 5 秒视频 + 导出
npm run test:e2e:real:general     # 仅通用分镜（ASS 已成功时）
npm run test:e2e:real:export      # 复用已有通用视频，仅验播放器与导出（不调模型）
```

- 输入夹具 `test-artifacts/full-journey/inputs/10012204-full-e2e.ass`；首次基准截图在 `test-artifacts/full-journey/screenshots/`（入库保留，复跑不得覆盖）；后续产物进 `runs/<run-id>/`。分阶段恢复必须复用同一 run-id。
- 环境必须具备：PostgreSQL/Redis、文本/图片/视频供应商、TOS 凭据、32 个系统人物与歌曲情感配置。视频基准选 5 秒控制成本。
- 成功后数据库核验：2 项目 2 任务；ASS/通用各 2 条 `storyboard_lines` 为 succeeded；4 个 scene_assets + 4 个 shot_assets；generation_jobs 全成功；有成本调用均有 `token_usage_records`；2 条 material_exports 为 ready；所有媒体 URL 为 TOS HTTPS 且返回 200；`api_error_logs` 无非预期 4xx/5xx（冷启动 `/api/auth/refresh` 401 属已知预期）。
- 失败处理：先看 Playwright 截图/trace，再查后端日志、generation_jobs、api_error_logs 区分交互失败与供应商失败；已有成果优先用恢复阶段重跑，避免重复收费；不得把失败任务改成功。
- 用例迭代：优先角色/标签定位；新增关键节点同步加截图并更新数量断言；不降低超时掩盖供应商延迟；不删错误弹窗断言。

## 管理后台测试

```bash
cd backend && .venv/bin/pytest -q tests/test_admin_console.py   # 后端集成（独立 SQLite）
ADMIN_API_E2E=1 npx playwright test e2e/admin/admin-api.spec.ts       # 远程 API 契约
ADMIN_CONSOLE_E2E=1 npx playwright test e2e/admin/admin-console.spec.ts  # 远程 UI
```

测试不得修改或删除系统人物；模型启停类测试完成后恢复原状态。

## 上线验收清单

真实视频规格验收：每个供应商的低成本 Agent 测试必须同时核对 `requestedResolution/providerResolution/actualWidth/actualHeight/fps/codec/actualDuration/fileSize`，不得只相信请求参数或供应商状态字段。规格变化先报警并人工确认，不静默改写产品档位。RunningHub 测试不得占用或检查英和余额。

域名与 HTTPS：域名解析到公网 IP；HTTPS 可打开且 HTTP 自动跳转；证书签发与自动续期正常；Nginx 为域名模式。
容器与数据：四服务 healthy；`/api/health` 200；迁移自动执行；种子数据就绪；数据库/Redis 不公网开放（调试走 SSH 隧道，必须开放则 IP 白名单）。
账号与业务：管理员登录、双 Token、改密、多用户隔离可用；ASS 解析/歌曲编号匹配/情感命中/通用分镜/场景图/视频/单镜重生成/批量生成/素材导出全通。
媒体与日志：图片、视频、封面、导出包全部 TOS；API 报错入库；Token 记账；失败原因可追踪；关键操作有审计。
最终确认：线上与本地配置分离；生产密钥未入库；备份策略与回滚步骤就绪；验收结果留档。

## 专项改动验证要点

- 导出改动：进度单调递增、完成后归档可读、不同 taskId 状态不覆盖、用户间不可读他人导出、SSE 断开后 GET 状态可恢复。
- 大纲改动：明确人物动作的歌词不得规划为空镜、连续空镜受限、6 条及以上歌词至少 3 个场景、视觉母题不超过大纲声明次数。
- 分镜Worker改动：断开 `worker-storyboard` 后API仍能202入队且工单保持 `queued`；恢复Worker后可完成。执行中强制终止Worker后，工单须由PostgreSQL心跳判定为失租、attempt递增并重放；超过3次必须落失败终态，同时更新任务的 `outlineProgress`，不得无限重试或停留在 `outlining`。
- 系统人物改动：默认分类男/女/儿童且只读、对所有用户可见、儿童提示词保持年龄造型一致、原图与缩略图均为 TOS URL；新增系统图片用 `scripts/sync-system-human-assets.py --asset CODE=/path/to/image` 上传，不得复制到项目目录。
- 本机临时数据依赖和显式镜像构建验收经 `docker-compose.local-build.yml` 使用国内镜像代理；服务器部署不加载该文件。代理不可用时用 `LOCAL_NODE_BASE_IMAGE`、`LOCAL_NGINX_BASE_IMAGE` 临时覆盖，不得改服务器部署配置。

## Agent 来源授权与完整用量归因

生产环境仅超级管理员或 `AGENT_TEST_USERNAMES` 显式授权的账号可以携带 Agent 测试来源头；未授权请求返回 403，不会把它改记为普通业务。三个必需头仍为 `X-Agent-Name`、`X-Agent-Run-Id`、`X-Test-Run-Id`。账号授权不代替测试头，Agent 必须主动携带本次唯一批次。

### 测试服务器的普通账号验收

测试服务器 `mv-test.epaipix.com` 使用生产部署配置，后端及 Worker 的 `APP_ENV=production`，因此同样执行上述账号授权检查。服务器所属环境由 `DEPLOYMENT_TIER=test` 和域名确认。保留此运行模式可以同时验证部署安全约束。

远程验收使用 MV 工作台账号。模型平台 `mg-test.epaipix.com` 的账号独立管理。本机凭据保存在 Git 忽略的 `e2e/.env`，权限设为 `600`，不得写入报告或提交。

普通权限和跨用户隔离回归按以下顺序准备：

1. 确定本次测试批次及普通验收账号的完整用户名。
2. 将这些用户名精确加入测试服务器实际生效的 `AGENT_TEST_USERNAMES`，保留原有授权名单。运行时 `backend/.runtime_secrets.env` 中的同名配置优先于 `backend/.env`；先确认配置来源，并按部署流程使配置生效。该配置按用户名匹配，不支持随机用户名通配符。
3. 由管理员创建普通验收账号，或使用已授权的专用普通账号。账号保持普通业务权限，Agent 授权只允许携带测试来源。
4. 使用完整三个归因头进行登录、首次改密、权限、数据隔离和软删除回归。授权检查也覆盖首次改密接口，须在该请求前准备好授权。
5. 验收后软删除本次创建的账号和业务数据，撤销本次临时加入的授权，并记录部署版本、批次及结果。复用专用账号时，仅清理本次数据。

当前 `e2e/user/remote-api.spec.ts` 按批次生成随机普通用户名，并直接进行首次改密。可通过 `REMOTE_E2E_USER_USERNAME` 显式指定本次将创建的普通用户名，并在运行前精确授权此名称。该名称必须从未被使用（已软删除账号仍占用用户名唯一约束），脚本仍负责创建和软删除账号；不传时沿用随机命名。脚本不会修改服务器授权名单，运行前后由部署操作添加和撤销本次授权。不要通过删除归因头执行这段 Agent 验收。

### 三个归因请求头

| 请求头 | 含义 | 当前约定 |
| --- | --- | --- |
| `X-Agent-Name` | 标识自动化调用的执行者 | Code Agent 验收固定为 `code-agent` |
| `X-Agent-Run-Id` | 标识本次 Agent 运行批次，关联生成工单和费用 | 每次运行唯一，同一轮请求复用 |
| `X-Test-Run-Id` | 标识接口测试批次，关联请求日志和耗时记录 | 与本轮 Agent 批次使用相同值 |

例如同一次验收使用以下请求头。下一次运行生成新的批次值：

```http
X-Agent-Name: code-agent
X-Agent-Run-Id: mv-regression-20261117-a81f6d
X-Test-Run-Id: mv-regression-20261117-a81f6d
```

这些头随 HTTP 请求发送，由自动化客户端或浏览器测试脚本设置，不需要用户在页面表单中填写。它们提供来源和费用追踪，身份认证仍通过登录 Cookie 和访问令牌完成。带 Agent 标记的生成请求若缺少必需头，会在创建工单前返回 422；账号未获 Agent 授权时可返回 403。

用量与文本调用日志直接保存来源、Agent 名称和批次；Worker 从持久工单恢复上下文。升级时能关联工单的历史日志按工单回填；无工单的历史调用来源不可推断，标为 `legacy_unknown`，不冒充普通业务。授权只能验证账号有测试资格，不能从没有来源头的普通交互中自动识别自动化客户端。

刷新凭证按 family 轮换：旧凭证超过 5 秒缓冲窗口后被重用，会撤销该 family 的全部刷新凭证并提高账号访问凭证版本，已有 access token 随即失效；短窗口重复请求只拒绝，避免将多个页签的并发刷新立即判作盗用。测试不得输出原始凭证。

### 测试服视频并发联调

在已部署相同版本的 MV 测试机运行 `scripts/test-video-mock-capacity.sh`。该入口使用测试机的个人平台 Key，创建和查询经过 MV 的 all in one 适配器。专用工单类型 `mock_video_acceptance` 将平台验收的 2500 个占位与业务视频 2000 个槽位隔离，每笔受理写入 MV 工单及 Agent 用量记录。每个请求同时指定 URL 和请求体的 mock 开关。测试进程核对零积分、无供应商任务 ID 和空媒体终态。

默认目标为 Seedance 1000、WAN 1000、Veo 500。控制进程将工单提交后，由测试机上的四个 Worker 容器用同一个 Key 从 MV 数据库读取工单，执行 60 秒的同步错峰查询。计时包含进程等待和解析，汇总脚本另外记录 HTTP 请求头发出的时间。报告位于测试机 `.deployment/mock-video/`，包含去凭证的工单清单、各分片和汇总结果。指定 `MV_DIAGNOSTIC_VEO_SLOTS` 可以复测被其他业务占用后的可用容量，小于 500 的诊断始终返回未通过。如进程中断，可在相同版本 backend 容器用 `MV_DRAIN_RUN=<本轮 ID> python -m scripts.mock_video_acceptance` 恢复终态核对。业务 Worker 的 2000 槽跨副本领取、边界和 Redis 唤醒另由 `make test-middleware` 使用隔离 PostgreSQL/Redis 验证。

专项验收目标为单 Key 持续 100 QPS、60 秒内 6,000 次查询全部成功、覆盖全部 2,500 个在途任务，MV 端到端 P95 ≤ 500 毫秒。四个查询分片按同一个 UTC 起点每 10 毫秒轮到一个分片，同一分片的计划间隔为 40 毫秒。分片预先登记每次查询的绝对时刻，到点后派发，在发送 HTTP 请求头之前限制短时突发。每个分片最多积攒 6 次放行机会，限速器按每 39.6 毫秒恢复一次、相邻实际放行至少间隔 5 毫秒处理短时积压。四个分片均以原定时刻为最早发送时间。每个分片分批预热 32 条持久连接，每次查询独占一条，解析完毕即归还，每个计划查询仍只调用一次原查询适配器。60 秒窗口采用左闭右开区间，发出时间以请求头发送完成为准；跨窗发送会使验收失败。

分片 JSON 的 `scheduling` 按计划秒记录调度迟到超过 50 毫秒（`scheduler_late`）、待处理查询达到 96 个（`pending_limit`）、等到窗口结束仍无法发送（`window_closed`），以及派发时观测到的待处理峰值和最大迟到毫秒数。漏发只计一次，同时迟到和队列满时归入迟到。汇总的 `wire_rolling_peaks` 显示四个分片合计滚动 100 毫秒和 1 秒的实际发送峰值，`sent_in_window` 为窗口内发送数。429 和状态解析错误独立计数。
