# TODO：生成模型扩展技术债

> 本文档是仓库唯一的待办清单。核心要求：不要只给前端下拉框增加名称，必须同步完成后端白名单、能力矩阵、供应商参数映射、任务配置持久化、Token/费用账单、旧任务兼容和自动化测试。

## 已完成（勿重复）

- 后端模型注册中心：模型存库，管理后台「模型管理」CRUD 与启停，公开端点 `GET /api/model-options` 动态下发。
- 前端选择器动态化：`src/generationModels.ts` 的 `loadGenerationModels()` 从 `/model-options` 拉取并覆盖内置默认，注册中心不可用时回退默认模型，不再硬编码禁用。

## 剩余待办

当前 `/model-options` 仅返回 `id / name / modality`，能力约束仍写死在前端 `src/mediaConstraints.ts`（时长 4–15s）与后端 `backend/app/media_constraints.py`。接入新模型时必须完成：

- [ ] 在管理后台模型注册时录入真实供应商标识，不得把 UI 别名直接当作供应商 API model 值。
- [ ] 为每个模型声明支持的画幅、清晰度、时长范围、参考图数量、音频、水印等能力，入库并随 `/model-options` 下发（扩展现有响应结构）。
- [ ] 前端按模型能力动态联动和禁用不支持的参数（替换 `mediaConstraints.ts` 硬编码），后端必须重复校验。
- [ ] 扩展 `GeneralStoryboardCreate`、ASS Form 参数、`ImageGenerationCreate`、`VideoGenerationCreate` 的后端白名单。
- [ ] 将所选模型持久化到 `project_tasks.storyboard_config` 和每条 `storyboard_lines.shot_options`；任务创建时保存一份能力快照，避免模型配置变化后无法解释历史生成参数。
- [ ] 确保图片与视频生成请求实际传递用户选择的模型，而不只是页面展示。
- [ ] 在 `generation_jobs`、`token_usage_records` 和失败账单中记录最终供应商及模型。
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
