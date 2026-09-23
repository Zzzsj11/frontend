# 英和海外接入与真实测试记录

来源：https://admin-aigc.yseeai.com/async/doc；目录快照：2026-09-21。

范围：文本 55、图片 25、视频 17，共 97 个模型。排除视频增强和字幕擦除。

完整模型编码与渠道地址见 [目录快照](../catalog/yseeai-2026-09-21.json)。本报告不包含密钥；继续使用本地 `.env` 配置。

## 接入简化方案

采用模型目录驱动的协议适配；每个模型保留原始模型编码。海外新增服务模型 ID 使用 `yseeai--原始模型编码`，避免覆盖 MV 现用渠道。

| 类型 | 渠道接口 | 本服务接口 | 处理方式 |
|---|---|---|---|
| 文本 Chat | `https://ai-aigc.yseeai.com/v1/chat/completions` | `/v1/chat/completions` | 非流式/流式，用量记录 |
| 文本 Claude | 同域 `/v1/messages` | `/v1/messages` | Anthropic 消息及流式事件 |
| Responses | 同域 `/v1/responses` | `/v1/responses` | input、max_output_tokens；独立事件格式 |
| Seedream 图片 | 同域 `/v1/images/generations` | `/v1/images` 或 `/v1/jobs` | 同步渠道响应存为本地异步工单，转存失败不再生成 |
| GPT/Gemini/万相图片 | `https://api-aigc.yseeai.com/image/generation/tasks` | `/v1/images` 或 `/v1/jobs` | 创建一次，GET 原任务 ID 轮询 |
| Seedance 2.x | 同域 `/v3/video/tasks` | `/v1/videos` 或 `/v1/jobs` | content 多模态数组 |
| 其余视频 | 同域 `/video/generation/tasks` | `/v1/videos` 或 `/v1/jobs` | 按模型组装 payload，共用轮询归档 |

高级调用 `/v1/jobs` 接收 `{"model":"服务模型ID","payload":{原始渠道字段}}`；路由与真实 model 字段由服务控制，不允许调用者传任意上游 URL。所有异步结果查询 `/v1/jobs/{id}`。

## 参数差异

- Gemini Omni：顶层 prompt、images、duration，metadata.task；原图 URL 转 Base64。
- Veo：prompt、images（最多 3 张）、duration、resolution、metadata；本轮文生视频 8 秒 720p。
- Seedance：content 包含 text/image_url/video_url，duration、ratio、resolution；1.5 使用统一视频路由，2.x 使用 v3。尚未获得权限实测的版本仍须验收。
- Wan 2.6：t2v 为 input.prompt + parameters.size；i2v 为 input.img_url；r2v 为 input.reference_urls。
- Wan 2.7/3.0：input.media 类型区分 first_frame、reference_image、reference_video；videoedit 的源视频类型是 video，时长取源视频。
- DreamActor：人物 image_urls 或 binary_data_base64 二选一且仅 1 张，video_url 为动作模板；不能拿风景视频当有效验收素材。图片 ≤4.7MB，视频 ≤30秒，结果 URL 仅有效 1 小时。
- Wan 图片使用 input.messages[].content[].text/image 和 parameters；其他图片使用 prompt/image。Seedream 走同步接口，返回 data[].url。

## 测试方法与边界

- Agent 批次：`overseas-f653fed1afda4d1285452b363910dae5`；所有真实请求使用 code-agent 来源、独立幂等键、数据库工单与用量。
- 每模型最小有效调用一次；未自动重发失败或不确定请求。并发提交上限 3；服务端仍遵守用户/模型/渠道限制。
- 首轮发现当前 Key 权限与公开目录不同；后续运行增加只读 /v1/models 权限预检。部分文本在本地并发限制阶段被拒绝，不能算已到渠道。
- 成功只表示本轮参数组合成功；不表示所有图生/编辑/流式/续编组合均已真实验证。
- 缺少 usage 的成功任务保留空用量，不能凭空计算真实成本。公开报价不等于账户实际费率；保持管理员配置。

当前 Key 可见模型：gemini-3.8-flash, gemini-omni-flash-preview, veo-3.1-fast-generate-preview, veo-3.1-generate-preview。

## 逐模型证据

