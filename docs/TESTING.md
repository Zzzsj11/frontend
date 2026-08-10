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

导出改动至少验证：进度单调递增、完成后归档可读、不同 `taskId` 状态不覆盖、用户之间不可读取导出记录、SSE 断开后 GET 状态可以恢复。大纲改动至少验证：明确人物动作歌词不得规划为空镜、连续空镜受限、6 条及以上歌词至少使用 3 个场景、视觉母题不超过大纲声明次数。
