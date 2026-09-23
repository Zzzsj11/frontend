# 技术架构

计价预检以模型能力中的 `billing` 为单一产品配置：声明渠道、每秒粗估价、是否检查余额和是否排除。RunningHub 测试通道不计费且不检查英和余额；最终对账仍以版本化 `video_pricing_rules` 和供应商真实用量为财务事实。

视频归档完成后，媒体 Worker 在受控并发下使用 ffprobe 读取 TOS 文件，将请求档位、供应商档位、实际宽高、FPS、编码、真实时长和文件大小固化到任务结果与 `shot_assets`。历史素材可用 `backend/scripts/backfill_video_metadata.py` 幂等补齐。管理后台历史重算通过 `billing_reconcile` 持久化 Worker 工单执行，每批 500 条，支持进度、重复请求复用和中断重放。

项目是 Vue 3 + TypeScript 前端、FastAPI + SQLAlchemy 后端、PostgreSQL 持久化、Redis 缓存/任务状态、TOS 媒体存储的 MV AI 生产平台。Nginx 托管前端并代理 `/api`。

主要领域：认证和多用户隔离、项目/子项目、ASS 与通用分镜、系统及私有人物、场景/视频/音频资产、模型注册、生成任务、Token 用量、错误日志、管理后台。

生成链路：前端提交任务，后端校验用户和模型，创建 `generation_jobs`，调用供应商，原媒体及缩略图导入 TOS，资产记录入 PostgreSQL，用量写入账本。列表只加载缩略图，用户交互时才加载原图或视频。

统一供应商配置通过 Docker Secret `provider_config` 挂载。检测到其中的 `AIGC_TOKEN` 时，文本模型 Token、聊天 API 地址和默认模型作为同一个配置组生效，优先于遗留的 `LLM_*` 环境变量，避免共享 Token 被误发往其他供应商；只有未配置统一供应商 Secret 时才启用独立 `LLM_*` 配置。

模型调用可整体切换到独立模型服务（`model-service/`，对外 API + 管理 API + 双前端，独立数据库与部署）：配置 `MODEL_GATEWAY_URL` 与 `MODEL_GATEWAY_API_KEY` 后，`backend/app/model_gateway.py` 将 LLM、图片、视频、Kling/RunningHub 及提示词优化调用路由到该服务；留空则保持现有直连供应商行为。迁移按渠道灰度——`MIGRATED_CHANNELS` 已承接 yinghe、yseeai、toapis、runninghub 与两个提示词优化渠道；PPIO 与 BFL 已移除支持，不属于待迁移渠道，也不允许旁路直连。网关请求携带内部 Key、`X-User-Id` 用户归因与 Agent 三头；工单上下文内 `Idempotency-Key` 由工单 ID 派生稳定键（媒体创建另由 providers 以 `{job_id}:{variant}` 覆盖），Worker 崩溃重放由网关按 (client, user, key) 去重，不会重复创建上游任务。仍受支持渠道的旧直连工单恢复时按原来源直连查询；已退役渠道仅保留历史记录，不恢复调用。网关工单在 `MODEL_GATEWAY_URL` 缺失时禁止静默回退，避免来源丢失。model-service 自身架构、API 协议与部署见 `model-service/README.md` 及 `model-service/docs/`。

ASS 与定制通用分镜默认使用 `OUTLINE_PROTOCOL_VERSION=v2` 的紧凑大纲协议。定制通用一次输出全片导演决策骨架；ASS 固定为一次大场景规划加一次全曲镜头骨架，不再按大场景并行重复提交人物长描述。后续逐镜提示词仍消费兼容的标准大纲字段，因此无需改动下游图片、视频和导出链路。紧急回滚可将该变量设为 `v1`，恢复旧提示词和旧调用编排。

Chat对话、媒体生成、素材导出、ASS/通用大纲、逐镜提示词和ASS场景段重试支持两种执行模式：默认 `inline` 保持本地单进程行为；服务器设置 `JOB_EXECUTION_MODE=worker` 后，API只在同一事务中写领域状态和 `generation_jobs`，`worker-chat`、`worker-image`、`worker-media`（仅视频）、`worker-export` 与 `worker-storyboard` 使用 PostgreSQL `FOR UPDATE SKIP LOCKED` 领取。图片和视频使用独立执行池，避免长视频轮询占满图片槽；单机默认分别为32并发。分镜工单的完整人物、上下文、大纲和重试快照保存在 `generation_jobs.request`，进度与心跳同时落PostgreSQL；Worker中断后最多自动重放3次。Redis承担低延迟 Worker 唤醒、Chat跨进程取消、热状态与事件，短暂不可用不会丢失数据库工单。模型注册中心的 `executionPool/executionConcurrency` 同时由进程内信号量和 Redis 原子租约约束，多 Worker 或多节点共享同一并发上限；Redis不可用时降级为进程内限制。视频生成按供应商和模型拆分执行池：英和提供 SD2.0 与 MiniMax-H3 直连，RunningHub H3 保留为并发 2 的测试通道。人物入库或换图时，TOS 原图注册为英合虚拟人物资产；生成英合 Seedance 视频时使用 `asset_avatar_url` 中的 `asset://`，原始 TOS URL 始终保留用于展示和对账。各 H3 通道共享提示词编译与参考素材约束，但分别适配创建、查询、恢复和结果解析协议。顶部余额接口仅查询英和商户与子账号 Key；批量任务按模型 `billing` 声明决定估价和余额预检，不跨渠道兜底。独立 model-service 的管理余额采集支持 yinghe、yseeai、toapis，不等同于 MV 生成预检范围。新模型接入现状和剩余清单见 `TODO_MODEL_EXPANSION.md`。

