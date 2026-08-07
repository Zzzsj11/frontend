# MV Agent Docker 与前端自动化测试报告

- 测试日期：2026-08-06
- 项目目录：`/Users/local-agent/xwrj/mv-agent-frontend`
- 访问地址：`http://127.0.0.1:5173`
- 截图目录：`/Users/local-agent/xwrj/mv-agent-frontend/test-artifacts/screenshots`

## 1. Docker 编排结果

已将以下服务纳入根目录 `docker-compose.yml`：

| 服务 | 容器职责 | 状态 | 端口 |
| --- | --- | --- | --- |
| frontend | Vue 构建产物 + Nginx，反向代理 `/api`、`/media` | Healthy | 5173 |
| backend | FastAPI + 启动时 Alembic migration | Healthy | 仅容器网络 8000 |
| postgres | 会话、消息、生成任务持久化 | Healthy | 5433 |
| redis | 任务热缓存、事件流、Pub/Sub | Healthy | 6380 |

数据卷：`mvagent_postgres`、`mvagent_redis`、`mvagent_media`。

## 2. 环境配置结果

| 配置 | 结果 | 说明 |
| --- | --- | --- |
| Chat | 通过 | 已兼容 Anthropic Messages 与 OpenAI Chat Completions 两种协议；统一 AIGC Key 真实请求返回 `CHAT_SHARED_KEY_OK` |
| TOS | 通过 | 已接入参考项目配置；真实上传 SVG、通过公网 URL 回读 HTTP 200，并清理测试对象 |
| PostgreSQL | 通过 | 迁移表：`chat_sessions`、`chat_messages`、`generation_jobs` |
| Redis | 通过 | `PING` 返回 `PONG`，Chat 事件写入 Redis |
| 生图 | 通过 | 复用统一 AIGC Key，真实任务成功，结果已转存 TOS |
| 生视频 | 通过 | 复用统一 AIGC Key，真实 5 秒任务成功，MP4 已转存 TOS |

统一 AIGC Key 通过 Docker secret 挂载，不写入 Git、不烘焙进镜像。健康检查中 `chatConfigured`、`imageConfigured`、`videoConfigured` 均为 `true`。

## 3. 自动化测试结果

| 测试项 | 结果 | 证据 |
| --- | --- | --- |
| Python API 自动化 | 通过 | Pytest `6 passed` |
| Vue/TypeScript 生产构建 | 通过 | `vue-tsc -b && vite build` |
| Docker 服务健康检查 | 通过 | 四个服务均为 `healthy` |
| Nginx API 反向代理 | 通过 | `/api/health` 返回 PostgreSQL/Redis/TOS/Chat 状态 |
| Chat 真实模型请求 | 通过 | 统一 AIGC Key 返回并持久化 `CHAT_SHARED_KEY_OK` |
| TOS 真实上传/回读 | 通过 | `smoke-tests` 对象上传成功，公网回读 HTTP 200，随后删除测试对象 |
| PostgreSQL migration | 通过 | Alembic `0001_initial`，三张业务表存在 |
| Redis 事件流 | 通过 | user/state/assistant_delta/assistant_done 事件完整 |
| 浏览器控制台 | 通过 | 自动化路径中 0 条 error/warning |
| 生图真实付费请求 | 通过 | Yinghe 任务完成至 100%，1024×1024 PNG 已归档 TOS |
| 生视频真实付费请求 | 通过 | Seedance 任务完成至 100%，5 秒 16:9 MP4 已归档 TOS |
| ASS 文件格式校验 | 通过 | 3/3 文件结构、时间轴与 Dialogue 字段合法 |
| ASS 真实分镜生成 | 通过 | `00001667.ass` 返回 HTTP 200，39 条字幕生成 17 个有效分镜 |

### ASS 文件测试补充（2026-08-06）

- 原文件目录：`/Users/local-agent/xwrj/mv-agent-frontend/test-artifacts/ass/original`
- UTF-8 标准化目录：`/Users/local-agent/xwrj/mv-agent-frontend/test-artifacts/ass/utf8`
- `00001384.ass`：GB18030，66 条 Dialogue，时间轴 4.28–222.24 秒，校验通过。
- `00001627.ass`：UTF-8 BOM，51 条 Dialogue，时间轴 8.37–184.37 秒，校验通过。
- `00001667.ass`：UTF-8 BOM，39 条 Dialogue，时间轴 21.88–188.20 秒，校验通过。
- 真实链路选择 `00001667.ass`，请求耗时 61.28 秒，生成 17 个分镜；17/17 的场景提示词与分镜提示词均非空。
- 完整真实响应：`/Users/local-agent/xwrj/mv-agent-frontend/test-artifacts/ass/00001667-real-response.json`

## 4. 前端自动化路径与截图

1. `01-首页与分镜编辑器.jpg`：首页布局、侧边栏、分镜编辑器、播放器、时间轴。
2. `02-ASS分镜弹框.jpg`：ASS 分镜入口、角色库选择、ASS 上传和额外要求。
3. `03-通用分镜参数弹框.jpg`：角色库、音乐属性、视觉属性和生成规模。
4. `04-通用分镜角色与参数选择.jpg`：选择“苏晚”并将季节切换为“冬”。
5. `05-分镜提示词编辑弹框.jpg`：点击分镜提示词后自动选中“分镜”编辑项。
6. `06-真实生图结果.png`：统一 AIGC Key 真实生成的 1024×1024 图片。
7. `07-真实生视频首帧.jpg`：真实生成的 5 秒视频在第 1 秒提取的画面。

前端交互截图为 1280×720；真实生图保留 1024×1024 原始分辨率；视频证据帧为 1280×720。全部按执行顺序编号。

真实视频文件：`/Users/local-agent/xwrj/mv-agent-frontend/test-artifacts/真实生视频结果.mp4`。

## 5. 启动与复测

```bash
cd /Users/local-agent/xwrj/mv-agent-frontend
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:5173/api/health
```

停止服务：

```bash
docker compose down
```

如需清除数据库、Redis 和媒体数据，必须由使用者明确确认后再删除 Docker volumes。

## 6. 密钥策略

Chat、生图、生视频复用参考项目的统一 `AIGC_TOKEN`。本地密钥文件为 `backend/.provider_config.py`，已加入 `.gitignore` 和 `.dockerignore`；Compose 以 `/run/secrets/provider_config` 只读挂载给后端。仍可通过 `LLM_API_KEY`、`IMAGE_API_KEY`、`VIDEO_API_KEY` 分别覆盖。
