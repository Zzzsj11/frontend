# 公司内部模型 API 对接文档

## ToAPIs 普通版图片规格补充（2026-09-22）

统一 `/v1/images` 的 `size` 可使用已支持的像素别名，或比例加显式 `resolution`，例如 `{"size":"2:3","resolution":"1K"}`。`1024x1536` 映射为 `2:3 / 1K`，不会再强制方形；`2880x2880` 是该渠道的 `4K` 档位，不能按最长边误报为 2K。比例与分辨率档位不承诺上游实际输出的每个像素，归档元数据仍记录实测结果。

普通 GPT Image 2.5 固定 high，统一接口允许 auto/high，明确指定 medium 等会在提交前返回 422，不再静默改成 high；需要其他画质须另配对应上游版本。Seedream 5.0 支持 2K/3K，Gemini 普通版支持本接口列出的 1K/2K/4K。无法转换的尺寸或互相冲突的 size/resolution 返回 422。`estimate_only` 复用同一参数转换，响应含 `normalized_parameters`，规格不支持时同样拒绝。

协议依据：[GPT Image 2](https://docs.toapis.com/docs/cn/api-reference/images/gpt-image-2/generation)、[GPT Image 2.5 普通版](https://docs.toapis.com/docs/cn/api-reference/images/gpt-image-2.5/generation)、[Seedream 5.0](https://docs.toapis.com/docs/cn/api-reference/images/seedream-5.0/generation)。

版本：1.0 开发版。依据当前 MV 适配代码、既有渠道说明和实测记录整理。当前部署地址及真实密钥见本机 `.secrets/API-INTEGRATION.internal.md`，该文件不提交 Git。下面的 `$MODEL_API_KEY` 是内部调用方 Key，绝不是供应商 Key。

## 1. 连接与公共约定

本机公开 API：`http://127.0.0.1:8011`；管理台：`http://127.0.0.1:5180`；管理 API：`http://127.0.0.1:8012`。生产在公司 HTTPS 入口后部署。

请求体默认上限 32 MiB；优先传原图公网 URL，由服务下载转换，避免大段 Base64 膨胀。每个调用方默认最多 1000 个在途／排队任务，达到上限返回 429。

每个系统一个 Key，每个实际用户一个稳定的 `X-User-Id`。只在同一逻辑请求的网络重试中复用 `Idempotency-Key`；参数或 Agent 批次变化时复用键返回 409。任务和结果按调用方与用户双重隔离。

```bash
curl "$MODEL_API/v1/jobs" \
  -H "Authorization: Bearer $MODEL_API_KEY" \
  -H 'X-User-Id: internal-user-001' \
  -H 'Idempotency-Key: example-veo-001' \
  -H 'Content-Type: application/json' \
  -d '{"model":"veo-3.1-generate-preview","payload":{"prompt":"A quiet autumn riverside at sunrise, no people.","duration":8,"resolution":"720p","size":"1280x720","metadata":{"aspectRatio":"16:9","resolution":"720p"}}}'
```

测试或 Agent 调用必须追加：

```
X-Agent-Name: code-agent
X-Agent-Run-Id: <本次唯一批次>
X-Test-Run-Id: <本次测试批次>
```

Agent 专属 Key 强制要求这三个头；记录会进入任务与管理后台来源筛选，禁止冒充正常业务。API Key 仅创建时返回一次；管理员可停用、轮换或软删除。

## 2. 推荐的统一参数接口

新系统优先调用 `POST /v1/videos` 或 `POST /v1/images`，都返回 202 工单。后文逐模型原生 payload 示例适用于高级 `/v1/jobs` 与迁移兼容接口；新系统无需自己实现这些渠道映射。

```bash
curl "$MODEL_API/v1/videos" \
  -H "Authorization: Bearer $MODEL_API_KEY" \
  -H 'X-User-Id: internal-user-001' \
  -H 'Idempotency-Key: unified-video-001' \
  -H 'Content-Type: application/json' \
  -d '{"model":"gemini-omni-flash-preview","prompt":"A quiet autumn riverside at sunrise.","duration":10,"aspect_ratio":"16:9","resolution":"720p","images":[],"reference_mode":"text","generate_audio":false}'
```

| 字段 | 统一含义 |
|---|---|
| model / prompt | 必填，目录模型 ID 与提示词 |
| duration | 整数秒；省略时 Veo 默认 8、Gemini Omni 默认 10、其余默认 5 |
| aspect_ratio | 16:9（默认）、9:16、4:3、1:1；按模型再次限制 |
| resolution | 默认 720p；H3 的 720p 映射 768P，1080p 映射 2K |
| images / videos / audios | 参考素材原始 URL 数组；按模型限制数量与类型 |
| reference_mode | auto / text / first_frame / first_last / reference；不支持的组合在付费前拒绝 |
| generate_audio / watermark | 默认 false，转换为对应模型的字段；各模型实际支持程度以原生协议为准 |

Kling 的 auto/身份参考图片不会被自动当成首帧，必须明确使用场景首帧模式；Veo 此接口使用 reference 图片，暂不提供未验证的首尾帧控制。Gemini 图片转 Base64 由服务完成。H3 的视频和音频参考也在服务端转换为 content。RunningHub 工作流继续使用专用兼容接口。

图片接口示例：

```json
{"model":"gpt-image-2.5-flare","prompt":"A blue ceramic cup on a cream tabletop.","size":"1024x1024","quality":"low","n":1,"images":[]}
```

图片 images 统一为数组，服务自动转换上游单图／多图字段。任务查询和所有权规则与视频相同。

## 3. 统一任务生命周期

`POST /v1/jobs` 返回 202，JSON 含 `id/model/kind/status/provider_task_id/result/usage/error/origin/agent_run_id`。创建受理不代表渠道已成功生成。

`GET /v1/jobs/{id}` 需相同 Key 与 `X-User-Id`，返回：

```json
{"id":"job-...","model":"veo-3.1-generate-preview","kind":"video","status":"succeeded","provider_task_id":"task_...","result":{"media":[{"url":"https://...tos.../video.mp4","cover_url":"https://.../cover.jpg","thumbnail_url":"https://.../thumbnail.jpg"}],"native":{}},"usage":{"output_seconds":8},"error":null,"origin":"agent_test","agent_name":"code-agent","agent_run_id":"run-...","created_at":"2026-09-21T00:00:00+00:00"}
```

上例 usage 仅示意：真实字段由渠道提供，空对象表示没有拿到用量，不能认定免费。规范化媒体原文件与图片缩略图均归档 TOS；`native` 保留供应商结构并将主结果 URL 替换为 TOS 链接。

对外 `/v1/jobs` 与用户门户只返回四种状态：

| 状态 | 含义 | 客户端操作 |
|---|---|---|
| queued | 等待执行 | 轮询 |
| running | 准备、提交、生成、归档或等待恢复 | 轮询原任务 |
| succeeded | 生成和归档完成 | 使用结果 |
| failed | 失败或需内部人工核查 | 查看原因，不自动重新付费 |

服务端数据库与管理 API 保留细分状态：`preparing/submitting/archiving/recoverable` 对外映射 `running`，`manual_review` 对外映射 `failed`。状态映射只发生在返回数据时，不修改任务状态、用量、积分或恢复逻辑。

建议每 5 秒查询一次。管理恢复端点 `POST /admin/jobs/{id}/recover` 仍只允许带渠道 ID 的 `recoverable` 任务，不发送第二个生成 POST；`manual_review` 必须核查渠道结果，不能因对外显示 failed 就自动重提。

## 4. 模型与协议总表

| 内部模型 ID（payload model 由服务强制校正） | 渠道 | 协议 | 既有验证 |
|---|---|---|---|
| doubao-seedance-2.0 | 英和 | Seedance V3 | 有 720p 成片 |
| doubao-seedance-2.0-mini | 英和 | Seedance V3 | 有 480p 成片 |
| doubao-seedance-2.0-fast | 英和 | Seedance V3 | 有 480p 成片 |
| MiniMax-H3 | 英和 | H3 content | 5/5，720 档映射 768P |
| wan3.0-video | 英和 | input + parameters | 5/5 |
| wan3.0-video-prime | 英和 | input + parameters | 有成功成片 |
| kling-v3 | 英和 | Kling 原生字段 | 曾成片，人物卡问题，默认停用 |
| veo-3.1-generate-preview | 英和海外 | unified | 5/5，8 秒 720p |
| veo-3.1-fast-generate-preview | 英和海外 | unified | 有 720p 成片 |
| gemini-omni-flash-preview | 英和海外 | unified + Base64 | 补测后 5/5，10 秒 720p |
| gpt-image-2 / gpt-image-2.5-sunburst / gpt-image-2.5-flare | 英和 | 异步图片 | MV 当前图片适配 |

模型目录 `GET /v1/models` 返回当前 Key 可用模型及能力。上表“既有验证”是原 MV 实测，不等于新网关逐模型实测完成。额外保留 Grok、RunningHub、提示词优化和多 LLM 的迁移入口，见后文。

## 5. Seedance 2.0 / Mini / Fast

三个模型共用协议，仅 model 不同。上游 `POST /v3/video/tasks`，`GET /v3/video/tasks/{id}`。兼容入口前缀 `/providers/yinghe`。

```json
{"model":"doubao-seedance-2.0","payload":{"content":[{"type":"text","text":"A quiet autumn riverside at sunrise."},{"type":"image_url","image_url":{"url":"https://public.example/original.jpg"},"role":"reference_image"}],"duration":5,"ratio":"16:9","resolution":"720p","generate_audio":false,"watermark":false,"return_last_frame":true}}
```

- `content` 必填，文本与参考图按顺序放入；不需要图时删除图片项。
- MV 当前时长 4–15 整数秒；画幅 16:9、9:16、4:3、1:1。Mini/Fast 当前产品使用 480p/720p；标准版的更高规格应以账号能力为准。
- 图片使用公网原图，不传缩略图。虚拟人物资产仍使用同渠道同账号 `asset://`。服务提供受用户所有权限制的 `/providers/yinghe/v3/assets` 与 `/detail` 兼容接口。
- 上游创建返回 `id`；成功结果通常位于 `content.video_url`，用量可能是 Token，并非统一按秒计费。

## 6. MiniMax H3（英和）

上游 `POST /video/generation/tasks`，同路径加任务 ID 查询。内部模型 ID 为 `MiniMax-H3`，不是 MV 展示别名。

```json
{"model":"MiniMax-H3","payload":{"content":[{"type":"text","text":"A quiet riverside, continuous slow tracking shot."},{"type":"image_url","image_url":{"url":"https://public.example/original.jpg"},"role":"reference_image"}],"duration":5,"ratio":"16:9","resolution":"768P","aigc_watermark":false}}
```

支持文生、首帧、首尾帧、参考图/视频/音频。参考图片最多 6、视频 1、音频 3，总计最多 10；音频参考需要视觉素材。MV 720p 档映射 `768P`，1080p 档映射 `2K`，不得承诺 H3 输出恰好 1280×720。时间 4–15 秒。首帧/尾帧角色和具体 content 构造沿用 MV 编译器；本服务接收原生 content，不把身份图默认当作首帧。上游返回 `task_id`，成功地址通常为 `task.content.url`。

## 7. Wan 3.0 / Prime

两个模型共用 `input` 与 `parameters` 结构：

```json
{"model":"wan3.0-video","payload":{"input":{"prompt":"Autumn riverside at sunrise.","media":[{"type":"reference_image","url":"https://public.example/original.jpg"}]},"parameters":{"duration":5,"resolution":"720P","ratio":"16:9","audio":false,"watermark":false}}}
```

Prime 将外层 model 改为 `wan3.0-video-prime`。`media` 可省略；支持 `first_frame`、`last_frame`、`reference_image`、`reference_video`、`reference_audio`，不要把多模态素材全塞入 images。当前 MV 使用 4–15 秒。上游创建 `taskId`，成功 `resultUrl`，缩略图可能为 `thumbnailUrl`，用量可能为 `tokenUsage`。

## 8. Kling V3（默认停用）

```json
{"model":"kling-v3","payload":{"model_name":"kling-v3","prompt":"The person slowly walks forward.","image":"https://public.example/first-frame.jpg","image_tail":"https://public.example/last-frame.jpg","duration":5,"mode":"std","sound":"off","cfg_scale":0.5}}
```

时长 3–15 秒；`std` 720P，`pro` 1080P，渠道文档另列 4k。文生使用 aspect_ratio；图生不要传 aspect_ratio。`image` 是首帧、`image_tail` 是尾帧，绝非通用人物身份参考字段。主体 `element_list` 缺少已验证的主体创建接口，不开放自动人物卡转换。上游查询 HTTP 200 也可能失败，必须看 `data.task_status`；成功视频在 `data.task_result.videos`。本模型保持停用，管理员明确启用后才能提交。

## 9. Veo 3.1 / Fast

```json
{"model":"veo-3.1-generate-preview","payload":{"prompt":"Two people pass each other on a bridge.","images":["https://public.example/person-a-original.jpg","https://public.example/person-b-original.jpg"],"duration":8,"size":"1280x720","resolution":"720p","metadata":{"aspectRatio":"16:9","resolution":"720p"}}}
```

Fast 修改 model 为 `veo-3.1-fast-generate-preview`。无图时省略 images；参考图片按原图 URL 数组传递，最多 3 张，已有测试最多 2 张。既有补测为 8 秒，分辨率 720p；竖屏 size 为 720x1280。服务当前边界 4–8 秒，不表示其中每个整数都完成渠道实测。查询从 SUCCESS/succeeded 等状态判定，成功地址可能为 resultUrl、video_url 或嵌套 result。

## 10. Gemini Omni Flash Preview

```json
{"model":"gemini-omni-flash-preview","payload":{"prompt":"Animate the subject naturally in an autumn riverside scene.","images":["https://public.example/person-original.jpg"],"duration":10,"metadata":{"aspect_ratio":"16:9","task":"reference_to_video"}}}
```

- `prompt` 必须顶层；`duration` 是正整数。当前 MV 实测 10 秒，输出固定 720p。
- `metadata.task` 为 text_to_video、image_to_video、reference_to_video；单张身份图使用 reference_to_video，普通首帧使用 image_to_video，无图使用 text_to_video。
- **仅此模型**在提交前下载公网原图，校验格式并转换为 Base64 Data URL，单张不超过 20 MiB；已有 Data URL 也校验。工单保留调用输入，供应商 Key 不写入工单。
- 公网 URL 直传曾报缺少素材；Base64 路径已实测成功。内容审核拒绝与图片字段缺失是两类错误，不混为一谈。
- `edit` 需 previous_interaction_id；未做续编实测，不能据此承诺全部续编能力。

## 11. 图片生成

```json
{"model":"gpt-image-2.5-flare","payload":{"prompt":"A quiet autumn riverside, cinematic light, no text.","size":"1024x1024","quality":"low","n":1,"image":"https://public.example/original.jpg"}}
```

无参考图时省略 image；多图时 image 为数组。精细模型为 gpt-image-2.5-sunburst，快速为 gpt-image-2.5-flare，兼容旧 gpt-image-2。支持的 quality 以模型为准，MV 列表为 auto/low/medium/high/xhigh/max，n 当前 MV 限制 1–4。上游 `/image/generation/tasks`，创建 taskId，结果 resultUrls/resultUrl。服务归档每张原图和缩略图至 TOS。

## 12. LLM

```bash
curl "$MODEL_API/v1/chat/completions" \
  -H "Authorization: Bearer $MODEL_API_KEY" -H 'X-User-Id: internal-user-001' \
  -H 'Idempotency-Key: chat-example-001' -H 'Content-Type: application/json' \
  -d '{"model":"gpt-5.6-sol","messages":[{"role":"user","content":"Reply OK."}],"max_tokens":16,"stream":false}'
```

兼容 OpenAI messages、temperature、max_tokens 等原生字段；stream=true 返回 SSE，并请求渠道返回最终 usage。中断流按结果不确定记录，不能伪造完整 Token 用量。返回原生 JSON，流式额外返回 X-Job-Id。

目录预置现有后台模型对比列表：gpt-5.5、gpt-5.6-sol、gpt-5.6-terra、claude-opus-4-8、deepseek-v4-flash/pro、grok-4.6、kimi-k3、glm-5.2、qwen3.8-max。Claude 使用 `/v1/messages` 与 Anthropic 请求体；这些是已有项目配置，不代表每个 Key 均有权限。

## 13. 其他 MV 迁移入口

- Grok：内部 grok-video-1.5，ToAPIs `/v1/videos/generations`；prompt、duration、resolution、aspect_ratio、video_generation_mode，与原 MV 一致。
- RunningHub：内部 minimax-h3-runninghub，接受现有工作流 JSON，服务端注入渠道 apiKey；查询与素材上传有专用兼容入口。工作流结构仍由 MV 当前编译器生成。
- Gemini 提示词优化：gemini-3.7-flash，OpenAI 兼容接口，独立 optimizer-gemini 渠道。
- H3 提示词优化：h3-context，payload 原生 content，服务映射上游 MiniMax-H3；kind=text 返回 text，不做视频归档。

## 14. 错误与运维

401：Key 无效/停用；403：Key 不允许模型；404：任务不属于调用方用户或路径不支持；409：幂等冲突/状态不允许；422：输入不符合本服务要求；429：同步 LLM 并发已满；503：渠道未配置。

管理接口全部需要独立管理员 JWT。供应商 Key 不通过管理查询返回。管理后台包含模型启停/并发、调用方 Key 创建/停用、任务来源筛选/用量/恢复、操作审计。原始用户提示词与 Base64 不在任务列表展示。

规范化服务 API 是稳定边界；供应商原生 payload 是版本化兼容边界。新接入模型须先增加目录、适配协议、异常状态测试和真实低成本验收，不能仅增加前端名称。

## 15. 新服务实测备注

2026-09-21 最小验收中，LLM、快速图片和 Seedance Fast 均通过新服务实际生成成功。视频请求 5 秒/720p，文件实测 1280×720、24fps、约 5.042 秒。图片请求 size=1024x1024，渠道返回 1254×1254：请求规格与实际规格需要分别记录，不能直接用请求值当成文件尺寸。服务新增结果媒体的实际规格字段，原始协议兼容结果保持不变。

完整任务、测试批次、用量和本机归档验证结果见 `ACCEPTANCE.md`。本轮没有重新测试此前已暂停的渠道。


## 用户门户与积分（新增）

用户 Vue 门户目录为 `user-web/`，本机 http://127.0.0.1:5181。管理员开通账号并设置月总额后，用户登录创建自己的 API Key（最多 10 个），可分别设置月消费上限；绑定用户的 Key 自动确定所有权，不需要 `X-User-Id`，不得覆盖为他人。

1 积分 = ¥0.01。每个模型及生成方式的费率由管理员配置，用户文档读取同一组规则。以渠道实际输入/输出等用量乘对应费率扣积分，接单时保存费率快照。`GET /v1/jobs/{id}` 的 `billing` 返回本任务积分、人民币金额、计费状态与预占。完整字段、月额度和流水语义见 [PORTAL-AND-CREDITS.md](PORTAL-AND-CREDITS.md)。
