# 性能监控与接口耗时观测

回答一个运营问题：**「页面卡顿，到底是接口返回慢、网络慢、响应体太大，还是前端渲染慢？」**

本文档覆盖三层观测体系：后端全量请求耗时日志、前端会话级埋点、管理后台「性能」页。
配套测试见文末「测试清单」，全部改动已在线上部署（2026-08-12）。

## 1. 架构总览

```
浏览器（前端）
 ├─ apiRequest/openApiStream 埋点（src/perf.ts，会话级 ring buffer）
 │    t0 fetch发出 → t1 响应头到达 → t2 json() 完成
 │    ├─ networkMs = t1 - t0（网络 + 服务端处理）
 │    └─ parseMs   = t2 - t1（响应体大小 / JSON 序列化）
 │
 ├─ X-Polling: 1（轮询/SSE 请求打标记，前后端同时跳过）
 │
 └─ 普通请求 → nginx → FastAPI
                         └─ api_request_log_middleware
                              ├─ X-Polling: 1 → 直接跳过（最优先）
                              ├─ 无 run_id 且未开全量 → 跳过
                              └─ 记录 duration_ms + 脱敏后的请求/响应摘要
                                   └─ api_request_logs 表（PostgreSQL）
                                          ├─ /admin/request-logs（列表/详情）
                                          ├─ /admin/request-logs/summary（聚合 P95）
                                          └─ 管理后台「性能」页展示
```

**定位链（三个数一对，原因立现）：**

| 现象 | 结论 |
| --- | --- |
| 后端 `duration_ms` / P95 大 | 接口 / 数据库 / 上游 AIGC 慢 |
| 前端 networkMs 大、后端正常 | 网络 / nginx 网关 |
| 前端 parseMs 大 | 响应体太大（大 JSON 列表） |
| 主线程长任务集中在渲染期 | 前端渲染问题（大数据 v-for / 图片解码） |

## 2. 后端请求日志

### 2.1 开关（线上已开启）

- 默认：仅带 `X-Test-Run-Id` 头的测试流量入库（e2e 自动注入，生产正常流量零开销）。
- 全量：`backend/.env` 置 `API_REQUEST_LOG_ALL=true` 后**所有**非轮询 `/api/*` 请求入库。
  注意：变量必须写在 `backend/.env`（容器 `env_file`），写在 `.env.production` 不会注入容器。

### 2.2 轮询/长连接过滤（X-Polling: 1）

轮询每 2-5 秒刷一次、SSE 挂几分钟，全量记录会产生海量重复数据，且 SSE 的
`duration_ms` 等于整个连接时长，会污染慢请求统计。因此：

- **前端**所有轮询/长连接请求统一打 `X-Polling: 1` 头（清单见 3.3）；
- **后端**中间件对带该头的请求直接跳过（优先于 run_id / 全量开关判断）。

用 header 而非路径黑名单的原因：`GET /api/tasks/{id}` 既是初始加载（必须记录耗时）
也是轮询，按路径过滤会误伤初始加载——而初始加载正是用户感知卡顿的关键数据。

### 2.3 落库内容

- 请求/响应体仅 JSON 且 ≤8KB 入库（超过只记 `truncated` 元信息）；
- SSE / 流式 / 二进制不缓冲 body，只记元信息；
- 密码、token 等敏感字段自动脱敏为 `***`。

## 3. 管理后台接口

### 3.1 请求列表 / 慢查询

```
GET /api/admin/request-logs
```

| 参数 | 说明 |
| --- | --- |
| `runId` | 测试批次 ID（e2e 流量） |
| `path` | 路径模糊匹配（contains） |
| `method` / `status` | 方法与状态码精确过滤 |
| `minMs` | 只返回耗时 ≥ 该值（毫秒）的请求 |
| `orderBy` | `created`（默认，时间倒序）或 `duration`（耗时倒序，慢请求 TOP） |
| `limit` / `offset` | 分页，limit ≤ 200 |

单条详情（含脱敏后的输入参数与输出原文）：

```
GET /api/admin/request-logs/{id}
```

### 3.2 耗时聚合（哪个接口稳定慢）

```
GET /api/admin/request-logs/summary?hours=24&minCount=3&limit=50
```

| 参数 | 说明 |
| --- | --- |
| `hours` | 时间窗口，1-168（默认 24） |
| `minCount` | 最少请求次数才计入（默认 3，过滤偶发） |
| `limit` | 返回条数 ≤ 100（默认 50） |

返回 `[{path, method, count, avgMs, p95Ms, maxMs}]`，**只统计正式流量**
（`run_id == ''`，e2e 测试批次天然隔离），按 max 倒序。P95 在 Python 计算
（跨方言，测试库 SQLite 同样可跑）。

### 3.3 前端轮询打标清单（新增轮询必须同步打标）

| 位置 | 请求 | 频率 |
| --- | --- | --- |
| `src/api/mediaGen.ts` `waitForJob` | `GET /generations/{id}` | 3s，最长 11 分钟 |
| `src/api/imageGen.ts` `getImageTask` | `GET /generations/{id}` | 3s，最长 5 分钟 |
| `src/stores/project.ts` `_watchRunningStoryboardLines` | `GET /tasks/{id}` | 5s × 60 次 |
| `src/stores/project.ts` `_pollSegmentRetry` | `GET /tasks/{id}` | 2s × 150 次 |
| `src/api/domain.ts` `streamStoryboardOutline` | SSE 大纲进度 | 长连接 |
| `src/api/domain.ts` `streamMaterialExport` | SSE 素材导出 | 长连接 |

