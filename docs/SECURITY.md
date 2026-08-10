# 安全基线

服务器测试环境禁止默认管理员密码和开发 JWT；Secret 只存服务器 600 权限环境文件或受控 Secret Manager。PostgreSQL、Redis 不开放公网，优先在容器内维护，确需远程客户端时通过 SSH 隧道访问。管理员建议使用强密码和 IP 白名单。预发布与正式生产安全方案在 v1.0.0 完成后单独设计。

日志禁止记录密码、Token、Cookie、完整 API Key。上传校验类型和大小，TOS 使用私有 Bucket/签名 URL是下一阶段任务。每周运行 `scripts/security-check.sh`，依赖高危漏洞进入修复队列，Critical 阻断发布。

Docker 基础镜像必须同时写明版本和已验证 SHA-256 digest，禁止只依赖可漂移标签。更新 digest 时要核对镜像内实际版本、来源和漏洞扫描结果；服务器本地构建的发布镜像必须保留 Commit SHA。
