# 生成模型接入现状与剩余技术债

> 本文件只维护当前能力和仍需处理的架构债；已同步 PPIO/BFL 退役口径。接入模型不能只给前端下拉框增加名称，必须同步完成后端校验、供应商参数映射、任务持久化、用量记录、旧任务兼容和自动化测试。

## 退役边界与迁移要求

PPIO 与 BFL（Black Forest Labs，历史 FLUX 3）已从 MV 与 model-service 移除支持，适配器、余额查询、模型 seed 和人物 PPIO 专属字段不再属于活动能力，不列入后续接入或补测计划。

- MV 历史 Alembic 文件保留，避免迁移断链；通过新增前向迁移软删除存量 provider/model/pricing 行，并移除人物专属字段。
- model-service 同样需要前向迁移退役旧渠道及关联模型、费率配置行；不能仅删除 seed 后假定旧数据库已清理。
- 上线前须分别确认两侧迁移落库；本说明不代表已经执行。历史财务工单、费用、用量与媒体保留，不通过退役清理删除或重写。

## 已完成（勿重复）

- 后端模型注册中心：模型存库，管理后台「模型管理」CRUD 与启停，公开端点 `GET /api/model-options` 动态下发。
- 前端选择器动态化：`src/generationModels.ts` 的 `loadGenerationModels()` 从 `/model-options` 拉取并覆盖内置默认，注册中心不可用时回退默认模型，不再硬编码禁用。
- H3 已进入项目视频生成主流程，UI 支持 T2VA、I2VA、FL2VA、Ref2VA（当前产品明确不开放 L2VA）；Ref2VA 产品上限为 6 图、1 视频、3 音频，视觉素材必需，音频不能单独提交。
- H3 保留 RunningHub 工作流模型（前端标注并发上限 2），并新增 MiniMax-H3 直连模型（前端显示 H3）；直连协议使用 `/video/generation/tasks`、稳定 `Idempotency-Key`、`task_id` 和 `task.content.url`，768P/2K 分别由产品侧 480p/720p 与 1080p 映射。
- 人物入库时注册英合虚拟人物资产，英合 Seedance 生成时使用 `asset_avatar_url`；TOS 原图与缩略图保持不变。
- MV 余额端点查询英和商户/子账号 Key；批量生成按模型 `billing` 决定是否估价和校验余额，不使用其他渠道余额兜底。独立 model-service 的余额采集范围见其 `docs/CHANNEL-BALANCES.md`，不等同于 MV 生成预检范围。
- 模型能力同时下发 `billing`、`resolutionLabels` 与 `providerResolutionMap`。RunningHub 明确为暂不计费且不检查英和余额；英和 H3 的内部兼容档位 `720p/1080p` 分别映射供应商 `768P/2K`，RunningHub 映射为工作流 MP 档位。
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

## 2026-09-21 补测修复与未决协议

- 管理端同步识别 Kling `task_status=succeed` 等成功状态；对仍受支持渠道，显式对账恢复允许已失败工单补回资产和成功状态，并重新对账。普通 worker 的超时终态保护保持生效。
- Gemini 保持文档规定的顶层 `prompt`、`images`；单张人物身份图使用 `reference_to_video`，普通单张场景图使用 `image_to_video`。2026-09-21 同图同提示词补测已确认公网 URL 报“缺少图片”、Base64 Data URL 成功生成 1280×720 / 10 秒视频。仅 Gemini Omni 在提交前将公网原图下载并转为 Base64 Data URL（按图片实际格式确定 MIME，单图限制 20 MiB，沿用公网地址及重定向安全检查）；工单仍保留原图 URL，其他模型不变。
- Kling V3 首尾帧使用 `image` / `image_tail`，图生时不传 `aspect_ratio`。人物卡不能自动映射成首帧；缺少同渠道主体创建接口及 `element_list` 完整结构时，在提交前明确拒绝该参考模式，避免再次产生无效成片。此校验不等于已完成人物主体生成接入。
- Gemini 与 Kling 适配器保存脱敏的实际请求体到工单，管理员可通过视频对账详情的 `providerRequest` 核查；不记录鉴权头。
- 历史补测仅覆盖原失败、未执行和 Kling 人物不合格镜头；已有合格结果不重生成。当时维持 720 档、Grok/Gemini 10 秒，HappyHorse/Vidu/Veo 继续排除。这不构成新一轮付费调用授权；已退役渠道不再补测。所有真实调用必须携带 `X-Agent-Name: code-agent`、本次运行唯一的 `X-Agent-Run-Id` 与 `X-Test-Run-Id`。
