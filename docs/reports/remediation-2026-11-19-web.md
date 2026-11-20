# 工作区与管理前端修复验收

日期为 2026-11-19。以下编号对应 [深度审查报告](deep-code-review-2026-11-18.html)。本轮使用本机 Chromium、模拟供应商响应，以及隔离的 SQLite 和 fakeredis。真实模型调用与部署次数均为零。

| 编号 | 修复 | 验证 |
| --- | --- | --- |
| WEB-01 | 保存音轨只发送显隐和偏移。后端加锁后合并字段。兼容旧客户端的任务 PATCH 也保留已有配置。 | 在含大纲、情绪和默认视频模型的任务上依次用两个接口保存音轨，重新读取后原配置逐项相同。[实现](../../backend/app/domain.py) · [接口用例](../../backend/tests/test_workspace_integrity.py) |
| WEB-02 | 会话切换使旧请求失效。列表和详情写入前检查会话与工作区所有者，旧请求的异常和 finally 也受保护。创意分镜写入期间切换子项目时，已保存的旧镜头也不会插入当前工作区或继续派发视频。 | 人为延迟前一用户的项目和分类，后一用户先完成加载，再释放旧响应，侧栏与分类保留后一用户数据。[工作区](../../src/stores/project/workspace.ts) · [回归](../../tests/user/workspaceIntegrity.test.ts) |
| WEB-03 | 写请求、SSE 和认证刷新都绑定发起会话。只有同一会话可重放 401 或释放共享刷新请求，即使调用方传入自己的取消信号也可在登出时中止。 | 模拟迟到的 401 和刷新成功响应，验证旧写请求只发送一次、旧连接关闭、新用户并发请求共用自己的刷新。[客户端](../../src/api/client.ts) · [回归](../../tests/user/apiClient.test.ts) |
| WEB-04 | 首查失败进入按任务计算的退避，前台从 3 秒逐步延长至 30 秒，并遵守服务端 Retry-After 和任务截止时间。 | 模拟首查 429 和 8 秒等待窗口，下一次查询发生在窗口结束时。另验证相隔 1 毫秒注册的两项任务只发一批首查，网络错误后也可恢复。[调度器](../../src/utils/generationPoller.ts) · [回归](../../tests/user/generationPoller.test.ts) |
| WEB-05 | 变更阵容仅提交一次。服务端在同一事务内更新阵容顺序，批量软删除确实移出的逐镜演员关系。 | 用三个不同演员组合的镜头删除同一人，并重复提交，同步结果只影响出演过该演员的镜头。[客户端](../../src/stores/project/characters.ts) · [服务端与接口用例](../../backend/tests/test_workspace_integrity.py) |
| WEB-06 | 分镜的歌词、场景、视频提示词、视频参数和创意提示词合并为一次 PATCH。成功后关窗，出错保留草稿。 | 挂载真实弹窗，首次提交失败后仍可见。确认每次点击只发一个完整请求，重试成功才关闭。[弹窗](../../src/components/ShotDetailModal.vue) · [回归](../../tests/user/workspaceIntegrity.test.ts) |
| WEB-07 | 随机批次在明确拒绝时释放每镜生成状态并保留错误。超时或受理状态不明时仍只查询原工单。 | 模拟余额不足返回 402，两镜均可重试且活动工单查询次数为零。[处理](../../src/stores/project/creation.ts) · [回归](../../tests/user/workspaceIntegrity.test.ts) |
| WEB-08 | 创意优化处于排队或运行时锁定提交，轮询只更新同一任务。同一用户意图使用稳定请求 ID，服务端对重放返回原记录，配额与入队同事务。 | 组件回归断言排队后重复点击只提交一次。接口重放返回相同 ID，仅扣一次配额、派发一次，复用 ID 更改参数返回 409。[组件](../../src/components/CreativeVideoModal.vue) · [接口回归](../../backend/tests/test_workspace_integrity.py) |
| WEB-09 | 人物建档绑定当前用户已完成的图片工单和原图。同工单重复恢复返回同一人物，分类创建也复用已有名称。查询暂时中断保留草稿。 | 两次建档只注册一次。删除后再次恢复返回 410。浏览器验收覆盖等待中刷新、恢复到原工单与最终入库。[建档](../../backend/app/domain.py) · [接口回归](../../backend/tests/test_workspace_integrity.py) · [浏览器用例](../../e2e/user/digital-human-headshot.spec.ts) |
| WEB-10 | 空工作区禁用手动新增。有任务时等待服务端分配 ID，然后显示并选中已持久化镜头。 | 组件验证禁用状态，以及使用服务端 ID 新增成功后滚到底部。[编辑器](../../src/components/ScriptEditor.vue) · [回归](../../tests/user/scriptEditor.test.ts) |
| WEB-11 | 项目和子项目释放拖拽时先保存目标索引，再清除悬停状态。 | 两种列表各将第 1 项拖至第 3 项，精确断言提交顺序。[侧栏](../../src/components/SongSidebar.vue) · [回归](../../tests/user/workspaceIntegrity.test.ts) |
| WEB-12 | 管理列表、性能页和视频账单对每次查询分配序号，仅接受最新查询的结果、错误和加载状态。 | 挂载账单面板，让旧查询最后完成。新筛选仍只显示新查询中的子项目。[账单](../../src/components/AdminVideoBillingPanel.vue) · [后台](../../src/views/AdminConsoleView.vue) · [回归](../../tests/admin/adminVideoBilling.test.ts) |
| WEB-13 | 详情加载失败清除未成功加载的活动任务 ID，再次点击原任务可重试。 | 首次详情响应 503，第二次点击同项能载入并选中已保存镜头。[工作区](../../src/stores/project/workspace.ts) · [回归](../../tests/user/workspaceIntegrity.test.ts) |
| WEB-14 | 去重后按最多 100 镜顺序提交，项目切换会取消后续批次。 | 205 个不同镜头加一个重复 ID，实际提交 100、100、5 个且顺序与输入相同。[分镜](../../src/stores/project/storyboard.ts) · [回归](../../tests/user/workspaceIntegrity.test.ts) |
| WEB-15 | 私有分类重命名和合并由后端在事务中持久化。重名时迁移当前用户的私有人物并软删除原分类。 | 经改名再合并后重新 GET，人物引用目标分类且旧分类消失。[接口](../../backend/app/domain.py) · [回归](../../backend/tests/test_workspace_integrity.py) |
| WEB-16 | 项目、子项目与手动镜头在收到删除成功响应后才从当前列表移除。 | 三种 DELETE 的模拟失败均保留原记录及当前选择。[工作区](../../src/stores/project/workspace.ts) · [分镜](../../src/stores/project/lines.ts) · [回归](../../tests/user/workspaceIntegrity.test.ts) |
| WEB-17 | 每批状态请求限时 12 秒。终态观察回执独立发送并在 5 秒后中止。 | 挂起第一次查询，确认后续查询重新发送。挂起回执时结果仍正常交付。501 个同时观察的工单按 500 和 1 两批返回全部结果。[调度器](../../src/utils/generationPoller.ts) · [回归](../../tests/user/generationPoller.test.ts) |
| WEB-18 | 带有效 ASS 时间点和项目音轨时，预览使用实际分镜起点，终点取歌曲时长加偏移。浏览器按剪辑时长对齐源视频播放时间。 | 15 秒音轨、−2 秒偏移、不同素材时长的四镜，验证实际预览的三段为 0–6、6–10、10–13 秒。浏览器另验证真实本地视频的连续播放与全屏切换。[时间轴](../../src/stores/project.ts) · [回归](../../tests/user/workspaceIntegrity.test.ts) · [浏览器](../../e2e/user/player-fullscreen.spec.ts) |
| WEB-19 | 本地与远程用例的断言均匹配界面文案“正在查询原视频工单”。本地测试分别断言零新生成、正在观察的 ID 和刷新结果。 | Chromium 刷新前后各读取活动工单列表，所有状态查询仅含原 ID，且视频生成 POST 总数为零。[浏览器用例](../../e2e/user/video-reconciliation.spec.ts) |
| WEB-20 | 头像请求验收检查可选分辨率的实际序列化方式，后端验证有效规格。 | 5 条 Chromium 头像旅程均通过。接口参数回归验证普通默认 1K、Seedream 带参考图默认 2K，以及显式 4K 的保留。[浏览器用例](../../e2e/user/digital-human-headshot.spec.ts) · [后端规则覆盖](../../backend/tests/test_workspace_integrity.py) |

