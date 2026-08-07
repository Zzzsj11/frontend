# MV Storyboard 全链路自动化测试报告

- 测试日期：2026-08-07（America/Los_Angeles）
- 环境：Docker Compose；Vue 3 前端、FastAPI 后端、PostgreSQL 16、Redis 7
- 测试账号：`admin`
- 结论：通过。ASS 与通用分镜均由浏览器真实操作完成提示词、场景图、视频、播放器和素材包导出；4 张图片、4 张视频、4 张封面和 2 个 ZIP 均已用 HTTP 200 验证。

## 一、实施与清理结果

### API 错误审计

新增 `api_error_logs` 表及 Alembic 迁移 `b7d02d13a9f4`。FastAPI 的 HTTP、参数校验和未捕获异常现在统一生成 `errorCode` 并入库，记录用户、请求方法、路径、查询参数、状态码、异常类型、脱敏请求体、堆栈、IP 和 User-Agent。密码、Token、Cookie 等敏感值会被替换，管理员可查询或软删除日志。

### 前端错误提示

新增全局错误总线和 `ErrorDialog`。网络失败、API 非 2xx、分镜/图片/视频/导出失败都会弹出一致的模态提示，显示可复制的错误编号，重复错误会去重；生成失败后相关 loading 状态会恢复，用户可继续重试。

### 数据与文件清理

执行真实测试前，已软删除所有非默认业务数据，并清空 Redis。保留的默认数据为：1 个管理员、30 个系统人物、1 个系统人物分类、2,124 条歌曲情感配置。删除操作遵循 `deleted_at` 软删除规则。

已移除旧演示图片、旧演示视频、旧截图、Vite 示例素材、过期 ASS/响应文件及旧报告；本次仅保留可复现输入和 24 张验收截图。真实生成媒体全部位于 TOS，仓库内没有保存项目生成的图片或视频。

测试完成后的有效业务数据是本报告的两组验收结果：2 个项目、2 个任务、4 条分镜、4 张场景图、4 段视频、12 个生成任务、12 条 Token 账单、2 个素材导出包。另有 7 条 `/api/auth/refresh` 的 401 审计记录，来自无 Refresh Token 的浏览器冷启动，证明预期鉴权错误也被入库。

## 二、ASS 全链路

### 输入

- 文件：[`10012204-full-e2e.ass`](../test-artifacts/full-journey/inputs/10012204-full-e2e.ass)
- 文件编号：`10012204`
- 入库匹配：歌曲《他不爱我》，歌手李琦；流行歌曲 / 爱情消极 / 失恋；冬季、冷色调、雨夜街景
- 歌词：`雨落在最后一班车离开的站台`；`我终于学会在冷光里告别`
- 角色：系统人物 001、系统人物 017
- 画幅/时长：16:9；每镜 5 秒

### 输出

1. 建立镜：冬季雨夜末班车站台，人物 001 位于候车亭边缘，缓慢横移并轻推，冷蓝低饱和。
2. 收束镜：人物 001 与 017 分置左右，中间留白，极慢推近并轻移，以冷光中的告别收束。

项目 `project-7ecb1ddabde248e38b93ea567c26d0f8`，任务 `task-95fa2f5790b645a882e04fe31828d6e8`。两条分镜、两张场景图、两段 1080p/5 秒视频均为 `succeeded`，导出 ZIP 为 `ready`。

Token：分镜模型 `gpt-5.5` 调用 2 次，输入 2,575、输出 1,700、合计 4,275。图片模型 `gpt-image-2` 与视频模型 `doubao-seedance-2.0` 各记账 2 次；供应商未返回文本 Token，因此相应 Token 数为 0，但调用账单仍完整保留。

## 三、通用分镜全链路

### 输入

- 类型：流行 / 爱情积极 / 青涩心动；秋季；青年；电影写实
- 空镜 1、人物镜 1；总时长 10 秒；9:16
- 角色：系统人物 018
- 额外要求：`同一秋夜城市街区，从孤独到相遇，电影写实`

### 输出

1. 空镜：秋夜城市旧街，湿润石板路与暖色路灯倒影，低机位稳定推进，无人物。
2. 人物镜：少女在老公寓窗边由中景推至近景，余晖、暖色街灯和浅景深表达青涩期待。

项目 `project-6297cdf333eb46078a91cf2180addd74`，任务 `task-3bedb12772ae4628b3eecb0043f0b327`。两条分镜、两张 9:16 场景图、两段 1080p/5 秒视频均为 `succeeded`，导出 ZIP 为 `ready`。

Token：分镜模型 `gpt-5.5` 调用 2 次，输入 1,819、输出 793、合计 2,612。图片和视频各记账 2 次，供应商 Token 字段为 0。两条旅程文本模型总计输入 4,394、输出 2,493、合计 6,887 Token。

