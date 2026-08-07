# Full Journey Test Asset

本目录保存 ASS 与通用分镜真实全链路测试资产：

- `inputs/`：稳定、可复现的 ASS 输入夹具。
- `screenshots/`：2026-08-07 首次验收通过的 24 张基准截图，不应被日常复跑覆盖。
- `runs/`：后续运行的临时产物目录，默认被 Git 忽略；确认有长期价值后再人工选取为新基准。

测试实现位于 `e2e/full-real-generation.spec.ts`，使用说明见 [`docs/REAL_FRONTEND_E2E_GUIDE.md`](../../docs/REAL_FRONTEND_E2E_GUIDE.md)，首次验收结果见 [`docs/FULL_FRONTEND_AUTOMATION_REPORT_2026-08-07.md`](../../docs/FULL_FRONTEND_AUTOMATION_REPORT_2026-08-07.md)。
