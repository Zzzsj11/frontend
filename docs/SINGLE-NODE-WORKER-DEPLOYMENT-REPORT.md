# 单机 Worker 测试部署报告

测试日期：2026-08-20；服务器：`120.24.38.200`；用途：单机服务拆分与部署要求验证，不作为高可用生产环境。

## 实际环境

- Ubuntu 24.04.4 LTS，4 vCPU，30 GiB 内存；数据盘配置4 GiB低优先级应急Swap（`vm.swappiness=10`）。
- 40 GB 系统盘；200 GB NVMe 数据盘已格式化为 ext4，并按 UUID 持久挂载到 `/var/lib/docker`。
- Docker 29.7.2、Compose 5.5.0；应用使用精确 Git SHA 的版本化镜像。
- PostgreSQL、Redis、API、Web、`worker-chat`、`worker-media`、`worker-export`、`worker-storyboard` 均为独立容器；数据库、Redis和后端端口不对公网开放。
- 健康检查、每分钟资源采样和每日 PostgreSQL 备份已安装为独立宿主机 cron。

## 验证结果

- 完整发布卡口通过：后端200项、前端150项，Alembic单head、前端构建、Docker构建全部成功。
- 远程 API 权限/隔离/软删除旅程和浏览器登录/项目旅程通过（公网安全组未放行时通过 SSH 隧道执行）。
- Worker隔离故障测试：停止导出Worker后工单保持 `queued`；重启API仍为 `queued`；恢复Worker后才领取并落终态。
- 分镜Worker真实故障隔离：停止 `worker-storyboard` 后提交ASS大纲，API返回202且工单保持 `queued`；恢复Worker后同一工单成功完成、任务进入 `generating` 并生成视觉圣经。完整输入、LLM调用和Token用量均关联该工单。
- Chat真实链路：API入队、`worker-chat`调用、Redis事件、PostgreSQL消息和用量落库成功；“只回复OK”约3秒，53 tokens。
- 图片真实链路：`gpt-image-2`生成、轮询、TOS原图/缩略图归档成功，约61秒。
- H3真实链路：T2VA、4秒、480P、静音视频生成和TOS归档成功；供应商耗时81秒，17 coins。
- 数据盘顺序测试：512 MiB同步写约2.56秒（约200 MiB/s），直读约3.40秒（约151 MiB/s）。
- PostgreSQL本机备份已迁入数据盘，并实际完成一次隔离数据库恢复验证；验证库用户记录可读且清理成功。每日备份、每周恢复验证均已进入cron。
- 空载CPU 98–100% idle、IO wait 0%；API约95 MiB，媒体Worker约95 MiB，Chat约85 MiB，导出Worker约78 MiB，PostgreSQL约49 MiB，Redis约4 MiB。
- 容器已设置CPU/内存上限；4核机器上导出Worker并发固定为1，H3模型池并发固定为2。

## 部署中发现并修复的问题

1. 首次部署脚本原先在PostgreSQL/Redis启动前运行green backend，导致DNS/迁移失败。已改为先启动并等待数据服务健康。
2. 新增Worker最初没有继承本机基础镜像代理覆盖，会直连docker.io。已补齐三个Worker的本机代理构建参数。
3. Worker原先无健康检查和资源上限。已增加进程健康检查，并在生产Compose限制CPU与内存。
4. 图片供应商usage嵌套于 `rawUsage`，原文虽保存但tokens汇总列为0。已兼容嵌套usage并补回归测试。
5. 健康脚本原先只检查四个基础容器。Worker模式下现会额外检查Chat、媒体、导出和分镜Worker。
6. ASS大纲、通用大纲和ASS场景段重试原先依赖API进程内协程，重启会丢失执行上下文。现已把完整输入快照与领域状态原子入库，由独立 `worker-storyboard` 执行；PostgreSQL保存进度/心跳，异常退出后最多自动重放3次。

## 需要运维配合或扩容的事项

### 必须处理

1. **测试入口使用 HTTP 80**：阿里云安全组已放行 TCP 80，前端通过 `http://120.24.38.200` 直接提供服务，不依赖域名。后端 `8000`、PostgreSQL 和 Redis 仍不直接暴露公网。
2. **SSH仍允许root和密码登录**：应先创建运维用户、安装密钥并验证，再关闭 `PasswordAuthentication` 和root远程登录。该操作需运维确认备用登录通道，避免锁机。
3. **缺少外部可恢复备份**：本机日志和备份已迁到200 GB数据盘，但仍与主机处于同一故障域，不满足灾难恢复。需要提供独立Bucket及生命周期策略，并实际演练恢复。

### 建议处理

1. **CPU**：外部模型调用不吃本机CPU，但FFmpeg、打包和导出会占满核心。当前4核只能安全承载单路重型导出；若希望同时导出2路，建议升级到8 vCPU；4路建议16 vCPU或拆独立导出节点。
2. **公网带宽/镜像源**：首次拉取约113 MB PostgreSQL层时速度明显波动，首次部署时间受公网下载影响。建议确认实例公网带宽至少20 Mbps，期望稳定构建/素材传输时使用50 Mbps以上，或提供内网镜像仓库。
3. **磁盘容量**：200 GB盘当前足够测试，但Docker镜像、数据库、Redis AOF和构建缓存都在同盘。需要80%告警和镜像保留策略；测试素材增长后建议至少500 GB。

## 仍未完成的架构治理

- 单机只有一个媒体Worker进程，模型池信号量可保证H3并发2；扩为多个Worker副本或K8s前，必须改为Redis Lua原子租约和心跳，否则每个副本都会各自放行2个H3任务。
- 定时任务当前是宿主机cron；迁移K8s时应分别改为CronJob，并为会修改业务数据的任务增加分布式防重入锁。
- PostgreSQL和Redis目前是单实例，适合测试环境，不具备节点级高可用。