## 运行记录

- 本轮首次前端 Vitest 全量通过 54 个文件、292 项。随后补充旧会话结束切换和创意分镜跨任务返回两种情况，工作区/项目专项复跑 77 项通过。组件重测的默认 jsdom 并行度从 4 调为 2，保留 5 秒超时，避免与本机镜像构建争用资源。最新全量计数见[总验收记录](remediation-2026-11-19.md)。
- 后端 SQLite 专项 4 项通过。供应商派发和人物注册使用本地替身。行锁代码按 PostgreSQL 语义编写，这组 SQLite 用例验证重放、事务结果和字段保留。
- Chromium 默认清单收集 35 项，本地 27 项全部通过，8 项由用例开关跳过。已执行管理后台模型渠道、ASS 全旅程、构建版本刷新、头像五个场景、退出及失败重试、人工核对、弹窗关闭、两项导出、视频全屏播放、人物标签和裁切、六组任务模型变更、批量视频恢复和原工单核对。
- 跳过项包括部署后台 API 1 项、部署后台页面 2 项、需要测试服务器工单夹具的人工与自动核对各 1 项、真实模型生成 1 项、部署用户 API 与页面各 1 项。
- 另用一次性本地 ASGI 服务与真实前端构建运行了后台 API、内容管理员和用户项目配置三条开关用例，全部通过。用户旅程使用合成 ASS 与测试渠道目录。访问控制验证读取真实路由，内容管理员可在新标签进入授权栏目，原工作台保持打开，越权读取仪表盘返回 403。共执行清单中 30 个不同用例。其余 5 个分别需要部署账单与 Worker 心跳、测试服务器的两类工单夹具、完整 TOS API 集成或真实模型调用。
- TypeScript 与 Vite 生产构建通过。Prettier 全量格式检查通过。ESLint 为零错误，两个既有 Playwright 文件给出 5 条单文件组件数量警告。Vite 在 Chromium 运行期间记录过一次 ResizeObserver 通知延后，所有旅程断言通过。
