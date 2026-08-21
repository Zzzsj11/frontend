# 三个全量分镜任务并发压测与上线容量评估

> 测试日期：2026-08-21  
> 测试环境：本机 Docker Compose，`JOB_EXECUTION_MODE=worker`，12 vCPU / 7.75 GiB Docker VM  
> 数据口径：PostgreSQL 工单与资产、Token 账本、Worker 心跳、Docker 资源采样、供应商余额与错误响应

## 1. 最终结论

1. 三个真实全量子任务最终全部完成：**47/47 条提示词、47/47 张场景图、47/47 条 Seedance 2.0 视频**，没有用 mock 替代模型调用。
2. 媒体执行已拆成独立的 `worker-image` 与 `worker-media`（仅视频），默认并发分别为 **32 + 32**。长视频不再占住图片槽，避免“先发视频的项目饿死其他项目图片”。
3. 扩容复测中视频在途峰值达到 **20**，供应商 **429=0、超时=0**。这证明当前 Key 和供应商链路可以承受至少 20 路视频实测并发，但不能据此直接承诺 32 路持续 SLA。
4. 媒体 Worker 的 burst 进程实测约 **92–102 MiB/个**；即使图片、视频各一个 32 并发进程，内存仍不是当前瓶颈。主要容量边界仍是供应商额度、上游耗时和队列等待。
5. 测试中曾因旧 Key 额度耗尽中断，换入新 Key 后按“单镜探针 → 缺口补跑”恢复，最终无重复覆盖已有成功资产。正式上线必须配置 Key 余量告警。

## 2. 三任务最终对账

| 任务          | 子任务 ID                               | 目标配置                              |    提示词 |    场景图 |      视频 | 最终状态 |
| ------------- | --------------------------------------- | ------------------------------------- | --------: | --------: | --------: | -------- |
| ASS《七里香》 | `task-9a458d21887548bba93910fba7b4d28f` | 13 镜，16:9，480p，Seedance 2.0       |     13/13 |     13/13 |     13/13 | 全量完成 |
| 通用 MV A     | `task-fae5aa98836d41b6b979f3cd39e9aa8d` | 17 镜，210s，16:9，480p，Seedance 2.0 |     17/17 |     17/17 |     17/17 | 全量完成 |
| 通用 MV B     | `task-9905e89b152f439a85e8fa45454bf1f7` | 17 镜，210s，16:9，480p，Seedance 2.0 |     17/17 |     17/17 |     17/17 | 全量完成 |
| **合计**      | 3 个真实子任务                          | 47 镜                                 | **47/47** | **47/47** | **47/47** | **100%** |

数据库最终资产核验为 47 条 `storyboard_lines`、47 条有效 `scene_assets`、47 条有效 `shot_assets`。历史失败工单保留用于审计，不会伪装成成功，也不影响当前资产 47/47 的事实口径。

### 2.1 通用 MV A 恢复明细

通用 A 在旧 Key 耗尽前已有 9 条视频。新 Key 生效后只补 8 个缺失镜头，未重复生成已有 9 条：

- 真人合规高风险镜先做单镜探针：354 秒，一次成功。
- 其余 7 个工单端到端耗时（包含公平排队）：158、342、458、546、740、738、671 秒。
- 8 个恢复工单全部 `attempt=1`；429=0、超时=0、新失败=0。
- 人物镜请求不传数字人头像；6 个人物镜启用了“真人参考拒绝时自动 T2V”能力。本轮新 Key 接受了场景首帧，实际 fallback 触发 0 次。
- 恢复新增视频用量 8 次、967,568；通用 A 全任务成功视频用量 17 次、2,056,082。

## 3. 最终 Worker 架构

```text
用户/API
  └─ PostgreSQL generation_jobs（事实源）+ Redis（唤醒）
       ├─ worker-storyboard：大纲/逐镜提示词，concurrency=2
       ├─ worker-image：仅图片，concurrency=32
       ├─ worker-media：仅视频，concurrency=32
       ├─ worker-chat：concurrency=2
       └─ worker-export：concurrency=1
```

关键变化：

- 图片和视频拆池，视频轮询不会占用图片槽。
- 跨用户/子任务按当前在途数公平领取，单一大任务不再独占全部媒体槽。
- PostgreSQL 租约、Worker 心跳和 graceful drain 保证部署时不丢工单；已有 `provider_task_id` 的任务只恢复轮询，不重复提交供应商。
- 通用人物镜不发送数字人头像；若人物场景首帧被判真人参考，只对该类镜头降级纯文本 T2V。

架构图见 [2026-08-21-generation-bottleneck.svg](2026-08-21-generation-bottleneck.svg)。HTML 报告内嵌同一 SVG，不依赖外部文件。

## 4. 扩容复测数据

| 指标                   |         最终实测 |
| ---------------------- | ---------------: |
| 图片 Worker 配置       |               32 |
| 视频 Worker 配置       |               32 |
| 视频在途峰值           |               20 |
| 供应商 429             |                0 |
| 供应商超时             |                0 |
| 媒体 Worker burst 内存 | 约 92–102 MiB/个 |
| 三任务最终资产         |  47 图 + 47 视频 |

20 路在途是本轮真实观测峰值，不等同于 32 路持续压测。上线后应继续记录 14 天 P50/P95/P99、失败率、Key 消耗和最老排队时间，再决定是否把视频并发从 32 提升到 64/96。

