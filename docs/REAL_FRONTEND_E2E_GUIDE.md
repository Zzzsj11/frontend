# 真实前端全链路自动化测试使用指南

## 1. 用途与边界

测试文件：`e2e/full-real-generation.spec.ts`

该用例通过 Chromium 操作真实前端，覆盖：

1. 管理员登录。
2. 创建歌曲项目。
3. ASS 上传、编号与歌曲情感配置匹配、角色选择、逐条并发提示词生成。
4. 通用分镜参数与角色选择、逐条并发提示词生成。
5. 每条分镜生成场景图。
6. 每条分镜生成视频并在播放器加载。
7. 导出视频片段与整体提示词 Markdown 的 ZIP 素材包。
8. 每个关键节点截图，以及全局错误弹窗断言。

这是有真实外部成本的验收测试，不属于普通 CI 冒烟测试。默认执行 `npm run test:e2e` 时该用例会跳过，只有显式设置 `REAL_GENERATION_E2E=1` 才会调用文本、图片、视频和 TOS 服务。

## 2. 固化测试资产

- 输入夹具：`test-artifacts/full-journey/inputs/10012204-full-e2e.ass`
- 首次通过截图：`test-artifacts/full-journey/screenshots/01-*.png` 至 `24-*.png`
- 首次验收报告：`docs/FULL_FRONTEND_AUTOMATION_REPORT_2026-08-07.md`
- 后续运行产物：`test-artifacts/full-journey/runs/<run-id>/screenshots/`

首次通过截图是视觉和流程基准，不应由复跑脚本覆盖。后续结果默认进入带时间戳的新目录；需要让多个恢复阶段写入同一目录时，为它们传入相同的 `REAL_E2E_RUN_ID`。

## 3. 环境要求

从仓库根目录执行：

```bash
npm ci
npx playwright install chromium
docker compose up -d --build
docker compose ps
```

四个 Compose 服务 `frontend`、`backend`、`postgres`、`redis` 应为 healthy/running。后端配置必须具备可用的：

- PostgreSQL 与 Redis；
- 文本模型供应商；
- 图片模型供应商；
- 视频模型供应商；
- TOS Bucket 与访问凭据；
- 已初始化的 32 个系统人物（男 / 女 / 儿童分类）和歌曲情感配置。

视频生成支持 4–15 秒整数时长。真实基准仍选择 5 秒以控制成本；涉及约束变更时，应先依赖前后端边界测试覆盖 4 和 15 秒，不要仅为验证边界重复生成昂贵视频。

默认测试地址为 `http://127.0.0.1:5173`（通过 `PLAYWRIGHT_BASE_URL` 指定）。不要把真实供应商密钥提交到仓库。

## 4. 推荐执行方式

为一次测试先确定唯一 run-id，便于日志、截图和数据库记录关联：

```bash
export REAL_E2E_RUN_ID="$(date +%Y%m%d-%H%M%S)"
export PLAYWRIGHT_BASE_URL="http://127.0.0.1:5173"
export REAL_E2E_PROJECT_SUFFIX="$REAL_E2E_RUN_ID"
npm run test:e2e:real
```

完整模式会依次执行 ASS 和通用分镜。测试超时上限为 90 分钟；提示词、图片、视频等待上限分别为 10、15、25 分钟。

测试完成后检查：

```bash
find "test-artifacts/full-journey/runs/$REAL_E2E_RUN_ID/screenshots" -type f | sort
```

完整成功应生成 24 张截图。Playwright 退出码必须为 0，页面中不能存在 `role=alertdialog` 的错误弹窗。

## 5. 分阶段与断点恢复

### 仅执行通用分镜

适用于 ASS 已成功、只需重跑通用分镜的情况。编号从 13 开始：

```bash
REAL_E2E_RUN_ID="$REAL_E2E_RUN_ID" npm run test:e2e:real:general
```

### 复用已有通用视频，仅验证播放器和导出

该模式不会重新调用模型。它登录后选择列表中最后一个“通用分镜”任务，确认已有两段视频，然后复验播放器与素材导出：

```bash
REAL_E2E_RUN_ID="$REAL_E2E_RUN_ID" npm run test:e2e:real:export
```

使用此模式前必须确认当前用户最后一个通用任务就是目标任务。若数据库中存在其他新任务，应先通过 UI 或数据库只读查询核实，不要盲目运行。

