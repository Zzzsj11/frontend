# 管理后台自动化测试使用说明

管理后台测试分为三层，适合本地开发、CI 和部署后验收复用。

## 后端集成测试

```bash
cd backend
.venv/bin/pytest -q tests/test_admin_console.py
```

测试使用独立 SQLite 数据库，覆盖管理员鉴权、仪表盘、模型注册、操作审计、普通用户越权拦截及用户端模型选项。

## 本地前端与 API 测试

```bash
npm run test:admin
```

Playwright 默认自动启动本地 Vite。后端应提前启动并由 Vite 代理访问。

## 远程部署验收

```bash
PLAYWRIGHT_BASE_URL=http://SERVER_IP:5173 \
REMOTE_E2E_USERNAME=admin \
REMOTE_E2E_PASSWORD='YOUR_PASSWORD' \
npm run test:admin
```

`admin-api.spec.ts` 验证接口权限与响应契约；`admin-console.spec.ts` 验证登录、仪表盘、模型、用量、错误及审计页面。

测试不得修改或删除系统人物。模型启停类测试应在完成后恢复原状态。
