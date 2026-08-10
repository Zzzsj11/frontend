# 测试指南

测试分层：后端 pytest 验证权限、隔离、软删除、模型、资产和业务旅程；Vitest 验证前端 Store/约束/错误处理；Playwright 验证 API 契约与真实浏览器旅程。

```bash
make test
make test-e2e
make preflight
```

远程验收：

```bash
PLAYWRIGHT_BASE_URL=http://SERVER:5173 \
REMOTE_API_BASE_URL=http://SERVER:5173 \
REMOTE_E2E_USERNAME=admin REMOTE_E2E_PASSWORD='***' \
make remote-test
```

失败产物在 `test-results`，远程截图在 `test-artifacts/remote/runs`。新增功能必须优先补后端集成测试；关键页面再补 Playwright，避免只依靠脆弱的端到端测试。
