# 待发布工作审查（2026-09-22）

后续状态：此报告记录首次审查时的问题；代码与发布工具的后续修复见 [发布完善记录](release-fixes-2026-09-22.md)，不要将下文初始缺陷视为仍未修复。

结论：尚不适合直接全量部署。以下区分代码缺陷、已修复项与尚未执行的发布步骤。本轮只读核对生产状态；未部署、未提交代码、未调用真实模型。

## 版本与实际环境

- 本地 HEAD、远端 `origin/codex/single-node-workers`、线上部署标记均为 `06faad4c9dce612be90672bc307a001f7b03cb99`。待发布内容主要是未提交的工作区改动，包括整个未跟踪的 `model-service/`；不能仅按 HEAD 构建而期待包含这些修改。
- 线上 MV 主服务和 Worker 健康，MV 数据库 Alembic 为 `a6c9e2f4b801`。未部署独立模型服务，未创建 `model_service` 数据库。
- 本地独立服务数据库有 38 条有效供应商路由，但全部 `enabled=false`、`verification=pending`；模型启用数为 0。38 条路由均有估价规则，正式 `pricing_rules` 为 0。估价可展示不代表已开放生成或已配置实际扣费。

## 本轮已修复

1. 首次部署凭据格式：`model-service/scripts/bootstrap-mv.py::write_private` 原先给 `.env.migration` 的数据库 URL 加单引号，而 `docker run --env-file` 保留引号，迁移无法连接。现在区分 Docker 与 Compose 文件格式；测试验证 URL 解析、600 权限、不覆盖已有文件和 Compose 特殊字符。
2. 备用渠道错误拒绝：`model-service/public-api/gateway/main.py::enqueue` 原先先校验目录默认渠道凭据，再选择实际路由。默认国内渠道未配置、海外路由可用时仍返回 503。现在按选中的路由校验；测试覆盖仅海外渠道可用的情况，不请求真实供应商。
3. 7 项过时测试断言：后端 4 项未跟上“保存不确定提交记录、仅准备资产映射、不直接写库”的脚本行为；前端 3 项未模拟新增的模型目录读取。已更新并加强“不重复提交、不直接提交数据库、失败保留外部资产映射”的断言，保留真实的目录校验。
4. 修复阻断检查的格式问题，并纠正价格同步文档的“只读”表述：脚本不生成，但会写入本地数据库。

## 尚需完善，按优先级排序

### P1：ToAPIs 图片请求丢失用户尺寸和画质

位置：`model-service/public-api/gateway/main.py::create_image` 的 `toapis-image` 分支。

`size` 固定为 `1:1`，GPT 图片的 resolution/quality 固定为 `1K`/`high`。因此用户请求 `1024x1536`、`quality=medium` 仍被改成方形高画质请求，预估参数也可能与提交参数不一致。这是应用自己的转换问题，不是已证明的供应商输出偏差。

完成条件：按具体上游模型协议转换尺寸、分辨率与画质；不支持的规格在提交前明确返回 422；覆盖竖图、方图、不同画质及估价与实际提交参数一致性的 mock 测试。当前审查未改写未核实的供应商参数协议。

### P1：首次上线无法复现本地目录、路由和费率

位置：`model-service/scripts/migrate.sh`、`scripts/seed.py`、`scripts/setup-aggregation.py`、`scripts/publish-estimate-rates.py`。

迁移脚本仅执行 Alembic 和旧目录 seed，不执行选定的统一目录/路由配置。报价发布脚本还硬编码读取开发 `.env` 与 `.runtime/comparison-20260922`，不能直接视为独立生产发布工具。只部署镜像和迁移不会得到本地的 38 条路由与报价配置。

完成条件：准备不含密钥的版本化配置产物与幂等导入入口；显式选择目标环境；只启用有验证证据的路由，保留关闭状态；分别发布估价和正式扣费规则；用空 PostgreSQL 数据库验收。不要复制开发数据库或将 fixture 费率带入生产。海外业务凭据需安全注入 Worker，不能只依赖旧 MV 配置自动取得新凭据。

### P2：独立 Worker 没有停机收尾

位置：`model-service/public-api/gateway/queue.py::main`。

主循环无 SIGTERM/SIGINT 排空处理。Compose 配置的停止宽限时间本身不会让 Python 停止领取并等待在途提交；重启时可能中断供应商提交，过期租约随后转入人工对账。现有机制防止盲目重发，但会增加发布引起的人工恢复。

完成条件：收到停止信号后停止领取，限时等待提交/保存任务 ID，取消后台余额采集；超时保留可恢复或待核账状态，并验证不重复提交。

### P1 发布步骤：头肩照提示词和系统资产尚需正式切换

`d6f2a8c1e903` 只升级模板元数据，`seed_prompts` 不覆盖已有发布正文。只发布新前端和迁移，不能保证存量数据库的生成提示词切到新规则。

按 `docs/提示词运营闭环演示手册.md` 第 4.2 节合并并发布三个模板、无费用检查最终提示词。系统资产准备脚本现在只输出备份和变更映射，必须审核映射后通过新的 Alembic 数据迁移执行；同时同步全新环境种子，不能把脚本运行成功当作资产已入库。此项是尚需执行的发布工作，不应在代码审查中覆盖运营正文或触发批量付费出图。

## 验证记录

- 独立服务 `make -C model-service check`：80 项 pytest、lint、格式及两个前端构建通过。
- 主项目 `make preflight-lite`：修复后完整通过，后端 484 passed / 1 xfailed、覆盖率 69.54%，前端 228 passed，lint、格式、Alembic 单 head/升级检查和前端构建通过。初次发现的 4 项后端旧断言及 3 项前端旧 mock 失败均已消除。
- 定向脚本测试 64 项、ScriptEditor 测试 5 项通过。
- Playwright：ASS 分镜和头肩照 6 项通过；使用已核实来自本工作区的本机 Vite（4173），浏览器模拟并拦截业务请求。
- 独立门户/后台隔离浏览器验收通过：注册、管理员绑定 Key、额度调整、费率发布、账单和文档；临时数据库和无供应商凭据进程，模型调用为 0。
- 未执行本版本 Docker 完整发布构建或线上流量切换。以上检查不等于真实模型质量验收。

日志：`/tmp/release-audit-service-check.log`、`/tmp/release-audit-mv-recheck.log`、`/tmp/release-audit-e2e.log`、`/tmp/release-audit-portal.log`。日志为本机临时证据，不随源码提交。
