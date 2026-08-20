# 生成模型接入现状与剩余技术债

> 最后核验：2026-08-19。本文件不记录已失效的实施过程，只维护当前能力和仍需处理的架构债。接入模型不能只给前端下拉框增加名称，必须同步完成后端校验、供应商参数映射、任务持久化、用量记录、旧任务兼容和自动化测试。

## 已完成（勿重复）

- 后端模型注册中心：模型存库，管理后台「模型管理」CRUD 与启停，公开端点 `GET /api/model-options` 动态下发。
- 前端选择器动态化：`src/generationModels.ts` 的 `loadGenerationModels()` 从 `/model-options` 拉取并覆盖内置默认，注册中心不可用时回退默认模型，不再硬编码禁用。
- H3 已进入项目视频生成主流程，UI 支持 T2VA、I2VA、FL2VA、Ref2VA（当前产品明确不开放 L2VA）；Ref2VA 产品上限为 6 图、1 视频、3 音频，视觉素材必需，音频不能单独提交。
- H3 任务、请求、结果和 RunningHub 输入输出均持久化；当前单 API 实例内并发上限为 2。

## 剩余待办

当前 `/model-options` 已返回部分 capabilities，但仍有约束分散在前端 `src/mediaConstraints.ts`、后端 `backend/app/media_constraints.py` 和 H3 模式校验中。继续接入模型时必须完成：

- [ ] 在管理后台模型注册时录入真实供应商标识，不得把 UI 别名直接当作供应商 API model 值。
- [ ] 为每个模型声明支持的画幅、清晰度、时长范围、参考图数量、音频、水印等能力，入库并随 `/model-options` 下发（扩展现有响应结构）。
- [ ] 前端按模型能力动态联动和禁用不支持的参数（替换 `mediaConstraints.ts` 硬编码），后端必须重复校验。
- [x] 扩展 `GeneralStoryboardCreate`、ASS Form 参数、`ImageGenerationCreate`、`VideoGenerationCreate` 的 H3 后端白名单与模式校验。
- [x] 将所选模型持久化到 `project_tasks.storyboard_config` 和每条 `storyboard_lines.shot_options`，并在生成请求中实际传递。
- [x] 在 `generation_jobs` 和模型调用记录中保留最终供应商、模型及 H3 工作流信息。
- [ ] 统一 `token_usage_records` 与失败账单的非 Token 计费字段，避免各供应商使用私有结构。
- [x] 单机阶段把媒体生成和素材导出迁移到独立Worker，队列以 PostgreSQL 为事实源、Redis为唤醒通道，并继续按模型配置独立执行池。
- [ ] 多机/K8s阶段把 H3 并发 2 从单Worker进程信号量升级为 Redis 原子租约，并支持未来按供应商、模型和账户配置不同上限。
- [x] 把通用Chat对话迁移到独立 `worker-chat`，保留现有Redis事件/SSE协议并支持跨进程中断。
- [ ] 把ASS大纲、场景段重试等领域LLM后台协程迁移到独立Worker。
- [ ] 核对模型计费口径；如供应商不返回 Token，应记录调用次数、原始 usage 和可用的费用单位。
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
