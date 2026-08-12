# DEBUG 交接：ASS 大纲生成间歇性报「e is not iterable」

> 写给接手 debug 的 agent。本文档包含：问题现象、复现方法、已完成的全部排查与排除结论、当前环境状态、建议的下一步。**请先读完再动手，避免重复劳动。**

## 1. 问题现象

ASS 分镜流程：登录 → 创建歌曲项目 → ASS 视频 → 上传 `test-artifacts/full-journey/inputs/10012204-full-e2e.ass` → 选 2 个角色 → 点「生成」。

**间歇性**出现：顶部红色 banner「MV 大纲生成失败：e is not iterable，已拆分的分镜列表已保留」，任务被标记 outline_failed，后续逐句提示词生成不触发，流程卡死。

**关键矛盾：后端实际完全正常**——失败的那次（task-52fc159a38a34d278d71a56986607a86）：

- `llm_call_logs` 中 ass_scene_plan / ass_scene_plan_retry / ass_scene_segment_1 / ass_scene_segment_2 全部 status=ok
- `project_tasks.storyboard_config.storyBible` 完整写入（shots/scenePlan/locations/motifs 齐全，所有集合字段均为 array 无 null）
- `task.status = 'generating'`（正常终态）
- 即：错误是**前端误报**，大纲其实成功了

banner 精确文案经截图裁剪放大确认：`MV 大纲生成失败：e is not iterable，已拆分的分镜列表已保留`。
对照 `src/components/ScriptEditor.vue:169-174` 模板 `MV 大纲生成失败：${store.outlineError}，...`，可得 **`store.outlineError === "e is not iterable"`（精确值，无前缀）**。

## 2. 复现矩阵（已实测）

| 环境                            | 构成                                                               | 结果                                               |
| ------------------------------- | ------------------------------------------------------------------ | -------------------------------------------------- |
| http://localhost:5199           | vite dev（未压缩源码）→ vite proxy → backend 8001                  | **7/7 全部成功，不复现**                           |
| http://localhost:5174 → 现 5173 | 生产容器（压缩构建 + nginx 变量式 proxy_pass + resolver）→ backend | **复现 2 次**（e2e 首轮 + repro 脚本首轮），间歇性 |

后端相同（本地容器 backend，两环境共享）。差异维度只有两个：**nginx 代理层** 或 **生产压缩构建**。

复现脚本（可直接用）：

```bash
# 生产容器跑 N 轮（每轮：建项目→上传→生成→检测 banner 或提示词进度）
REPRO_BASE=http://localhost:5173 REPRO_ROUNDS=6 node test-artifacts/full-journey/runs/repro-outline.mjs
# dev server 对照组（需先起：nohup env VITE_API_PROXY_TARGET=http://127.0.0.1:8001 npx vite --port 5199 --strictPort > /tmp/vite-dev.log 2>&1 &）
REPRO_BASE=http://localhost:5199 REPRO_ROUNDS=6 node test-artifacts/full-journey/runs/repro-outline.mjs
```

每轮真实调大纲 LLM（gpt-5.5，约 30-60s，小额费用）。账号 dev01 / supermv007。

## 3. 已完成的排查与排除结论（勿重复）

### 3.1 outlineError 赋值点全项目只有 3 处（src/stores/project.ts）

- `:639` 置 null（初始化）
- `:665` `outlineError = outlineProgress?.error || ('大纲生成超时，请重试' / '大纲生成失败，请重试')`——SSE 终态分支
- `:679` `outlineError = error instanceof Error ? error.message : '大纲生成失败'`——catch 分支

### 3.2 排除 :665 路径（后端 SSE 透传）

后端写 `outlineProgress.error` 唯一位置：`backend/app/domain.py:650`，格式为
`f"ASS 分镜大纲生成失败：{exc}"[:300]`——**必带「ASS 分镜大纲生成失败：」前缀**。
banner 中 outlineError 无前缀 → 不是后端透传。**确认错误来自 :679 catch，即前端 JS TypeError。**

### 3.3 runOutlineGeneration try 块（project.ts:643-675）逐一排除

| 候选点                                           | 结论                                                                                     |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------- |
| `[...fresh.cast]` (:660)                         | 后端 domain.py:504 cast 永远 list 推导（空也是 []），排除                                |
| `api.fetchSongScript` (src/api/domain.ts:39-111) | 内部全 map/find/断言，无 for...of，排除                                                  |
| `streamStoryboardOutline` (domain.ts:258-289)    | for...of 的 events 是 `buffer.split('\n\n')` 产物必为数组，排除                          |
| `_watchOutline` (project.ts:599-624)             | catch 全吞返回 boolean，异常不传播到外层，排除                                           |
| `_generateStoryboardQueue` (:420-459)            | async 函数，675 行 void 调用，rejection 不被外层 catch，且 worker 内部全 try/catch，排除 |
| `client.ts` apiRequest/openApiStream             | for...of 均为数组常量（retry delays），排除                                              |
| `errorBus.reportApiError` (src/errorBus.ts)      | some/filter/push 数组方法，state.queue 初始化 []，排除                                   |
| `_setTaskStatus` (:564)                          | for...of songProjects 数组，排除                                                         |

### 3.4 V8 消息格式实验（node -e 实测）

- `for..of undefined/null`、`[...undefined]`、数组解构 undefined → 均为 `"undefined is not iterable"` / `"null is not iterable"`
- `Promise.all(undefined)` → `"undefined is not iterable (cannot read property Symbol(Symbol.iterator))"`
- **V8 从不产出单字母 "e is not iterable"**。"e" 只能是**运行时值的 toString 结果**（V8 对对象值打印其字符串化的截断）——什么值 toString 为 "e" 是核心谜题。