| 模型 | 类型 | Key 权限 | 本轮状态 | 工单/原因 |
|---|---|---|---|---|
| `svip-claude-sonnet-4-6` | TEXT | 未开放 | failed | job-57d3d9223d36475bb16be535882cf012；Provider rejected the chat request |
| `svip-claude-opus-4-7` | TEXT | 未开放 | failed | job-15b22f289d124725b359363f00617d51；Provider rejected the chat request |
| `gemini-3.6-flash` | TEXT | 未开放 | failed | job-59755077b9f44ec59a52853feb0ccd56；Provider rejected the chat request |
| `gpt-5.5` | TEXT | 未开放 | failed | job-99062b8453d044179b45bc2fa225a21b；Provider rejected the chat request |
| `gemini-3.5-flash` | TEXT | 未开放 | failed | job-a1614316d8a6495fa0cd6796b81f1411；Provider rejected the chat request |
| `gemini-2.5-pro` | TEXT | 未开放 | failed | job-54b421b8575046098e038de014deedf5；Provider rejected the chat request |
| `gpt-image-2` | IMAGE | 未开放 | failed | job-3fae86f62a834ba58450bb4384bf427f；当前key未启用该模型:gpt-image-2 |
| `gemini-3.1-pro-preview` | TEXT | 未开放 | failed | job-fb65eb7a81604ff7870ef09b846821fe；Provider rejected the chat request |
| `svip-gpt-6-astra` | TEXT | 未开放 | failed | job-290ccf1f74ee48bc91c59d55cb831f50；Provider rejected the chat request |
| `gpt-5.6-sol` | TEXT | 未开放 | failed | job-7cb51b0943d848babeb211e040ecdda8；Provider rejected the chat request |
| `svip-claude-sonnet-5` | TEXT | 未开放 | not_submitted | Provider catalog missing API path/base URL |
| `svip-claude-opus-4-5-20251101` | TEXT | 未开放 | failed | job-5f40a67181a24236bd85e8dc5b8f3377；Provider rejected the chat request |
| `svip-gemini-3.1-flash-image-preview` | IMAGE | 未开放 | failed | job-a4677a077f8e4d4dab6b3b3820d6963c；当前key未启用该模型:svip-gemini-3.1-flash-image-preview |
| `svip-claude-fable-5` | TEXT | 未开放 | failed | job-94451590d52d49bbb82adc7eb211558a；Provider rejected the chat request |
| `svip-claude-haiku-4-5-20251001` | TEXT | 未开放 | failed | job-b6bc745efb534ce6b436208c78dcf456；Provider rejected the chat request |
| `seedream-4.0` | IMAGE | 未开放 | failed | job-0a647fce1dc0448d955b38c15c1bc2b7；Provider HTTP 403: Provider rejected the request |
| `svip-gemini-3.7-flash` | TEXT | 未开放 | failed | job-e48edf31d6b44654ab6b63bc3a72b4e2；Provider rejected the chat request |
| `dreamina-seedance-2.5` | VIDEO | 未开放 | failed | job-4606f81f823a4160bd0c471cd9618b29；当前key未启用该模型:dreamina-seedance-2.5 |
| `grok-4.5` | TEXT | 未开放 | failed | job-f84e2683b0094df2827b2089f36060fa；Provider rejected the chat request |
| `svip-gpt-image-2` | IMAGE | 未开放 | failed | job-5ec36a1c62a04ea680aea6d4c849476c；当前key未启用该模型:svip-gpt-image-2 |
| `dreamactor-m2.0` | VIDEO | 未开放 | not_submitted | Need person motion video; existing smoke fixture is a landscape, not a valid motion input |
| `z-claude-fable-5-1` | TEXT | 未开放 | not_submitted | Provider catalog missing API path/base URL |
| `svip-gpt-5.5` | TEXT | 未开放 | failed | job-7ae4915c4baa4533860b51e67981da05；Provider rejected the chat request |
| `svip-gpt-5.6-luna` | TEXT | 未开放 | failed | job-b596a9adc1aa498d91c9b3f4ec0b9779；Provider rejected the chat request |
| `svip-gemini-3.8-flash` | TEXT | 未开放 | failed | job-d3f16abba2054757864d2525cda443f6；Provider rejected the chat request |
| `svip-gemini-3.1-pro-preview` | TEXT | 未开放 | failed | job-d19bd1ecb50d4e1a8105f601779cf7cc；Provider rejected the chat request |
| `svip-claude-sonnet-4-5-20250929` | TEXT | 未开放 | failed | job-93a50a4f71424a79bdc9fe6e0db8a4eb；Provider rejected the chat request |
| `svip-gemini-3-flash-preview` | TEXT | 未开放 | failed | job-b2cb3b46de2a48ae946f3a0db0d08552；Provider rejected the chat request |
| `gemini-3.7-flash` | TEXT | 未开放 | failed | job-8a64bc67e2a148d786f7dbbe420e5f05；Provider rejected the chat request |
| `gemini-2.5-flash-lite` | TEXT | 未开放 | failed | job-b5c5178788b74265b72f1ed2b8d89ab3；Provider rejected the chat request |
| `gemini-3-pro-image-preview` | IMAGE | 未开放 | failed | job-9f3611ba8bda4e5ba48d53f1dda4a0d0；当前key未启用该模型:gemini-3-pro-image-preview |
| `s-gpt-image-2` | IMAGE | 未开放 | failed | job-b75b312c6db54eae8d709ccd1e756739；当前key未启用该模型:s-gpt-image-2 |
| `claude-opus-5` | TEXT | 未开放 | failed | job-308a4952004a4c65ae5a4c26bb339c67；Provider rejected the chat request |
| `svip-claude-opus-4-8` | TEXT | 未开放 | failed | job-0e2065016ce84ebb86623be3f68b1128；Provider rejected the chat request |
| `svip-gemini-3.6-flash` | TEXT | 未开放 | failed | job-189d6076c0b644ea8810138a5518e2d1；Provider rejected the chat request |
| `svip-claude-opus-4-6` | TEXT | 未开放 | failed | job-0ad1477aa5be40f7aa2d7b6ef456572e；Concurrency limit reached |
| `gemini-2.5-flash` | TEXT | 未开放 | failed | job-498a9962d8654eaea5e6ffa6731c39d0；Provider rejected the chat request |
| `gemini-2.5-flash-image` | IMAGE | 未开放 | failed | job-ff500ca1641c4f66b222f717575364e9；当前key未启用该模型:gemini-2.5-flash-image |
| `z-claude-fable-5` | TEXT | 未开放 | not_submitted | Provider catalog missing API path/base URL |
| `z-claude-sonnet-5` | TEXT | 未开放 | failed | job-78045a008bfd47ce81cb75273d9d04af；Provider rejected the chat request |
| `gpt-5.6-terra` | TEXT | 未开放 | failed | job-82e78c8b6f3f43848b4e0d8501f6b429；Concurrency limit reached |
| `svip-gemini-3-pro-image-preview` | IMAGE | 未开放 | failed | job-0c29c55ff925461295fc875711ca149e；当前key未启用该模型:svip-gemini-3-pro-image-preview |
| `svip-gemini-3.1-flash-lite-preview` | TEXT | 未开放 | failed | job-4de1b30853da420e8db3f83a21a839a3；Concurrency limit reached |
| `gemini-3.1-flash-lite-preview` | TEXT | 未开放 | failed | job-aa199e20d665480fb4b8be9bc29e58fc；Concurrency limit reached |
| `gpt-5.4-mini` | TEXT | 未开放 | failed | job-5cfeee0655e54e7288a31e85e27a2642；Concurrency limit reached |
| `svip-gemini-3.5-flash` | TEXT | 未开放 | failed | job-b4751f13736b4d8f98dc93da7141c691；Provider rejected the chat request |
| `gemini-3-flash-preview` | TEXT | 未开放 | failed | job-d497541ed6ba442d886d82133c742a34；Provider rejected the chat request |
| `gemini-3.8-flash` | TEXT | 有 | succeeded | job-91e9ea38076f4f72b92e7fcd7b1bb433 |
| `grok-4.6` | TEXT | 未开放 | failed | job-f64b155bdab84759bbaff715fcf3d0f5；Provider rejected the chat request |
| `dreamina-seedance-2.0-mini` | VIDEO | 未开放 | failed | job-9b7302f916eb4c5eac9791df2c895455；当前key未启用该模型:dreamina-seedance-2.0-mini |
| `gemini-3.1-flash-image-preview` | IMAGE | 未开放 | failed | job-ed244ac43a9c47fb884ae08ac2dc5ba9；当前key未启用该模型:gemini-3.1-flash-image-preview |
| `claude-opus-4-6` | TEXT | 未开放 | failed | job-dcdbcd8c2cbc4386ac8e7ed01c92e058；Provider rejected the chat request |
| `svip-gpt-5.6-sol` | TEXT | 未开放 | failed | job-99e41e347ab84383bc7daf297475735e；Provider rejected the chat request |
| `svip-gpt-5.6-terra` | TEXT | 未开放 | failed | job-d3336937f8a5427e80db49b0d0a63f2a；Provider rejected the chat request |
| `svip-gpt-5.4` | TEXT | 未开放 | failed | job-b129e9e6a76645878e329b247170d111；Provider rejected the chat request |
| `claude-fable-5` | TEXT | 未开放 | failed | job-b3ac63bc5fa441dbbb536d7e4bc4b234；Provider rejected the chat request |
| `z-claude-opus-5` | TEXT | 未开放 | failed | job-2123ee203dc642b79d71e236743159d3；Provider rejected the chat request |
| `svip-gpt-5.4-mini` | TEXT | 未开放 | failed | job-72582b15d2f347c981c75a15df8ca9c5；Provider rejected the chat request |
| `wan2.6-r2v-sg` | VIDEO | 未开放 | failed | job-60ec8454c49648238f5b1f51f3f6f88b；当前key未启用该模型:wan2.6-r2v-sg |
| `wan2.6-image-sg` | IMAGE | 未开放 | failed | job-d26b15b9481044a8be0559860dcab665；当前key未启用该模型:wan2.6-image-sg |
| `wan2.6-t2v-sg` | VIDEO | 未开放 | failed | job-9375d0b3d205485f85d8e86a64f0004d；当前key未启用该模型:wan2.6-t2v-sg |
| `wan2.6-t2i-sg` | IMAGE | 未开放 | failed | job-2a12bf50f81d40c5b0f4f2d2dcf1dde3；当前key未启用该模型:wan2.6-t2i-sg |
| `wan2.6-i2v-sg` | VIDEO | 未开放 | failed | job-46ba6fe80e25481a984853855580f3c3；当前key未启用该模型:wan2.6-i2v-sg |
| `seedream-4.5` | IMAGE | 未开放 | failed | job-fdaa2ccd25204918870942bfd7b0ce2f；Provider HTTP 403: Provider rejected the request |
| `dreamina-seedance-2.0` | VIDEO | 未开放 | failed | job-bc31b6c6e4334954bb834f0f94904616；当前key未启用该模型:dreamina-seedance-2.0 |
| `dreamina-seedance-2.0-fast` | VIDEO | 未开放 | failed | job-58533efa44ac47aab5a83f1e713849f3；当前key未启用该模型:dreamina-seedance-2.0-fast |
| `wan2.7-r2v-sg` | VIDEO | 未开放 | failed | job-0274e7d8181947e289ee69e4629ac532；当前key未启用该模型:wan2.7-r2v-sg |
| `seedream-5.0` | IMAGE | 未开放 | failed | job-339ffa495ae342bf9253a0b3e7b947e6；Provider HTTP 403: Provider rejected the request |
| `wan2.7-image-sg` | IMAGE | 未开放 | failed | job-c669329958444024823ddcaf2f7e838b；当前key未启用该模型:wan2.7-image-sg |
| `wan2.7-videoedit-sg` | VIDEO | 未开放 | failed | job-0f58ad25f8e14a8791108049fc806b72；当前key未启用该模型:wan2.7-videoedit-sg |
| `wan2.7-i2v-sg` | VIDEO | 未开放 | failed | job-9ff414d65fd047929e0d89b0c4f85f4a；当前key未启用该模型:wan2.7-i2v-sg |
| `claude-haiku-4-5-20251001` | TEXT | 未开放 | failed | job-75493d7a53444dd095594477cec7d3c9；Provider rejected the chat request |
| `dola-seedream-5.0-pro` | IMAGE | 未开放 | failed | job-80de9f2d87314c61b586cbd6f01d9e44；Provider HTTP 403: Provider rejected the request |
| `wan3.0-video-sg` | VIDEO | 未开放 | failed | job-dd0d26907adb444fa9c244c3d7e3e8ab；当前key未启用该模型:wan3.0-video-sg |
| `wan3.0-video-prime-sg` | VIDEO | 未开放 | failed | job-af8cfc81514948cab2e40ef106a26b02；当前key未启用该模型:wan3.0-video-prime-sg |
| `claude-opus-4-7` | TEXT | 未开放 | failed | job-45deec90f17940e5b458f0c87eac2eb4；Provider rejected the chat request |
| `claude-sonnet-4-6` | TEXT | 未开放 | failed | job-b855404dadff4c3b81a9b0915612ae36；Provider rejected the chat request |
| `codex-auto-review` | TEXT | 未开放 | failed | job-c88998b2d78943eab749a5835de2c8b2；Provider rejected the chat request |
| `claude-opus-4-8` | TEXT | 未开放 | failed | job-57b7d725a3e6479b90d27fd0ce19a0f2；Provider rejected the chat request |
| `grok-4.3` | TEXT | 未开放 | failed | job-d6ba2b36f3934061815386f46a0a4dde；Provider rejected the chat request |
| `gpt-6-astra` | TEXT | 未开放 | failed | job-6a48f056443d4c54bdd83fbb2a2c3d18；Provider rejected the chat request |
| `seedream-4.0-filter` | IMAGE | 未开放 | failed | job-0cbb699c62a840c0b3d8554dc7c58ef4；Provider HTTP 403: Provider rejected the request |
| `seedream-4.5-filter` | IMAGE | 未开放 | failed | job-d67abbaf163044b49aa4ef030e5ce12e；Provider HTTP 403: Provider rejected the request |
| `seedream-5.0-filter` | IMAGE | 未开放 | failed | job-d5c688a896954d188227ae7316cfb7b5；Provider HTTP 403: Provider rejected the request |
| `dreamina-seedance-1.5-pro` | VIDEO | 未开放 | failed | job-ee364f0861454c7b83d7cab1760688a4；当前key未启用该模型:dreamina-seedance-1.5-pro |
| `claude-sonnet-5` | TEXT | 未开放 | failed | job-4668adeee3f94d75b2c40138633c374d；Provider rejected the chat request |
| `veo-3.1-generate-preview` | VIDEO | 有 | succeeded | job-a84ebd2e69554ebdb4b9c6a05c10d56d |
| `veo-3.1-fast-generate-preview` | VIDEO | 有 | succeeded | job-74e41c48899740e98bf9a74c31a57bf5 |
| `gemini-omni-flash-preview` | VIDEO | 有 | succeeded | job-d63073e4bea84ab188f59b886ab75f85 |
| `claude-fable-5-1` | TEXT | 未开放 | failed | job-4cd950cb805e4235949fa79d2d524bdc；Provider rejected the chat request |
| `dola-seedream-5.0-pro-filter` | IMAGE | 未开放 | failed | job-2fcf647ba9b344f584c2c50905f95efb；Provider HTTP 403: Provider rejected the request |
| `gpt-image-2.5-flare` | IMAGE | 未开放 | failed | job-07775eeba6ad4d65b9bf2b119d93e72d；当前key未启用该模型:gpt-image-2.5-flare |
| `gpt-image-2.5-sunburst` | IMAGE | 未开放 | failed | job-5e6497c3088f4ec69630894751a5be78；当前key未启用该模型:gpt-image-2.5-sunburst |
| `s-gpt-image-2.5-flare` | IMAGE | 未开放 | failed | job-928ec59af0d148748fc7541f04267379；当前key未启用该模型:s-gpt-image-2.5-flare |
| `s-gpt-image-2.5-sunburst` | IMAGE | 未开放 | failed | job-acd440715b1341f0949767c20ad2a06c；当前key未启用该模型:s-gpt-image-2.5-sunburst |
| `svip-gpt-image-2.5-flare` | IMAGE | 未开放 | failed | job-2905248cac5c4088810147ab073a6f75；当前key未启用该模型:svip-gpt-image-2.5-flare |
| `svip-gpt-image-2.5-sunburst` | IMAGE | 未开放 | failed | job-26bdd0943aab429a89010e306df2b717；当前key未启用该模型:svip-gpt-image-2.5-sunburst |

## 本轮成功结果的实际规格

| 模型 | 请求 | 实际结果 | 用量 |
|---|---|---|---|
| Gemini 3.8 Flash | 最多 32 输出 Token | 成功返回 OK | 输入 259、输出 17、合计 276 Token |
| Veo 3.1 标准 | 8 秒 720p | 1280×720，24fps，8 秒 | 查询未提供 tokenUsage |
| Veo 3.1 快速 | 8 秒 720p | 1280×720，24fps，8 秒 | 查询未提供 tokenUsage |
| Gemini Omni | 5 秒 720p | 1280×720，24fps，10 秒；时长不符合请求 | 查询未提供 tokenUsage |

Gemini Omni 本轮只能算生成链路成功，不能算时长遵循验收通过。缺失用量不能记为零成本，仍需渠道账单或计费规则补充。

## 尚需完成

- 为当前海外 Key 开放其余模型；缺少接口配置的 3 个文本模型需渠道补全。
- DreamActor 准备合规人物动作模板后单独验收。
- 对尚未到达渠道/被权限拒绝的项，开通后使用新的明确批次补测；原有不确定任务先对账，不自动重发。
- 完成基础单模型验收后，再按图生、视频编辑、流式、续编等能力补齐模式覆盖与并发压力验收。
