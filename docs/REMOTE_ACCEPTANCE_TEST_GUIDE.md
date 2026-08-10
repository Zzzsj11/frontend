# 远程 API 与前端自动化验收指南

## 目标

该测试资产用于从开发机直接验收已部署环境，分为三层：

1. `remote-api.spec.ts`：覆盖全部后端路由、鉴权、Refresh Token、管理员能力、多用户隔离、TOS、项目、角色、ASS、通用分镜、软删除和错误日志。
2. `remote-frontend.spec.ts`：使用 Chromium 操作线上真实前端，覆盖登录、创建项目、ASS 配置、通用分镜配置、模型约束、截图和清理。
3. `full-real-generation.spec.ts`：有真实成本的文本、图片、视频、素材导出全链路。

## 环境变量

```bash
export PLAYWRIGHT_BASE_URL="http://124.222.219.76:5173"
export REMOTE_API_BASE_URL="$PLAYWRIGHT_BASE_URL"
export REMOTE_E2E_USERNAME="admin"
export REMOTE_E2E_PASSWORD="supermv007"
export REMOTE_E2E_RUN_ID="$(date +%Y%m%d-%H%M%S)"
```

不要把真实密码、Token 或供应商密钥写入仓库。

远程 Playwright 与 API 自动化必须使用上述服务器 IP 和端口，不使用业务域名。域名只由 `scripts/online-health-check.sh` 验证 HTTPS、证书和反向代理，避免 DNS、备案或证书链路波动干扰业务回归。

## 默认远程验收（不消耗生成 Token）

```bash
npm run test:remote:all
```

API 套件会触达图片、视频、聊天、SSE 等路由的鉴权或参数校验分支，但不会提交真实生成任务。它会真实使用 PostgreSQL、Redis 和 TOS。

## 包含真实生成的完整验收

该命令会产生实际模型费用：

```bash
REMOTE_REAL_GENERATION=1 npm run test:remote:all:real
```

其中真实前端全链路默认生成 ASS 和通用分镜各两条，并生成对应图片、视频和素材 ZIP。运行前确认线上余额、供应商配置和 TOS 可用。

## 数据与产物

- API 测试创建独立普通用户，结束时由管理员 API 软删除用户及其业务数据。
- 前端冒烟测试创建唯一项目，结束时调用删除 API 软删除。
- 前端截图位于 `test-artifacts/remote/runs/<run-id>/screenshots/`。
- 真实生成截图位于 `test-artifacts/full-journey/runs/<run-id>/screenshots/`。
- 失败时 Playwright trace 位于 `test-results/`。

所有清理均走产品 API 和 `deleted_at`，不得直接物理删除数据库记录。

## 单独执行

```bash
npm run test:remote:api
npm run test:remote:frontend
npm run test:remote:frontend:real
```

如果只验证 API 的真实生成分支：

```bash
REMOTE_REAL_GENERATION=1 npm run test:remote:api
```

## 成功标准

- Playwright 退出码为 0。
- API 健康检查中 PostgreSQL 与 Redis 为 `true`。
- 普通用户不能访问管理员 API，也不能读取其他用户任务。
- 上传及导入返回 TOS HTTPS URL。
- 删除后资源不可再读取。
- 页面不存在全局错误弹窗。
- 每次运行使用独立 run-id，并生成独立截图目录。