### 3.5 生产构建产物无该字面量

`docker exec mv-agent-frontend-frontend-1 grep -r 'is not iterable' /usr/share/nginx/html/assets/` 无结果 →
错误消息不是打包进去的 helper 库（esbuild/babel 降级 helper）模板，是引擎原生抛出。

### 3.6 Playwright trace 分析（失败现场）

`test-results/full-real-generation-ASS-a-ed5f2-ys-through-generated-videos-chromium/trace.zip`
（已解压到 /tmp/pw-trace，如被清理可重新 unzip）：

- 该任务网络记录**只有 POST regenerate 202 一条**（12:02:55.871）；**SSE events 请求与终态 GET /tasks/{id} 均无记录**——注意：进行中的流式 fetch 可能本就不被 trace 记录，此点存疑，不等于请求未发出
- 上传响应（resources/61ef1b3f...json）结构已核实完整：lines[3] 每行 digitalHumanIds/shotOptions/generationStatus 等键齐全
- trace 无 console 错误记录（当时生产代码无日志）

### 3.7 后端 SSE 实现要点（domain.py:771-804）

- 0.75s 轮询 DB，**只在 (status, progress) 变化时推事件，无心跳**
- 大纲 LLM 跑 30-140s 期间若 progress 无变化，SSE 完全静默
- 已设 `X-Accel-Buffering: no`
- 前端看门狗 150s 无事件则 abort（project.ts:602-604）

### 3.8 nginx 配置要点（docker/nginx.conf，bcbed9a 引入）

- 变量式 `proxy_pass $backend_upstream` + `resolver 127.0.0.11 valid=5s ipv6=off`（为平滑重启）
- **未核实**：proxy_read_timeout（默认 60s）、proxy_buffering、gzip 对 `text/event-stream` 的影响——**这是当前最大嫌疑区**

## 4. 当前环境状态（2026-08-11 左右）

本地 docker compose 栈（项目根 docker-compose.yml）：

- frontend：**5173->80**（原为 5174；recreate 时未设 FRONTEND_PORT 回到默认 5173）。镜像已重 build，**含调试日志**：project.ts:678 catch 里加了 `console.error('[outline] runOutlineGeneration failed:', error)`
- backend：**8001->8000**（宿主 8000 被别的项目容器 weeksir-python 占用，操作 compose 必须带 `BACKEND_PORT=8001`，否则 recreate 会撞端口失败）
- postgres 5433 / redis 6380
- vite dev：nohup 起在 5199（可能还活着，`lsof -iTCP:5199` 查）
- 账号：dev01/supermv007（user）、admin/supermv007（admin），本地线上均已设置
- 线上 124.222.219.76:5173 正常服务中（**尚未受此 bug 影响确认**，生产构建与线上一致，理论上同样可能复现）

未提交的工作区改动（git status 可见）：

- `src/stores/project.ts`：+console.error 调试行（定位后可去可留）
- `e2e/full-real-generation.spec.ts`：+REAL_E2E_PHASE=ass 分支、+大纲中间态截图、行数预期 2→3（夹具真实拆分为 2 歌词行+1 outro 尾奏行，已核实 DB/响应）
- `package.json`：+`test:e2e:real:ass` script
- `e2e/.env`：REMOTE_E2E_PASSWORD=supermv007（gitignored）

## 5. 建议的下一步（按优先级）

1. **加料复现抓堆栈**：当前镜像已含 :678 的 console.error，但 3 轮未复现。给 `_watchOutline` 的 catch 和 onEvent 回调也加 console.error（含 error.stack），`docker compose build frontend && BACKEND_PORT=8001 docker compose up -d` 后 `REPRO_BASE=http://localhost:5173 REPRO_ROUNDS=10` 批量跑。抓到堆栈后按行列号反查 `assets/*.js` 产物定位源码。
2. **直接验证 nginx/SSE 边界**：找一个正在 outlining 的任务（或造一个），分别经 nginx(5173) 与直连 backend(8001) `curl -N` SSE 端点对比事件流；重点测静默期 60s+ 是否被 nginx 切断（proxy_read_timeout）、切断后前端 reader 表现。
3. **审查 gzip 对 SSE 的影响**：若 nginx 对 event-stream 开了 gzip，流式可能被缓冲破坏。
4. 若堆栈指向某个具体值的展开：考虑给 fetchSongScript 的行归一化加防御（如 `item.digitalHumanIds ?? []`），并对 SSE payload 做 shape 校验。

## 6. 修复后的回归动作（原计划被此 bug 打断）

1. 去掉/保留调试日志后重新 build 前端镜像，恢复本地容器栈
2. 跑 `PLAYWRIGHT_BASE_URL=http://localhost:5173 REMOTE_E2E_USERNAME=dev01 REMOTE_E2E_PASSWORD=supermv007 REAL_E2E_PROJECT_SUFFIX=本地 npm run test:e2e:real:ass`（ASS 全流程真实验收：大纲→提示词→场景图→视频→导出，自动编号截图到 test-artifacts/full-journey/runs/<runId>/screenshots/，约 20-40 分钟，真实计费 3 图+3 视频）
3. 线上同流程：`PLAYWRIGHT_BASE_URL=http://124.222.219.76:5173 ... 同上`
4. 每轮后 admin 后台 /api/admin/jobs 核对 6 个任务全 succeeded 且带 providerTaskId
5. 全部通过后提交：spec/package.json/project.ts（调试行按规范决定去留）→ make preflight → 双推 → 部署
