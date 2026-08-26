# 生成模型接入现状与剩余技术债

> 最后核验：2026-08-26。本文件不记录已失效的实施过程，只维护当前能力和仍需处理的架构债。接入模型不能只给前端下拉框增加名称，必须同步完成后端校验、供应商参数映射、任务持久化、用量记录、旧任务兼容和自动化测试。

## 已完成（勿重复）

- 后端模型注册中心：模型存库，管理后台「模型管理」CRUD 与启停，公开端点 `GET /api/model-options` 动态下发。
- 前端选择器动态化：`src/generationModels.ts` 的 `loadGenerationModels()` 从 `/model-options` 拉取并覆盖内置默认，注册中心不可用时回退默认模型，不再硬编码禁用。
- H3 已进入项目视频生成主流程，UI 支持 T2VA、I2VA、FL2VA、Ref2VA（当前产品明确不开放 L2VA）；Ref2VA 产品上限为 6 图、1 视频、3 音频，视觉素材必需，音频不能单独提交。
- H3 保留 RunningHub 工作流模型（前端标注并发上限 2），并新增 MiniMax-H3 直连模型（前端显示 H3）；直连协议使用 `/video/generation/tasks`、稳定 `Idempotency-Key`、`task_id` 和 `task.content.url`，768P/2K 分别由产品侧 480p/720p 与 1080p 映射。
- PPIO 已按独立供应商接入 Seedance 2.0 标准版与 MiniMax-H3：Seedance 使用 `/v3/bytedance-cn/metered/contents/generations/tasks`，H3 使用 `/v3/minimax/v2/video_generation`；人物入库时会分别注册英合与 PPIO 两份虚拟人物资产，Seedance 生成时按所选模型渠道使用对应 `asset://`；模型编码、执行池、余额和账单均与英和隔离，前端按英和、PPIO、RunningHub 顺序展示。
- 余额端点聚合英和商户/子账号 Key 与 PPIO `availableBalance`；PPIO 原始金额按 1/10000 元保留在 `rawBalance/rawDetails`，业务和前端统一换算为人民币元。批量生成按渠道分别估价和校验；PPIO SD2.0 估算按 8 折后的 0.8 元/秒，PPIO H3 按 85 折后的 0.425 元/秒。
- 模型能力同时下发 `billing`、`resolutionLabels` 与 `providerResolutionMap`。RunningHub 明确为暂不计费且不检查英和余额；英和/PPIO H3 的内部兼容档位 `720p/1080p` 分别映射供应商 `768P/2K`，RunningHub 映射为工作流 MP 档位。
- 视频完成后通过 ffprobe 固化实际宽高、FPS、编码、真实时长和文件大小；请求档位、供应商档位、实际文件规格分开保存和展示。

## 剩余待办

当前 `/model-options` 已返回部分 capabilities，但仍有约束分散在前端 `src/mediaConstraints.ts`、后端 `backend/app/media_constraints.py` 和 H3 模式校验中。继续接入模型时必须完成：

- [ ] 在管理后台模型注册时录入真实供应商标识，不得把 UI 别名直接当作供应商 API model 值。
- [x] 为视频模型声明画幅、清晰度、时长、参考素材、原生音频、执行池、计价与供应商档位映射，并随 `/model-options` 下发。
- [x] 前端按模型能力动态联动清晰度和参考模式，后端重复校验；通用时长边界仍保留共享业务默认值。
- [x] 扩展 `GeneralStoryboardCreate`、ASS Form 参数、`ImageGenerationCreate`、`VideoGenerationCreate` 的 H3 后端白名单与模式校验。
- [x] 将所选模型持久化到 `project_tasks.storyboard_config` 和每条 `storyboard_lines.shot_options`，并在生成请求中实际传递。
- [x] 在 `generation_jobs` 和模型调用记录中保留最终供应商、模型及 H3 工作流信息。
- [x] 账单层统一使用 `usage_type/usage_quantity/usage_unit/raw_usage` 表达 Token、秒和 RunningHub 币。
- [x] 单机阶段把媒体生成和素材导出迁移到独立Worker，队列以 PostgreSQL 为事实源、Redis为唤醒通道，并继续按模型配置独立执行池。
- [x] 模型执行池已使用 Redis 原子租约并带心跳续租，多 Worker 共享并发上限。
- [x] 把通用Chat对话迁移到独立 `worker-chat`，保留现有Redis事件/SSE协议并支持跨进程中断。
- [x] 把ASS/通用大纲、ASS场景段重试迁移到独立 `worker-storyboard`；完整输入、进度和心跳持久化，内部工单支持最多3次有界重放。
- [x] SD2.0 按输出 Token、直连 H3 按输出秒数、RunningHub 暂排除；失败任务仍保留原始 usage 与失败标识。
- [ ] 处理旧任务使用已下线模型时的只读展示、重试提示与迁移策略。
- [ ] 增加前后端模型白名单、能力矩阵、默认值、非法组合和多用户隔离测试。
- [ ] 更新 Playwright ASS、通用分镜与真实付费验收用例，截图应能证明模型选择和最终任务记录一致。

## 能力响应建议结构

```json
{
  "kind": "video",
  "id": "provider-model-id",
  "label": "用户可读名称",
  "enabled": true,
  "ratios": ["16:9", "9:16"],
  "resolutions": ["720p", "1080p"],
  "duration": { "min": 4, "max": 15, "step": 1 },
  "referenceImage": { "min": 0, "max": 1 }
}
```

模型能力由后端数据库管理（管理后台可编辑），前端只负责呈现和提交。
