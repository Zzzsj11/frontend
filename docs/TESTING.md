# 测试指南

测试分层：后端 pytest 验证权限、隔离、软删除、模型、资产和业务旅程；Vitest 验证前端 Store/约束/错误处理；Playwright 验证 API 契约与真实浏览器旅程。

```bash
make test        # 后端 pytest + 前端 vitest
make test-e2e    # 本地 Playwright（mock 链路）
make preflight   # 发布前全流程校验
```

新增功能必须优先补后端集成测试；关键页面再补 Playwright，避免只依靠脆弱的端到端测试。失败产物在 `test-results/`，远程截图在 `test-artifacts/remote/runs/`。

## e2e 凭据约定（强制）

所有远程 spec 统一从 `e2e/env.ts` 取凭据：

- 目标非 localhost 时必须显式提供 `REMOTE_E2E_PASSWORD`，否则启动即报错（fail-fast，防止静默回退到本地开发密码白跑一轮）。
- 推荐方式：复制 `e2e/.env.example` 为 `e2e/.env` 填一次（已 gitignore，playwright.config.ts 自动加载），之后所有 `test:remote*` 命令免环境变量直跑。
- 禁止把真实密码写进任何入库文件。
- 本地后端测试环境 admin/123456 由 `backend/tests/conftest.py` seed，属合法默认值。

## API 耗时采集（接口耗时页）

- 后端 middleware 仅对带 `X-Test-Run-Id` 请求头的流量入库（生产正常流量零开销）；置 `API_REQUEST_LOG_ALL=true` 可临时全量记录（注意数据量）。
- pytest 全量测试由 conftest 自动注入批次头；e2e 的 API 级 spec 注入 `extraHTTPHeaders`，UI 级 spec 通过 `page.route('**/api/**')` 注入。
- 管理后台「接口耗时」页查看：批次列表（次数/均峰值/错误数）→ 单批请求表格（≥1s 高亮）→ 单条详情（脱敏后的输入参数与输出原文）。
- 请求/响应体仅 JSON 且 ≤8KB 入库；SSE/流式/二进制只记元信息。密码等敏感字段自动脱敏为 `***`。

## 远程验收（对已部署环境）

远程自动化固定使用 `http://124.222.219.76:5173`，不使用业务域名；域名可用性由 `scripts/online-health-check.sh` 单独验证，避免将网络问题误判为应用回归。

```bash
npm run test:remote:api        # API 契约/鉴权/隔离/软删除（不消耗生成 Token）
npm run test:remote:frontend   # Chromium 操作线上前端冒烟
npm run test:admin:api         # 管理后台 API 契约
npm run test:admin:frontend    # 管理后台 UI
REMOTE_REAL_GENERATION=1 npm run test:remote:api   # 含真实生成分支（产生费用）
```

成功标准：退出码 0；健康检查 PostgreSQL/Redis 为 true；普通用户不能访问管理员 API 或他人任务；上传返回 TOS HTTPS URL；删除后资源不可再读；页面无全局错误弹窗。测试创建的用户/项目结束时走产品 API 软删除，不得物理删除业务记录。

## 真实生成全链路（有真实成本）

`e2e/full-real-generation.spec.ts` 覆盖：登录 → 建项目 → ASS 上传/情感匹配/选角/逐条提示词 → 通用分镜 → 场景图 → 视频 → 播放器 → 素材 ZIP 导出，全程截图并断言无错误弹窗。默认跳过，`REAL_GENERATION_E2E=1` 才运行。

```bash
npx playwright install chromium   # 首次
docker compose up -d --build      # 四个服务 healthy/running
export REAL_E2E_PROJECT_SUFFIX="$(date +%Y%m%d-%H%M%S)"
npm run test:e2e:real             # 完整模式，上限 90 分钟
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
ADMIN_API_E2E=1 npx playwright test e2e/admin-api.spec.ts       # 远程 API 契约
ADMIN_CONSOLE_E2E=1 npx playwright test e2e/admin-console.spec.ts  # 远程 UI
```

测试不得修改或删除系统人物；模型启停类测试完成后恢复原状态。

## 上线验收清单

域名与 HTTPS：域名解析到公网 IP；HTTPS 可打开且 HTTP 自动跳转；证书签发与自动续期正常；Nginx 为域名模式。
容器与数据：四服务 healthy；`/api/health` 200；迁移自动执行；种子数据就绪；数据库/Redis 不公网开放（调试走 SSH 隧道，必须开放则 IP 白名单）。
账号与业务：管理员登录、双 Token、改密、多用户隔离可用；ASS 解析/歌曲编号匹配/情感命中/通用分镜/场景图/视频/单镜重生成/批量生成/素材导出全通。
媒体与日志：图片、视频、封面、导出包全部 TOS；API 报错入库；Token 记账；失败原因可追踪；关键操作有审计。
最终确认：线上与本地配置分离；生产密钥未入库；备份策略与回滚步骤就绪；验收结果留档。

## 专项改动验证要点

- 导出改动：进度单调递增、完成后归档可读、不同 taskId 状态不覆盖、用户间不可读他人导出、SSE 断开后 GET 状态可恢复。
- 大纲改动：明确人物动作的歌词不得规划为空镜、连续空镜受限、6 条及以上歌词至少 3 个场景、视觉母题不超过大纲声明次数。
- 系统人物改动：默认分类男/女/儿童且只读、对所有用户可见、儿童提示词保持年龄造型一致、原图与缩略图均为 TOS URL；新增系统图片用 `scripts/sync-system-human-assets.py --asset CODE=/path/to/image` 上传，不得复制到项目目录。
- 本机 `make preflight` 的 Docker 阶段经 `docker-compose.local-build.yml` 使用国内镜像代理；服务器部署不加载该文件。代理不可用时用 `LOCAL_NODE_BASE_IMAGE`、`LOCAL_NGINX_BASE_IMAGE` 临时覆盖，不得改服务器部署配置。
