# 安全基线

最后核验：2026-08-19。适用于本地开发和服务器测试环境。

## 身份与会话

- 登录分别按“客户端 IP 哈希”和“用户名哈希”在 Redis 做共享限流，默认任一维度 5 分钟最多 8 次，可同时抵御单源枚举与分布式撞同一账号；调整 `LOGIN_RATE_LIMIT_ATTEMPTS` / `LOGIN_RATE_LIMIT_WINDOW_SECONDS` 时必须同步安全测试。
- 临时密码用户由后端强制只能访问 `/api/auth/me`、`/api/auth/change-password` 和 `/api/auth/logout`，不能只依赖前端路由。
- 修改密码会提升 `users.auth_version`、软撤销该用户全部 refresh token，并签发新会话；旧 access/refresh token 均立即失效。
- `APP_ENV=production` 时必须挂载权限为 `600` 的 `/run/secrets/runtime_secrets`，默认 JWT Secret 或缺少 Secret 挂载都会拒绝启动。敏感值不再作为 Docker 环境变量注入；PostgreSQL 使用独立的 `POSTGRES_PASSWORD_FILE`。
- refresh cookie 为 HttpOnly + SameSite=Lax。当前服务器测试环境仍使用 HTTP IP，`REFRESH_COOKIE_SECURE=false` 是已知限制；启用 HTTPS 后必须改为 `true`，同时启用 HSTS。

## 网络与浏览器边界

- PostgreSQL、Redis 不开放公网，维护使用 SSH 隧道；后端端口只绑定回环/Docker 网络。
- nginx 统一透传 `X-Real-IP`、`X-Forwarded-For`、`X-Forwarded-Proto`，Uvicorn 只在受控网关后信任代理头。
- nginx 设置 CSP、禁止 iframe、MIME 嗅探、严格 referrer 和敏感浏览器权限。新增第三方资源域名必须按最小权限更新 CSP 并运行浏览器回归。
- CORS 携带凭证时禁止 `*`，配置错误会在启动阶段失败。
- 公共 `/api/health` 只返回 `{"ok": boolean}`，不公开数据库、Redis、存储和供应商配置状态。

## 文件与远程资源

- 通用上传接口只接受白名单图片、视频、音频，扩展名必须与 MIME 一致；图片还要经过 Pillow 解码。ASS、XLSX 等专用导入由各自接口单独校验。
- 远程导入只允许无凭证 HTTPS 公网地址，逐跳检查重定向、拒绝非全局 IP，并限制 500 MiB；视频归档与首帧提取均流式落盘，不整文件驻留内存。
- DNS 校验与实际连接仍存在很短的重绑定窗口。部署侧应继续限制 backend 出站访问云元数据地址和内网网段；未来若引入统一下载代理，应在代理层做 DNS 固定与 egress ACL。
- 媒体原文件和缩略图进入 TOS；日志禁止记录密码、Token、Cookie、完整 API Key。

## 发布卡口与剩余风险

- 每周运行 `scripts/security-check.sh`；Critical 阻断发布。发布前必须执行 `make preflight` 和权限/API Playwright，发布后核对安全头、限流、强制改密、旧令牌失效与用户隔离。
- `scripts/validate-secret-layout.sh` 阻止 `.env.production` 和 `backend/.env` 重新出现 Key、Token、JWT、TOS 或数据库密码。拥有宿主机 root/Docker 权限的人员仍能读取挂载文件，因此服务器账号与 Docker socket 必须按最高权限管理。
- Docker 基础镜像必须固定版本和已验证 SHA-256 digest，发布镜像保留 Commit SHA。
- 待架构治理：统一出站下载代理、HTTPS/安全 Cookie/HSTS、Redis Pub/Sub 驱动 SSE、外置 Worker 与按供应商并发配额。失败供应商调用的业务配额是否返还需先确定防滥用规则，不能简单自动退款。