新增轮询点时，在 `apiRequest`/`openApiStream` 的 init headers 里加
`{ 'X-Polling': '1' }`，否则会刷日志。

## 4. 前端会话埋点（src/perf.ts）

会话级、内存 ring buffer、**不落库**（浏览器刷新即清空）：

| 导出 | 说明 |
| --- | --- |
| `recordApiTiming` | 由 client.ts 自动调用；手动调用场景：特殊请求 |
| `apiTimingSummary(limit)` | 按 path+method 聚合 count/avg/p95/max/parseAvg |
| `recentSlowApi(minMs, limit)` | 最近慢请求（含 retried 标志） |
| `recordLongTask` / 长任务监听 | 主线程 >50ms 阻塞片段 |
| `navigationTiming()` | TTFB / DOMContentLoaded / Load |
| `perfSnapshot()` | 一键取当前会话全部观测数据 |
| `startPerfMonitoring()` | 启动 Long Task 监听（main.ts 已调用，幂等） |

埋点位置：`src/api/client.ts` 的 `apiRequest`（t0/t1/t2）与 `openApiStream`
（连接耗时）；轮询请求（X-Polling）自动跳过埋点，与后端日志语义一致。

## 5. 管理后台「性能」页

入口：管理控制台 → 侧栏「性能」。六个区块：

1. **后端 · 慢请求 TOP**（≥1000ms，耗时倒序，点详情看输入输出原文）
2. **后端 · 接口耗时聚合**（24h 正式流量，max 倒序 TOP30，P95>1s 高亮）
3. **本浏览器会话 · API 耗时聚合**（解析均耗单独列出）
4. **本浏览器会话 · 主线程长任务**（>50ms 即卡顿证据）
5. **本浏览器会话 · 整页加载计时**（TTFB / DCL / Load）
6. **本浏览器会话 · 最近慢请求**（≥800ms，含网络/解析/重试拆分）

页面底部附定位链说明。注意：区块 3-6 是**当前浏览器**的数据，排查用户问题时
让用户先操作复现再刷新性能页，或直接看区块 1-2 的后端数据。

## 6. 测试清单（回归验证）

### 6.1 后端（backend/tests/test_request_logging.py，9 个）

```bash
cd backend && .venv/bin/pytest tests/test_request_logging.py -q
```

| 测试 | 覆盖 |
| --- | --- |
| `test_request_logged_with_run_header` | 批次头流量落库 + 详情可取 |
| `test_not_logged_without_run_header` | 未开全量时无头流量不落库 |
| `test_password_redacted_in_request_payload` | 密码/token 脱敏 |
| `test_polling_requests_skipped` | X-Polling 请求不落库（同路径普通请求正常落库） |
| `test_request_logs_filter_min_ms_and_sort_by_duration` | minMs 过滤 + duration 排序 |
| `test_request_log_summary_aggregates_by_path` | 聚合只统计正式流量、字段完整 |
| `test_runs_aggregation` | 批次统计（次数/均峰值/错误数） |
| `test_filters_by_path_and_status` | 列表筛选 |
| `test_request_logs_require_admin` | 权限控制 |

### 6.2 前端（tests/user/perf.test.ts，4 个）

```bash
npm test
```

| 测试 | 覆盖 |
| --- | --- |
| `aggregates API timings by path...` | 聚合计算 count/avg/p95/max、排序 |
| `filters slow API entries by threshold` | 慢请求阈值过滤 + retried 标志 |
| `isPollingHeaders detects the X-Polling marker` | 标记识别 |
| `records timing ... skips polling requests` | apiRequest 埋点集成：普通请求记录、轮询跳过 |

### 6.3 线上手工验证（部署后冒烟）

```bash
# 普通请求 → 应落库（全量模式下无需任何头）
curl -s -o /dev/null http://127.0.0.1:8000/api/auth/me

# 轮询请求 → 不应落库
curl -s -o /dev/null -H "X-Polling: 1" http://127.0.0.1:8000/api/auth/me

# 查库核对（postgres 容器内）
docker compose --env-file .env.production exec -T postgres psql -U mvagent -d mvagent \
  -t -c "SELECT count(*) FROM api_request_logs WHERE created_at > now() - interval '2 minutes';"
```

浏览器冒烟：打开管理后台 → 「性能」页应看到后端聚合数据（正式流量 24h）；
「接口耗时」页可查单条详情。前端埋点数据需在当前浏览器操作后刷新性能页查看。

## 7. 部署与配置备忘

- 全量开关：`backend/.env` 的 `API_REQUEST_LOG_ALL=true`（线上已开，2026-08-12）。
- 中间件在 `backend/app/request_logging.py`，跳过顺序：X-Polling → 非 /api/ → 无头且未开全量。
- 前端埋点：`src/perf.ts`（新增）+ `src/api/client.ts` + `src/main.ts`（启动监听）。
- 管理后台：`src/views/AdminConsoleView.vue` 的「性能」tab。
- 数据量：线上验证 719 条/12 分钟（含用户真实操作），轮询排除后日均量级可控；
  如需长期保存可结合备份策略，表名 `api_request_logs`。
