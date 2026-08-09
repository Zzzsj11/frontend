# MV Storyboard Agent

面向 MV 制作流程的 AI 分镜 Web 应用。用户可以上传带歌曲编号的 ASS 字幕，或直接创建通用 MV 分镜；系统结合歌曲情感配置、系统角色与用户要求，逐条并发生成分镜提示词，并继续生成场景图、视频片段和可下载的素材包。

当前版本：`v0.9.1 web 内测版初版`。

## 核心能力

- ASS 分镜：解析 ASS 时间轴和歌词，通过文件名中的歌曲编号匹配歌曲情感配置。
- 通用分镜：按曲风、情感、季节、角色、画幅、镜头数和总时长规划空镜与人物镜。
- 渐进式生成：单次 API 只生成一条分镜提示词，前端以受控并发完成全量任务，减少首条结果等待时间。
- 角色库：内置 30 个系统角色，所有用户可见；用户上传或生成的私有角色及媒体彼此隔离。
- 媒体生成：场景图与视频异步生成，视频时长支持 4–15 秒整数，画幅支持 16:9、9:16、4:3、1:1。
- 生成配置：ASS 与通用分镜均保存画幅、清晰度、图片模型和视频模型；当前固定为 Img2 与 sd2.0，扩展事项见 [`TODO-LIST.md`](TODO-LIST.md)。
- 素材导出：将子项目内的视频片段与整体提示词 Markdown 打包成 ZIP 并提供下载。
- 多用户与鉴权：短期 Access Token + Refresh Token，管理员和普通用户的数据按所有权隔离。
- 数据审计：所有业务删除均为软删除；模型调用记录输入、输出及缓存 Token；后端 API 错误脱敏后入库。
- TOS 媒体存储：上传图片、生成图片、视频、首帧封面和导出包均持久化到 TOS，项目目录不保存业务媒体文件。

## 用户旅程

### ASS 分镜

1. 用户登录并创建歌曲项目。
2. 上传 ASS 文件；文件名必须包含数字歌曲编号。
3. 后端解析字幕并在 `song_emotion_profiles` 中匹配歌曲情感配置；无法匹配或显式编号不一致时返回可读错误。
4. 用户选择系统角色或自己的私有角色。
5. 后端创建任务、歌词分段、故事圣经与待生成分镜行。
6. 前端按并发上限逐条调用提示词生成 API，每条请求携带当前歌词和全量歌词上下文。
7. 用户逐镜生成场景图，再以场景图、角色和镜头提示词生成 4–15 秒视频片段。
8. 用户在播放器和时间轴中检查结果，最后导出视频片段与提示词 ZIP。

### 通用 MV 分镜

1. 用户创建项目，选择通用分镜。
2. 设置音乐分类、季节、年龄段、视觉风格、画幅、空镜/人物镜数量、总时长与角色。
3. 系统校验每镜规划时长均可落在 4–15 秒，并构建统一故事弧线与角色连续性约束。
4. 前端并发请求每一条分镜提示词；空镜禁止人物，人物镜使用预分配角色。
5. 后续场景图、视频、播放器和素材导出流程与 ASS 分镜一致。

## 技术架构

```mermaid
flowchart LR
    U["浏览器用户"] --> FE["Vue 3 Web 前端"]
    FE -->|"Access Token / Refresh Cookie"| API["FastAPI API"]
    API --> PG["PostgreSQL 16"]
    API --> REDIS["Redis 7"]
    API --> LLM["OpenAI-compatible LLM"]
    API --> IMG["图片生成服务"]
    API --> VIDEO["Seedance 视频生成服务"]
    API --> TOS["Volcengine TOS"]
    LLM --> API
    IMG --> API
    VIDEO --> API
    TOS -->|"稳定 HTTPS 媒体地址"| FE
```

### 前端

- Vue 3、TypeScript、Vite
- Pinia：项目、任务、分镜、媒体和播放状态
- Vue Router：登录、主编辑器、密码修改、用户管理
- 原生 Fetch API：统一 Access Token 注入、刷新和错误处理
- Vitest + Vue Test Utils：单元与状态测试
- Playwright：浏览器用户旅程与真实生成验收
- Nginx：生产静态资源及 `/api` 反向代理

### 后端

- Python 3.13、FastAPI、Pydantic
- SQLAlchemy Async + asyncpg：PostgreSQL 异步数据访问
- Alembic：数据库迁移
- Redis：生成任务热状态、SSE 事件和跨进程发布订阅
- httpx：模型、媒体供应商和远程资源访问
- PyJWT + Argon2：Access/Refresh Token 与密码哈希
- Volcengine TOS Python SDK：TOS 对象存储访问
- pytest：API、多用户隔离、存储、提示词质量和完整用户旅程测试

### 数据与安全

PostgreSQL 是持久化事实来源，主要保存用户、刷新令牌、项目、子任务、角色关系、分镜行、场景/视频/语音资产、生成任务、素材导出、聊天、歌曲情感配置、Token 账单和 API 错误日志。