## 5. 资源判断与容量边界

- 本轮 32+32 是异步 I/O 并发，不是 64 个持续满 CPU 的生成线程；大部分时间在等待远端供应商。
- burst 进程 92–102 MiB，说明 8 GiB 级主机仍有明显内存余量；生产仍应设置 requests/limits，避免异常下载或归档放大内存。
- 20 视频在途下没有 429/超时，当前上游并发健康；若 429 率超过 1%，必须降低并发，不应继续扩 Worker。
- Key 额度曾是 P0 硬阻塞。建议在 remaining 20%、10%、0 设置告警，并将额度耗尽识别为确定性拒绝，不进入“供应商结果不确定”的人工核对分支。
- `project_tasks.status=ready` 只代表脚本提示词已就绪，不代表媒体全量完成；运营与监控应使用派生 `mediaProgress/mediaStatus`。

建议告警线：

| 指标                           | 告警/动作                          |
| ------------------------------ | ---------------------------------- |
| `video queued` 最老等待 > 300s | 检查供应商耗时、Key 与在途分布     |
| 视频在途持续 32/32             | 先观察 429/超时，再决定是否扩容    |
| 429 或供应商限流率 > 1%        | 立即降并发，禁止横向扩 Worker      |
| 单 Worker 内存持续 > 512 MiB   | 检查下载、TOS multipart 与结果聚合 |
| Key remaining < 20% / 10% / 0  | 分级告警 / 切 Key / 停止新媒体任务 |

## 6. 本轮发现并修复的问题

| 优先级 | 问题                        | 处理与复测                                               |
| ------ | --------------------------- | -------------------------------------------------------- |
| P0     | 旧媒体 Key 额度耗尽         | 更换新 Key，先单镜探针再补缺口，最终 47/47；失败历史保留 |
| P0     | 空闲 Worker 忙循环          | Redis 阻塞监听 + timeout，消除空载高 CPU                 |
| P1     | 图片/视频共享槽导致图片饥饿 | 拆分 `worker-image` 与视频 `worker-media`，各 32 并发    |
| P1     | 单任务占满媒体槽            | 按子任务当前在途数公平领取；扩容复测视频峰值 20          |
| P1     | 通用人物场景首帧真人误判    | 不传人物头像；特定合规错误自动移除参考图降级 T2V         |
| P1     | 确定性额度拒绝误标人工核对  | 明确拒绝直接失败；只有响应不确定且无 taskId 才人工核对   |
| P1     | 部署重建产生 502 窗口       | frontend 先更新、green backend 接流量、Worker 逐类 drain |
| P1     | 通用 4/13 镜头配额漂移      | 严格校验空镜/人物镜数量，不符触发 LLM 重试               |
| P1     | ASS 同一大场景出现二次换装  | 增加语义校验，同场景服装连续、跨大场景换装               |

## 7. 正式部署配置与命令

生产 `.env.production`：

```dotenv
JOB_EXECUTION_MODE=worker
COMPOSE_PROFILES=workers
IMAGE_WORKER_CONCURRENCY=32
VIDEO_WORKER_CONCURRENCY=32
EXPORT_WORKER_CONCURRENCY=1
CHAT_WORKER_CONCURRENCY=2
STORYBOARD_WORKER_CONCURRENCY=2
WORKER_STALE_SECONDS=180
```

正式部署只使用版本化镜像和部署脚本。服务器代码必须已经是目标提交且工作区干净，然后执行：

```bash
cd /opt/mv-agent-frontend
git status --short
git rev-parse HEAD
chmod +x scripts/deploy-local-images.sh scripts/deploy.sh
DEPLOY_ENV=production ./scripts/deploy-local-images.sh
```

该命令按当前完整 Git SHA 构建版本化镜像并调用正式部署流程。部署流程先启 frontend，再启动 green backend 接流量并切换正式 backend，最后按 `worker-chat → worker-storyboard → worker-image → worker-media → worker-export` 顺序逐类 graceful drain/recreate，避免供应商无幂等创建时重复计费。

若版本化镜像已由镜像仓库提供，等价的正式入口为：

```bash
DEPLOY_ENV=production ./scripts/deploy.sh <version>
```

部署完成后必须执行线上健康检查，并确认五类 Worker 均为目标版本且 healthy。

## 8. 证据来源与边界

| 事实                     | 来源                                              |
| ------------------------ | ------------------------------------------------- |
| 最终 47/47/47            | `storyboard_lines`、`scene_assets`、`shot_assets` |
| 工单状态、排队与执行时间 | `generation_jobs`                                 |
| 模型用量                 | `token_usage_records`、`llm_call_logs`            |
| 在途峰值与 Worker 状态   | `worker_instances`、容量采样                      |
| CPU/内存                 | `docker stats --no-stream` 连续采样               |
| 429/超时                 | 工单错误、供应商响应与 Worker 日志                |
| Key 余量                 | 业务余额接口，报告不记录明文 Key                  |

结论边界：本轮证明了 20 路视频在途无 429/超时、32+32 架构可稳定完成三个全量项目；它不是 32 路视频持续稳态或多机集群 SLA。生产并发继续提升必须以滚动观测数据和供应商合同上限为准。