余额展示查询使用 60 秒服务端缓存，前端仅在页面可见时每 5 分钟按需刷新；用户手动点击可请求实时刷新，但服务端会合并 5 秒内的并发强刷。生成确认弹窗读取短时缓存，真正提交时仅对任务涉及的渠道执行最终余额校验，因此降频不削弱任务提交卡口。

ASS 与定制通用的逐镜提示词采用服务端批量受理：页面一次提交最多100条，Worker默认64并发执行，浏览器不再以4条长轮询限制吞吐。每条模型请求只携带当前场景、当前镜头、前后两镜、局部歌词和实际出演人物，不再重复发送全片镜头数组；模型等待期间释放数据库连接，只在读取和结果回填时开启短事务。随机通用创建完成后通过视频批量端点一次持久化全部纯文本视频工单，随后由 Seedance 模型池的170并发上限统一调度。

单机 Worker 可靠性以 PostgreSQL 租约为准：`worker_instances` 记录进程版本、`running/draining/drained` 状态、心跳与在途任务数；`generation_jobs` 记录 `worker_id/claimed_at/heartbeat_at/lease_expires_at/phase/provider_submitted_at`。SIGTERM 后 Worker 先持久化 `draining` 并停止领取，现有任务继续心跳直至结束。只有租约过期的任务可被恢复；已有 `provider_task_id` 的媒体任务只恢复轮询。gpt-image-2 图片和 Seedance 视频在供应商创建请求的 `Idempotency-Key` Header 中发送由本地工单 ID 派生的稳定键，并在发请求前持久化；处于 `submitting_provider` 且没有 taskId 的崩溃任务可以用原键安全重放，不会重复创建。其他未声明幂等能力的供应商仍转为 `manual_review`，禁止自动重提。

数据库结构只由 Alembic 管理，应用启动仅验证连接；测试用 SQLite 可在隔离数据库中由 metadata 建表。认证采用短 access token、数据库 refresh token 与 `users.auth_version`，改密可即时撤销历史会话。

退役迁移要求：MV 历史 Alembic 文件保留以防断链，新增前向迁移软删除 PPIO/BFL 存量 provider/model/pricing 行；人物专属历史列暂时保留供滚动切换中的旧进程读取，新代码不再映射或使用，物理清理须另行前向迁移。model-service 同样需要在独立数据库以前向迁移退役旧渠道行及关联配置。代码与 seed 移除不等于存量数据库已清理，上线须分别核验迁移结果。历史财务工单、费用、用量与媒体均保留，不删除、不重发生成；退役不影响其他保留渠道。部署核验见 `model-service/docs/DEPLOYMENT.md`。

素材导出使用 `material_exports` 保存用户、子项目、进度阶段、字节数和 TOS 归档地址，并关联 `generation_jobs`。每次导出拥有独立 ID、临时目录和 TOS 对象键；不同子项目可并行执行且前端状态按 `taskId` 隔离。浏览器通过带 Access Token 的流式 Fetch 订阅 SSE，断线或刷新后以 PostgreSQL 状态恢复，SSE 只承担实时通知而不是事实存储。

ASS 大纲采用三层提示词结构：系统安全与技术约束、歌曲级视觉圣经、当前镜头执行契约。视觉圣经统一人物面部身份、时间、天气和色彩，并在 `scenePlan.wardrobeByCharacter` 中为每个大场景规划独立服装；同一大场景内服装连续，切换大场景时换装。每镜契约固定人物、地点、动作、情绪重点、服装和镜头目的。人物服装决策顺序固定为“用户明确要求 > 季节 > 曲风 > 歌词与叙事 > 场景和动作 > 光线、色彩与视觉风格”，人物镜必须逐字携带大纲服装，结构校验不通过时自动修复。选定人物的新身份图为 1024×1536 白 T 灰底正面头肩大头照，只锁定五官、脸型、肤色、年龄感和发型，不从头肩照推断全身比例，保留儿童和卡通身份；无参考图按身份描述生成，有图仅提交一张身份原图，不再使用系统人物版式模板。最终视频提示词编译器会再次声明忽略白 T、灰背景、历史卡的浅灰下装与多视图排版，并为 H3 将对应图片标记为 `identity_only`。私有旧横版卡保留兼容裁切，用户手动重生成后切换为竖版；系统人物经受控脚本单独迁移。未选择人物的通用 MV 仍由视频模型逐镜自由生成人物与服装。

人物剧情镜头默认允许发型按场景与动作自然调整，以及合理的路人、观众和陪衬人物；身份参考只锁定主角五官、脸型、肤色和年龄感，空镜仍禁止人物。人物库头肩照本身的发型保留规则不变。逐镜提示词生成（含随机通用）完成时，服务端自动追加人物镜“人物表情自然不僵硬，视频整体画质类似实拍视频”、空镜“视频整体画质类似实拍视频”；视频提交端按分镜类型幂等补齐，并覆盖 H3 编译后的最终工单请求。人物人数标签描述主角人数，绑定角色 ID 不限制背景人物。

`a8c4e2f6b109` 前向迁移发布上述剧情规则：精确替换已知旧文案，保留无关运营定制、草稿和历史版本，并使用全部版本的最大版本号加一。部署后需等待 API/Worker 的提示词缓存 TTL（60 秒）失效或正常重启。历史大纲、提示词和已生成媒体不回写；重新生成提示词应用新规则，旧提示词直接生成视频会补齐画质要求但保留用户正文。迁移不修改人物身份照模板。