## 四、节点截图

### ASS（01–12）

1. [登录与清洁工作区](../test-artifacts/full-journey/screenshots/01-login-and-empty-workspace.png)
2. [创建 ASS 项目](<../test-artifacts/full-journey/screenshots/02-ASS 全链路真实验收-project-created.png>)
3. [上传 ASS 与选择角色](../test-artifacts/full-journey/screenshots/03-ass-input-and-cast-selected.png)
4. [两条提示词生成完成](../test-artifacts/full-journey/screenshots/04-ass-all-prompts-complete.png)
5. [第 1 条场景生成启动](../test-artifacts/full-journey/screenshots/05-ass-line-1-scene-started.png)
6. [第 2 条场景生成启动](../test-artifacts/full-journey/screenshots/06-ass-line-2-scene-started.png)
7. [全部场景完成](../test-artifacts/full-journey/screenshots/07-ass-all-scenes-complete.png)
8. [第 1 段视频启动](../test-artifacts/full-journey/screenshots/08-ass-line-1-video-started.png)
9. [第 2 段视频启动](../test-artifacts/full-journey/screenshots/09-ass-line-2-video-started.png)
10. [全部视频完成](../test-artifacts/full-journey/screenshots/10-ass-all-videos-complete.png)
11. [播放器就绪](../test-artifacts/full-journey/screenshots/11-ass-video-player-ready.png)
12. [素材包导出完成](../test-artifacts/full-journey/screenshots/12-ass-material-export-complete.png)

### 通用分镜（13–24）

13. [创建通用分镜项目](<../test-artifacts/full-journey/screenshots/13-通用分镜全链路真实验收-project-created.png>)
14. [参数与角色选择](../test-artifacts/full-journey/screenshots/14-general-parameters-and-cast-selected.png)
15. [两条提示词生成完成](../test-artifacts/full-journey/screenshots/15-general-all-prompts-complete.png)
16. [第 1 条场景生成启动](../test-artifacts/full-journey/screenshots/16-general-line-1-scene-started.png)
17. [第 2 条场景生成启动](../test-artifacts/full-journey/screenshots/17-general-line-2-scene-started.png)
18. [全部场景完成](../test-artifacts/full-journey/screenshots/18-general-all-scenes-complete.png)
19. [第 1 段视频启动](../test-artifacts/full-journey/screenshots/19-general-line-1-video-started.png)
20. [第 2 段视频启动](../test-artifacts/full-journey/screenshots/20-general-line-2-video-started.png)
21. [全部视频完成](../test-artifacts/full-journey/screenshots/21-general-all-videos-complete.png)
22. [播放器就绪](../test-artifacts/full-journey/screenshots/22-general-video-player-ready.png)
23. [素材包导出完成](../test-artifacts/full-journey/screenshots/23-general-material-export-complete.png)
24. [两条旅程最终状态](../test-artifacts/full-journey/screenshots/24-both-journeys-final-state.png)

## 五、测试中发现并修复的问题

- 首次测试时视频时长曾按 5/10 秒处理；后续已依据供应商完整能力统一扩展为 4–15 秒整数，并增加前后端边界校验与旧规划时长归一化。
- 9:16 分镜曾使用横图尺寸：场景生成现按画幅选择图片尺寸，竖屏使用 1024×1536。
- 创建项目与初始项目列表加载存在竞态，可能把通用任务挂到前一个 ASS 项目：创建与切换现为同一个 store 事务，列表加载期间禁止创建。
- 真实测试的通用按钮选择器误命中侧栏按钮：改为限定编辑器头部区域。
- 播放器选中分镜会重新打开编辑弹窗：测试按真实交互关闭弹窗后再执行导出。

## 六、验证清单

- 前端单元测试：6/6 通过。
- 后端 API/隔离/存储/提示词/用户旅程测试：20/20 通过。
- Playwright 真实媒体旅程：ASS 完成；通用生成完成；播放器与导出恢复阶段 1/1 通过。
- PostgreSQL 迁移头：`b7d02d13a9f4`。
- Docker 四个服务均健康。
- 4 张场景图、4 张封面、4 段视频、2 个 ZIP：逐一请求均返回 HTTP 200。
- 所有有效媒体 URL 均为 TOS HTTPS URL；视频 `cover_url` 为供应商视频首帧抽取并上传到 TOS 的 JPG。

说明：真实供应商生成耗时较长，测试支持 `REAL_E2E_PHASE=general` 与 `general-export` 断点恢复；这不会跳过业务断言，目的是在浏览器或测试脚本自身失败时复用已经成功且已记账的媒体，避免重复收费。
