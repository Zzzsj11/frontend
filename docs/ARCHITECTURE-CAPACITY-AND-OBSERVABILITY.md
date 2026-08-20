# 单机架构容量、全链路旅程与可观测性基线

更新时间：2026-08-20。测试环境：`120.24.38.200`，4 vCPU、30 GiB RAM、4 GiB swap，系统盘 40 GiB，Docker 数据盘 196 GiB。

## 数据流与故障边界

1. 用户经 Nginx/Vue 调用 FastAPI；API 只做鉴权、配额、校验和持久化提交。
2. PostgreSQL 的 `generation_jobs` 是任务真相源。Redis 只负责唤醒、进度缓存和事件加速；Redis 故障不会丢任务。
3. Storyboard、Chat、Media、Export worker 使用数据库抢占与心跳，分别隔离 LLM、模型调用和 FFmpeg 长任务。
4. 模型输入、输出原文件与缩略图进入 TOS；数据库保存 URL、状态、请求快照和模型用量。
5. 前端通过轮询/SSE 读取持久状态。worker 或 API 重启后，未完成工单可以最多重放 3 次。

### 覆盖全部组件的验收旅程

使用 dev01 登录 → 创建项目 → 上传 ASS → 匹配歌曲情感库 → 选择系统/私有人物 → 提交 ASS 大纲 → 重试一个场景段 → 逐镜头生成提示词 → 同时提交图片、Seedance 与 H3 视频 → 发起通用 Chat → 导出成片 → 管理后台查看模型用量、队列、资源与告警。该旅程依次触发 Nginx、前端、API、PostgreSQL、Redis、四类 worker、Chat/Image/Video provider、TOS、FFmpeg、SSE/轮询和监控采集。

边界注入：重复提交（幂等键）、Redis 中断（数据库轮询兜底）、provider 429/超时（保留工单并重试）、worker 被杀（心跳超时后重放）、TOS 上传失败（任务失败且保留输入）、Export 与视频同时运行（CPU/iowait 监测）、系统盘/数据盘接近阈值、网络出站接近月配额、数据库连接耗尽。验收要求是不丢单、不越权、不重复扣量，失败状态可见且可重试。

## 容量口径与实测

“可提交量”由 PostgreSQL 队列容量决定；“执行并发”由 worker 和 provider 槽决定。不能把排队任务数当作同时调用数，也不能把 Docker memory limit 当作已占用内存。

| 环节 | 当前执行上限 | 线上观测 | 单用户安全建议 |
|---|---:|---:|---:|
| ASS 大纲/分段重试 | Storyboard 工单 2 | plan 平均 51.2s；segment 调用约 32–79s，极端 163s | 同时 2 个 ASS 工单；单工单 4–5 段并行时会形成总计 8–10 个 LLM 峰值请求 |
| 通用大纲 | Storyboard 工单 2 | 1 次实测 94.4s；对比任务样本 P95 311.9s | 同时 2 个；超出排队 |
| 单镜头提示词 | API 内 semaphore 4 | 17 次，平均 11.6s，P95 14.4s | 同时 4 镜头；这是仍在 API 内的主要隔离缺口 |
| 图片 | Media worker 总槽 4 | 1 次 83.4s | 与视频共享 4 槽，持续压测后再拆独立池 |
| 视频 | Media 4；H3 provider 2 | 5 次平均 186.0s，P95 236.6s | H3 同时 2；其他模型受共享 4 槽及自身 provider 限制 |
| Chat | 2 | 1 次 2.0s | 同时 2 |
| 导出 | 1 | 当前成功样本不足 | 同时 1，避免 FFmpeg 抢占 4 核 CPU 与数据盘 I/O |

ASS 的“2 个工单”不等于只有 2 次 LLM 调用：大纲规划后，场景段使用 `asyncio.gather`。长 ASS 每工单最多 5 段，因此两个工单可能瞬时发起约 10 个分段调用。应再增加 provider 级 LLM semaphore（建议先设 6）才可形成严格峰值上限。

## 当前服务器是否浪费

采样时宿主机仅使用约 1.5/30 GiB，8 个容器合计约 545 MiB；因此“30 GiB 内存正在被浪费”在空闲时成立。Docker 配置中的 23.5 GiB 是上限而非预留，不能据此声称内存已紧张。

但 4 vCPU 是现实的共享瓶颈：单个导出可占满 FFmpeg，前端构建、数据库、API 和全部 worker 仍共享这 4 核；40 GiB 系统盘也需避免日志/临时文件回流。模型生成主要受外部 provider 并发和网络等待限制，盲目减内存不会提升吞吐。建议先连续采集 14 天 P95/P99，再决定把内存降到 16 GiB；CPU 暂不低于 4 核，若导出期间 API P95 或 iowait 告警，应增至 8 核或拆出 Export 节点。

## 新监控基线

- 30 秒 systemd timer 采集；cron 保留一分钟降级方案。
- 宿主机：CPU、load、iowait、内存、swap、网卡吞吐、磁盘吞吐与 IOPS。
- 文件系统：系统盘、Docker 数据盘、数据目录容量和 inode。
- 容器：CPU、内存、PIDs、网络与块设备 I/O。
- 业务：各 `generation_jobs` 类型 queued/running、最久等待、近一小时成功/失败、平均/P95；LLM 次数、失败、tokens、平均/P95。
- 告警：CPU 80/95%、内存 80/90%、磁盘 75/90%、swap 50/80%、iowait 15/30%、月出站 70/95%。

资源调整采用 14 天滚动证据：CPU、内存和磁盘按 P95 乘 1.5 安全系数；队列最久等待超过目标时优先调整对应 worker/provider 槽，而不是整体扩容。H3 必须保持 2；Export 扩容前先确认 CPU 和 I/O 余量。

## 后续卡口

1. 将 `storyboard_line` 从 API 同步执行迁入 Storyboard worker，避免四个慢请求占住唯一 API 进程。
2. 为 LLM 增加全局与 provider 级 semaphore，限制 ASS 内部分段扇出。
3. 连续 14 天收集数据后形成容量复盘；样本少于 30 次的 P95 仅作观察值。
4. 进入 K8s 时按 worker kind 拆 Deployment，并以队列等待和 provider 配额驱动扩缩容；PostgreSQL 仍是持久队列真相源。
