# 本机部署验收 — 2026-09-21

## 交付范围

- `admin-web`：Vue 3 管理前端；`public-api`：对外 API 与独立 Worker；`admin-api`：独立管理后端。
- 三个独立构建上下文和镜像；管理后端不导入公开 API，两个后端仅通过版本化数据库契约交换配置与任务状态。
- 对外包含统一 `/v1/videos`、`/v1/images`、LLM 非流式/SSE，以及原生兼容任务接口。
- MV 已加入可选网关路由、真实用户/Agent 归因、持久化路由标识、旧工单直连恢复与关闭网关时的防误重提保护。
- 本机服务已运行。**线上 MV 尚未切换，也没有修改生产服务器源码或部署现有 MV 新版本。**

## 验证结果

| 项目 | 结果 |
|---|---|
| 新服务 pytest | 32 项通过：鉴权、用户/调用方隔离、幂等冲突、模型参数转换、Base64、失败恢复、租约隔离、流式用量、请求大小与进程 Secret 隔离 |
| 原 MV `make preflight` | 通过：333 后端测试、224 前端测试、lint、迁移、前端构建和 Docker 构建 |
| 原 MV Playwright 用户侧 | 2 项通过、3 项按既有开关跳过 |
| 新管理台浏览器验收 | 登录、模型目录、创建 Agent Key、操作审计、退出通过；无 pageerror |
| 新服务镜像 | public、admin、admin-web 独立构建通过；两个后端容器应用导入通过 |
| PostgreSQL 多 Worker | 独立测试数据库、12 个并行领取者、模型上限 2，恰好取得 2 个不同任务，无超发，无真实模型调用 |
| 管理端独立重启 | 公开 API 连续 12 次健康检查均 200，公开 API 和 Worker PID 未变化 |
| 实际进程凭据隔离 | 管理/API Web 进程未注入供应商/TOS Secret，公开 API/Worker 未注入管理员 JWT Secret |
| 私密文件 | `.env`、`.secrets`、`.runtime` 已 Git 忽略；凭据文档权限 600，目录权限 700 |

原 MV 回归日志位于 `/tmp/model-service-mv-preflight.log` 和 `/tmp/model-service-mv-e2e.log`。新服务检查与构建日志位于 `/tmp/model-service-check.log`、`/tmp/model-service-docker-build.log`。本机运行证据保存在 `.runtime/`，不提交仓库。

## 真实最小验收

批次 `model-service-smoke-e484bc04335441e8b12b994cc2a4fe49`。全部通过 Agent 专属 Key，携带 `X-Agent-Name: code-agent`、同批次 Agent Run ID 和 Test Run ID。每类仅提交一次，未因下载失败重发生成。

| 类型 | 模型 | 结果与用量 |
|---|---|---|
| LLM | gpt-5.6-sol | HTTP 200；11 输入、5 输出、16 总 Token |
| 图片 | gpt-image-2.5-flare | 成功；1 张，原图与缩略图均归档 TOS；原始 usage：22 输入、3072 输出、3094 总 Token |
| 视频 | doubao-seedance-2.0-fast | 成功；5 秒请求，文件实测 1280×720、24fps、约 5.042 秒；原始 usage：108900 completion/total tokens |

图片工单：`job-ed5a19a00c4944c7a2b20bade093be43`；渠道任务：`task_Ln0SIfQum3pvLtgaTVj2NzBvHeHUItiv`。
视频工单：`job-7c8dca55c70440ec864b7c8bbedeb7f2`；渠道任务：`cgt-20260921222537-fgnzz`。

图片请求 1024×1024，但原图实测 1254×1254。该差异作为供应商行为保留，不将请求值当作实际尺寸。后续结果接口已补充实际媒体尺寸/技术元数据与请求规格；本次文件元数据和完整视频解码验证位于 `.runtime/video-metrics.json`。

首次归档遇到本机代理 Fake-IP DNS，下载器正确拦截保留地址；使用公网解析并固定连接 IP 后，通过管理恢复接口补回已有任务。视频还修复了本机缺少 imageio-ffmpeg 时使用系统 ffmpeg 的兼容路径。最终两个工单均 succeeded，原渠道 ID、原始用量与 Agent 归因保留，没有重新生成。

## 能力边界

- 32 项无费用测试包含十个英和视频模型的统一参数映射，但没有对新网关逐模型重新进行付费测试。此前 MV 的 5/5 成片结果不等同于新网关逐模型验收。
- Kling 默认禁用；HappyHorse、Vidu 继续遵循此前暂停决定，不新增付费测试或偷偷恢复入口。Flux-api 仅沿用历史暂停标记；现有文档未提供独立渠道标识，不能仅凭名称认定它是 BFL 的别名，也不能据此启用。PPIO 与 BFL（历史 FLUX 3）已从 MV 与本服务中移除支持，不是暂停或待迁移渠道；历史测试结果不代表当前支持。网关模式下暂停且未开放的渠道拒绝新调用，不旁路直连。
- RunningHub 工作流与提示词优化保留迁移兼容入口；本轮未做新的付费工作流验收。
- 本机实际运行使用独立 SQLite，生产使用独立 PostgreSQL；多 Worker 锁已在 PostgreSQL 验证，但并发极限和长时间负载仍需在目标生产环境压测。
- 本轮证明服务可以独立运行和支持迁移，不宣称线上 MV 已完成全量流量切换。上线前须配置生产数据库账号、HTTPS 入口和独立 Secret，并在旧工单结束前保留回滚所需配置。
- 原始用量可追溯；尚未配置财务费率的任务不能认定为免费。本服务不伪造人民币费用。

## 用户门户与积分扩展验收

新增独立 `user-web/`，本机 5181；用户注册、登录、API 文档、绑定 Key 的额度和逐任务积分可见。管理员新增「用户与积分」「生成方式费率」面板。费用使用渠道实际用量乘配置费率（用户确认的估算口径），1 积分 = ¥0.01；不内置未经核实的英和实际费率。

- 服务测试扩展至 36 项，包含用户越权、无用户创建 Key 路由、绑定不可转移、价格快照、不同生成方式匹配、缓存 Token 扣重、月度重置、临时增减与结算幂等。
- 隔离 PostgreSQL 钱包验收：12 个并发提交者在 20 积分、每任务预占 10 积分下仅受理 2 个；12 次结算回调只产生 2 条消费流水，余额为 19.6 积分。
- Playwright 使用隔离临时数据库和无供应商凭据的进程：注册→等待分配→管理员生成绑定 Key→临时 +20/-5→发布指定生成方式费率→插入明确标识为 fixture 的用量任务→用户查看 20 积分费用及 995 积分余额→用户文档核对同一费率。该任务未向渠道提交，**本轮真实模型调用数为 0**。
- 用户和管理页面截图已检查；用户 `portal-account.png`、`portal-docs.png` 与管理 `admin-pricing.png` 位于本机 `.runtime/`，为隔离测试数据。
- Alembic 0002 保留原工单、原 Key；已有系统 Key 默认保持原调用行为，明确显示额度控制未启用，管理员配置额度后启用。新 Key 默认受控。
- 实际使用前管理员需填写并发布各模型/生成方式费率；没有有效规则的受控 Key 不会进入付费调用。未取得必要用量的任务显示待核账并保留预占。

证据：`.runtime/portal-browser.json`、`.runtime/postgres-wallet-validation.json`；日志 `/tmp/portal-check.log`、`/tmp/portal-browser.log`、`/tmp/portal-postgres.log`、`/tmp/portal-mv-preflight.log`、`/tmp/portal-docker-build.log`。生产 MV 流量仍未切换。
