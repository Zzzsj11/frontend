# 测试指南

测试分层：后端 pytest 验证权限、隔离、软删除、模型、资产和业务旅程；Vitest 验证前端 Store/约束/错误处理；Playwright 验证 API 契约与真实浏览器旅程。

```bash
make test
make test-e2e
make preflight
```

远程验收：

```bash
PLAYWRIGHT_BASE_URL=http://124.222.219.76:5173 \
REMOTE_API_BASE_URL=http://124.222.219.76:5173 \
REMOTE_E2E_USERNAME=admin REMOTE_E2E_PASSWORD='***' \
make remote-test
```

远程自动化固定使用 `http://124.222.219.76:5173`，不使用业务域名。域名可能受 DNS、备案、证书链路或本地网络策略影响；域名可用性由线上健康检查脚本单独验证，避免将网络问题误判为应用回归失败。

失败产物在 `test-results`，远程截图在 `test-artifacts/remote/runs`。新增功能必须优先补后端集成测试；关键页面再补 Playwright，避免只依靠脆弱的端到端测试。

导出改动至少验证：进度单调递增、完成后归档可读、不同 `taskId` 状态不覆盖、用户之间不可读取导出记录、SSE 断开后 GET 状态可以恢复。大纲改动至少验证：明确人物动作歌词不得规划为空镜、连续空镜受限、6 条及以上歌词至少使用 3 个场景、视觉母题不超过大纲声明次数。

本机 `make preflight` 的 Docker 阶段通过 `docker-compose.local-build.yml` 使用国内基础镜像代理；服务器测试环境部署不加载该文件。若本机镜像代理不可用，可通过 `LOCAL_NODE_BASE_IMAGE`、`LOCAL_NGINX_BASE_IMAGE` 临时覆盖，不要修改服务器部署配置。

系统人物改动至少验证：默认分类为“男 / 女 / 儿童”且均只读、系统人物对所有用户可见、儿童人物提示词保持儿童年龄与造型一致、原图和缩略图均为 TOS URL。新增系统图片使用 `scripts/sync-system-human-assets.py --asset CODE=/path/to/image` 上传，不得复制到项目目录。