- 所有新增业务表均包含 `created_at`、自动更新的 `updated_at` 和 `deleted_at`。
- 删除接口只写入 `deleted_at`，不物理删除业务数据。
- 系统角色可被所有用户读取，私有角色、项目和生成媒体按 `user_id`/项目所有权隔离。
- 请求日志会对密码、Token、Cookie 等敏感字段脱敏。
- 浏览器不会获得模型供应商或 TOS 密钥。

## 目录结构

```text
.
├── src/                         Vue 前端
│   ├── api/                     API 与媒体生成客户端
│   ├── components/              编辑器、角色库、播放器和全局弹窗
│   ├── stores/                  Pinia 状态与用户旅程编排
│   └── views/                   登录、账户和管理页面
├── backend/
│   ├── app/                     FastAPI、领域服务、任务、存储和种子数据
│   ├── migrations/              Alembic 迁移
│   └── tests/                   后端自动化测试
├── e2e/                         Playwright 用户旅程
├── tests/                       前端单元测试
├── docs/                        验收报告与测试使用文档
├── test-artifacts/full-journey/ 固化 ASS 输入与全链路基准截图
└── docker-compose.yml           完整环境编排
```

## 运行依赖

推荐使用 Docker 启动完整环境：

- Docker Desktop / Docker Engine，支持 Compose v2
- 可用的 PostgreSQL、Redis、LLM、图片生成、视频生成和 TOS 配置
- 浏览器访问端口默认 `5173`

本地开发额外需要：

- Node.js 22+ 与 npm
- Python 3.13+
- PostgreSQL 16
- Redis 7

## 配置

后端示例配置位于 [`backend/.env.example`](backend/.env.example)。首次运行至少需要准备：

```bash
cp backend/.env.example backend/.env
```

然后配置以下类别：

- `JWT_SECRET`：至少 32 字符的随机值，生产环境禁止使用 Compose 默认值。
- `LLM_*`：兼容 OpenAI 协议的分镜文本模型。
- `IMAGE_*`：图片生成服务。
- `VIDEO_*`：视频生成服务。
- `TOS_*`：引用媒体桶、视频归档桶、前缀和公开域名。
- `BUSINESS_API_KEY`、`BUSINESS_USER_ID`：顶部栏业务余额查询凭证；未配置时安全显示 `--`，不会阻塞其他功能。
- `DATABASE_URL`、`REDIS_URL`：本地启动时的数据服务地址。

项目也支持将统一供应商配置放在 `backend/.provider_config.py`，Compose 会将其作为 secret 挂载。`backend/.env`、`.env.chat` 和 `.provider_config.py` 均已被 Git 忽略，严禁提交真实密钥。

## Docker 启动

```bash
docker compose up -d --build
docker compose ps
```

服务地址：

- Web：<http://127.0.0.1:5173>
- 健康检查：<http://127.0.0.1:5173/api/health>
- PostgreSQL：`127.0.0.1:5433`
- Redis：`127.0.0.1:6380`

后端容器启动时会自动执行 Alembic 迁移并补齐系统种子数据。首次管理员账号默认为：

```text
用户名：admin
密码：123456
```

首次登录后应立即修改密码。停止服务：

```bash
docker compose down
```

该命令不会删除命名卷。只有明确需要销毁数据库与 Redis 数据时才使用 `docker compose down -v`。

## 本地开发启动

先启动数据服务：

```bash
docker compose up -d postgres redis
```

启动后端：

```bash
cd backend
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

另开终端启动前端：

```bash
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Vite 开发服务器会将 `/api` 代理到后端。

## 测试

```bash
# 前端单元测试
npm test

# 后端测试
cd backend && .venv/bin/pytest -q

# 普通 Playwright（真实生成用例默认跳过）
npm run test:e2e

# 前端单元测试 + 普通 Playwright
npm run test:all
```

真实 ASS + 通用分镜测试会调用付费模型和媒体供应商，必须显式开启：

```bash
export PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173
export REAL_E2E_RUN_ID="$(date +%Y%m%d-%H%M%S)"
export REAL_E2E_PROJECT_SUFFIX="$REAL_E2E_RUN_ID"
npm run test:e2e:real
```

详细的断点恢复、截图约定、数据库核验、Token 和 TOS 检查方式见 [`docs/REAL_FRONTEND_E2E_GUIDE.md`](docs/REAL_FRONTEND_E2E_GUIDE.md)。首次真实验收结果见 [`docs/FULL_FRONTEND_AUTOMATION_REPORT_2026-08-07.md`](docs/FULL_FRONTEND_AUTOMATION_REPORT_2026-08-07.md)。

## 常用运维命令

```bash
docker compose logs -f backend
docker compose exec backend alembic current
docker compose exec postgres psql -U mvagent -d mvagent
docker compose exec redis redis-cli
```

数据库结构变更必须通过 Alembic 迁移；清理业务数据必须使用产品删除 API 或更新 `deleted_at`，不得绕过软删除规则。

## 当前状态

`v0.9.1` 是 Web 内测版初版，已完成登录、多用户隔离、ASS/通用分镜、逐条提示词生成、角色库、TOS 媒体、图片/视频生成、素材导出、Token 记账、错误审计及完整自动化测试资产。生产发布前仍应完成密钥轮换、默认密码修改、外部服务限流与正式部署环境的容量/安全验证。