## 6. 可配置环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `REAL_GENERATION_E2E` | 未设置 | 必须为 `1` 才运行真实测试 |
| `PLAYWRIGHT_BASE_URL` | `http://127.0.0.1:4173` | 使用外部已启动环境时建议设为 `http://127.0.0.1:5173` |
| `REAL_E2E_PHASE` | 完整流程 | 支持 `general`、`general-export` |
| `REAL_E2E_RUN_ID` | 当前 ISO 时间 | 后续产物目录名；恢复阶段必须复用同一值 |
| `REAL_E2E_ARTIFACT_DIR` | `test-artifacts/full-journey/runs/<run-id>` | 自定义截图根目录 |
| `REAL_E2E_ASS_FILE` | 固化的 `10012204` ASS | 替换 ASS 输入夹具 |
| `REAL_E2E_USERNAME` | `admin` | 测试账号 |
| `REAL_E2E_PASSWORD` | `123456` | 测试密码；共享环境应显式覆盖 |
| `REAL_E2E_PROJECT_SUFFIX` | 空 | 建议使用 run-id，避免项目同名 |

## 7. 成功判定与数据库核验

浏览器测试成功后，还应核对：

- 新增 2 个项目和 2 个任务（完整模式）；
- ASS 与通用分镜各 2 条 `storyboard_lines`，状态为 `succeeded`；
- 共 4 个有效 `scene_assets` 与 4 个有效 `shot_assets`；
- `generation_jobs` 中 storyboard、image、video 全部成功；
- 每次有成本的调用均有 `token_usage_records`，即使供应商返回的 Token 数为 0；
- 两条 `material_exports` 为 `ready`；
- 所有图片、封面、视频、ZIP URL 都是 TOS HTTPS 地址，并能返回 HTTP 200；
- `api_error_logs` 不存在本次运行产生的非预期 4xx/5xx。浏览器冷启动时无 Refresh Token 导致的 `/api/auth/refresh` 401 属于已知预期记录。

清理测试数据时必须调用产品删除 API 或更新 `deleted_at`，不得物理删除业务记录。系统人物、系统分类、管理员及歌曲情感配置属于默认数据，不能清除。

## 8. 失败处理原则

1. 先查看 Playwright 的错误上下文、失败截图和 trace。
2. 再查看后端日志、`generation_jobs`、`api_error_logs` 和 Token 账单，区分前端交互失败与供应商生成失败。
3. 如果图片或视频已经成功入库，优先使用恢复阶段，不要直接全量重跑造成重复收费。
4. 不要把失败任务改成成功；修复代码后按实际状态重试。
5. 测试产生的项目在报告确认前保留；确认后按软删除规则清理。

常用诊断命令：

```bash
docker compose logs --tail=200 backend
docker compose exec -T postgres psql -U mvagent -d mvagent
npx playwright show-trace test-results/<failed-test>/trace.zip
```

## 9. 用例迭代约定

- 优先使用角色、标签和可访问名称定位元素；只有缺少语义标记时才使用 CSS 类。
- 新增关键用户节点时同步增加截图，并更新截图编号和本指南的成功数量。
- 调整镜头数量时同步调整提示词、图片、视频的数量断言。
- 不要降低超时来掩盖供应商延迟，也不要删除错误弹窗断言。
- 新基准确认稳定后，将选定运行目录复制为新的版本化基准并新增报告；不要静默覆盖 2026-08-07 基准。
- 变更测试流程后至少运行 `npm test`、普通 `npm run test:e2e`；涉及真实供应商协议、画幅、时长或导出时，再执行真实全链路。

## 10. Code Agent 交接清单

其他 Code Agent 接手时应先阅读本指南和首次验收报告，然后：

1. 检查工作树，避免覆盖用户的未提交修改。
2. 检查 Docker 健康、迁移头和默认数据数量。
3. 明确本次 run-id、测试账号、输入夹具和计划运行的阶段。
4. 在调用真实模型前告知用户会产生实际成本。
5. 运行过程中每分钟以内提供一次进度，视频生成期间可查询任务状态但不要重复提交。
6. 结束后报告 Playwright 结果、截图目录、数据库状态、Token 用量、TOS 可用性和软删除清理情况。
