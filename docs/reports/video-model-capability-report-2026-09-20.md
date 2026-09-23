# 视频生成模型能力、并发与成本汇报（历史盘点）

盘点日期：2026-09-20

数据口径：盘点当日线上模型注册配置、供应商适配代码、生成工单与费用规则，不代表当前部署状态。

> 退役修订：PPIO 与 BFL（Black Forest Labs，历史 FLUX 3）已从 MV 与 model-service 移除支持。下文能力与调用参数表已移除其条目，仅在明确标注的历史费用、成片证据中保留必要记录；不得用于新调用、配置或补测。其他模型的历史能力也不等同于当前启用状态，以现行模型目录和验收边界为准。

## 一、管理摘要

- 盘点当日用户侧曾展示 15 个视频模型，覆盖六个渠道；其中 PPIO、BFL 已退役，该数量不是当前模型数。其余渠道为英和、英和海外、RunningHub、ToAPIs。
- 当时生产主力模型池上限为 200；英和海外三款为 20；RunningHub 为 2；ToAPIs 测试模型为 1。此处不提供已退役渠道的执行池配置。
- 当时已确认的结算价格主要集中在 SD2.0、H3、Wan3.0 系列。Kling、英和海外、Grok 的人民币结算表当时仍有缺项；已退役渠道费用仅作历史核账依据。
- 当时共 12 个模型有视频 Demo；H3（英和）、Grok Video 1.5 缺稳定链接。退役渠道的既有媒体证据见第五节，不再安排补生成。

## 二、模型能力总表（已剔除退役渠道）

“参考图方式”描述盘点当日系统实现，不等同于供应商理论能力或当前支持承诺。

| 模型 | 渠道 | 盘点时支持的生成方式 | 图片上限 | 视频/音频参考 | 时长 | 清晰度 | 画幅 | 系统并发上限 |
|---|---|---|---:|---|---|---|---|---:|
| SD2.0（英和） | 英和 | 文生视频、多参考图生视频 | 10 | 不支持 | 4–15 秒 | 由线上能力配置下发，当前常用 480P/720P/1080P | 16:9、9:16、4:3、1:1 | 200 |
| SD2.0 Mini（英和） | 英和 | 文生视频、多参考图生视频 | 10 | 不支持 | 4–15 秒 | 480P、720P | 16:9、9:16、4:3、1:1 | 200 |
| SD2.0 Fast（英和） | 英和 | 文生视频、多参考图生视频 | 10 | 不支持 | 4–15 秒 | 480P、720P | 16:9、9:16、4:3、1:1 | 200 |
| H3（英和） | 英和 | 文生、首帧、首尾帧、参考图/视频/音频 | 6 | 视频 1、音频 3；音频不能单独输入 | 4–15 秒 | 768P、2K | 16:9、9:16、4:3、1:1 | 200 |
| Wan3.0（英和） | 英和 | 文生、首帧、首尾帧、参考图/视频/音频 | 系统请求上限 10 | 代码支持视频/音频字段；供应商边界待确认 | 4–15 秒 | 480P、720P、1080P | 16:9、9:16、4:3、1:1 | 200 |
| Wan3.0 Prime（英和） | 英和 | 文生、首帧、首尾帧、参考图/视频/音频 | 系统请求上限 10 | 代码支持视频/音频字段；供应商边界待确认 | 4–15 秒 | 480P、720P、1080P | 16:9、9:16、4:3、1:1 | 200 |
| Kling V3（英和） | 英和 | 文生、首帧及多参考图 | 系统请求上限 10 | 不支持 | 4–15 秒 | 720P、1080P | 16:9、9:16、1:1 | 200 |
| Veo 3.1（英和海外） | 英和海外 | 文生、单图生视频 | 1 | 不支持 | 4–15 秒 | 720P、1080P、4K | 16:9、9:16 | 20 |
| Veo 3.1 Fast（英和海外） | 英和海外 | 文生、单图生视频 | 1 | 不支持 | 4–15 秒 | 720P、1080P、4K | 16:9、9:16 | 20 |
| Gemini Omni Flash（英和海外） | 英和海外 | 文生、单图生、多参考图生视频 | 6 | 不支持 | 4–10 秒 | 固定 720P | 16:9、9:16 | 20 |
| Grok Video 1.5（ToAPIs） | ToAPIs | 文生、单首帧、多参考图 | 7 | 不支持 | 6–10 秒 | 480P、720P | 16:9、9:16、1:1 | 1 |
| H3（RunningHub） | RunningHub | 文生、首帧、首尾帧、参考图/视频/音频 | 6 | 视频 1、音频 3；总文件 10 | 4–15 秒 | 0.4MP、0.9MP、1.8MP | 16:9、9:16、4:3、1:1 | 2 |

## 三、历史价格与计费方式

“生成前估价”曾用于余额预检；“对账方式”记录盘点时的工单核算口径。两者可能不同；历史价格不能直接用于新任务。

| 模型 | 生成前估价 | 当前对账方式 | 折扣/备注 | 明确程度 |
|---|---:|---|---|---|
| SD2.0（英和） | ¥0.83/秒 | 480P/720P：¥46/百万输出 Token；1080P：¥51/百万输出 Token | 对账乘 83% | 已确认 |
| SD2.0 Mini（英和） | ¥0.50/秒 | 480P/720P：¥23/百万输出 Token | 暂无折扣配置 | 已录入，需业务确认最终结算 |
| SD2.0 Fast（英和） | ¥0.80/秒 | 480P/720P：¥37/百万输出 Token | 暂无折扣配置 | 已录入，需业务确认最终结算 |
| H3（英和） | ¥0.425/秒 | ¥0.425/输出秒 | 768P 已配置；2K 报价空缺 | 768P 已确认 |
| Wan3.0（英和） | 720P ¥0.60/秒 | 480P ¥0.30；720P ¥0.60；1080P ¥1.20/输出秒 | 当前为官方华北 2 原价 | 待供应商账单复核 |
| Wan3.0 Prime（英和） | 720P ¥0.90/秒 | 480P ¥0.45；720P ¥0.90；1080P ¥1.80/输出秒 | 当前为官方华北 2 原价 | 待供应商账单复核 |
| Kling V3（英和） | ¥0.80/秒 |  | 当前无价格规则，工单对账显示未定价 | 待补 |
| Veo 3.1（英和海外） | ¥2.88/秒 |  | 按公开美元价及 7.2 汇率做生成前估算 | 待英和海外结算表 |
| Veo 3.1 Fast（英和海外） | ¥0.72/秒 |  | 同上 | 待英和海外结算表 |
| Gemini Omni Flash（英和海外） | ¥0.72/秒 |  | 同上 | 待英和海外结算表 |
| Grok Video 1.5（ToAPIs） | ¥0.137664/秒 |  | 当前 Key 的 720P 目录价 $0.01912/秒，测试额度 1000 积分 | 待补积分与美元/人民币结算关系 |
| H3（RunningHub） | 不参与余额预检 | 记录 RunningHub 币，当前排除人民币对账 | 仅测试 | 人民币换算待补 |

### 已退役渠道的历史核账口径（非生效费率）

仅用于解释旧账单，不导回 seed、价格规则或余额预检；新库与存量库均不得据此恢复渠道。

| 已退役模型 | 盘点时核账口径 | 保留原因 |
|---|---|---|
| FLUX 3（BFL） | 1 Credit = $0.01；当时 HD 文生/图生报价 $0.17/秒 | 已有一笔 85 Credits / $0.85 实扣，见第五节；不再补齐其他模式报价 |
| SD2.0（PPIO） | 480P/720P：¥46/百万输出 Token；1080P：¥51/百万输出 Token；对账乘 80% | 解释历史费用，不是当前计价配置 |
| H3（PPIO） | 基础价 ¥0.50/输出秒，对账乘 85%；当时 768P/2K 共用 | 解释历史费用，不是当前计价配置 |

## 四、盘点时的调用参数（已剔除退役渠道）

### 1. Seedance 2.0 系列：英和

- 接口：`POST /v3/video/tasks`
- 关键参数：`model`、`content[]`、`generate_audio`、`ratio`、`resolution`、`duration`、`watermark`、`return_last_frame`
- `content` 首项为 `{type: text, text: prompt}`；参考图追加为 `{type: image_url, role: reference_image, image_url: {url}}`
- Mini/Fast 共用该协议，模型名分别为 `doubao-seedance-2.0-mini`、`doubao-seedance-2.0-fast`

### 2. MiniMax H3：英和

- 英和接口：`POST /video/generation/tasks`
- 关键参数：`model=MiniMax-H3`、`content[]`、`resolution`、`duration`、`ratio`、`aigc_watermark`
- 图片角色：`reference_image`、`first_frame`、`last_frame`
- 视频角色：`reference_video`；音频角色：`reference_audio`
- 内部 720P/1080P 分别映射供应商 768P/2K

### 3. H3：RunningHub

- 根据模式调用独立工作流：T2VA、I2VA、FL2VA、Ref2VA
- 关键参数：提示词、时长、画幅、参考媒体文件名、阶段一/阶段二百万像素、是否生成音频
- 参考视频和音频单段 2–15 秒，总时长不超过 15 秒；音频必须同时配有图片或视频

### 4. Wan3.0 / Wan3.0 Prime

- 接口：`POST /video/generation/tasks`
- 关键参数：`model`、`input.prompt`、`input.media[]`、`parameters.resolution`、`parameters.ratio`、`parameters.duration`、`parameters.audio`、`parameters.watermark`
- 媒体类型：`first_frame`、`last_frame`、`reference_image`、`reference_video`、`reference_audio`

### 5. Kling V3

- 接口：`POST /video/generation/tasks`
- 关键参数：`model_name=kling-v3`、`prompt`、`duration`、`mode`、`aspect_ratio`、`sound`、`cfg_scale=0.5`、`image_list[]`
- 720P 映射 `mode=std`；1080P 映射 `mode=pro`
- 第一张图片标为 `first_frame`，后续图片标为 `reference`

### 6. Veo 3.1 / Veo 3.1 Fast

- 接口：`POST /video/generation/tasks`
- 关键参数：`model`、`prompt`、`duration`、`images[]`、`size`、`resolution`、`metadata.aspectRatio`、`metadata.resolution`
- 720P/1080P/4K 根据画幅映射实际宽高，例如 16:9 的 720P 为 `1280x720`

### 7. Gemini Omni Flash

- 接口：`POST /video/generation/tasks`
- 关键参数：`model=gemini-omni-flash-preview`、`prompt`、`duration`、`images[]`、`metadata.aspect_ratio`、`metadata.task`
- `metadata.task`：`text_to_video`、`image_to_video`、`reference_to_video`

### 8. Grok Video 1.5

- 接口：`POST /v1/videos/generations`
- 关键参数：`model=grok-video-1.5`、`prompt`、`video_generation_mode`、`duration`、`resolution`、`aspect_ratio`、`client_business_id`
- 单图使用 `image`；多图使用 `reference_images[]`
- 模式：`text_to_video`、`first_frame_image_to_video`、`reference_images_to_video`

历史请求使用系统生成的稳定 `Idempotency-Key`。任何另行获准的 Agent 真实测试仍必须携带 `X-Agent-Name: code-agent`、本次运行唯一的 `X-Agent-Run-Id` 与 `X-Test-Run-Id`；本报告不构成调用授权。

## 五、视频 Demo

| 模型 | Demo | 已验证规格 | 备注 |
|---|---|---|---|
| SD2.0（英和） | [播放](https://media-generate-chouka.tos-cn-beijing.volces.com/mv-agent/generated-videos/users/user-c9e1923122714b0e9fce58aa7d20263d/generated/videos/65479964e095-cgt-20260920154642-nflca.mp4) | 1280×720，12.04 秒 | TOS 稳定链接 |
| SD2.0 Mini（英和） | [播放](https://media-generate-chouka.tos-cn-beijing.volces.com/mv-agent/generated-videos/users/user-c9e1923122714b0e9fce58aa7d20263d/generated/videos/e63b82e53183-cgt-20260920122658-8h1v9.mp4) | 864×496，4.04 秒 | 请求档位 480P |
| SD2.0 Fast（英和） | [播放](https://media-generate-chouka.tos-cn-beijing.volces.com/mv-agent/generated-videos/users/user-c9e1923122714b0e9fce58aa7d20263d/generated/videos/795c7e54fd56-cgt-20260920122658-2nxs1.mp4) | 864×496，4.04 秒 | 请求档位 480P |
| H3（英和） |  |  | 待补稳定 Demo |
| Wan3.0（英和） | [播放](https://media-generate-chouka.tos-cn-beijing.volces.com/mv-agent/generated-videos/users/user-c9e1923122714b0e9fce58aa7d20263d/generated/videos/4b88cf3ca1c1-wan-200221df-8da4-4590-a5ab-5a2955c8092b.mp4) | 854×480，5 秒 | 30 FPS |
| Wan3.0 Prime（英和） | [播放](https://media-generate-chouka.tos-cn-beijing.volces.com/mv-agent/generated-videos/users/user-c9e1923122714b0e9fce58aa7d20263d/generated/videos/a1703724f568-wan-323d86b9-216d-42d3-ab6a-839c49ce2742.mp4) | 854×480，5 秒 | 30 FPS |
| Kling V3（英和） | [播放](https://media-generate-chouka.tos-cn-beijing.volces.com/mv-agent/generated-videos/users/user-c9e1923122714b0e9fce58aa7d20263d/generated/videos/0c8ba01d14db-kling-1403774432-AigcVideoTask-dc3a8b98286bce7596968b52b5948c1ft.mp4) | 1280×720，4.04 秒 | 请求档位 720P |
| Veo 3.1（英和海外） | [播放](https://media-generate-chouka.tos-cn-beijing.volces.com/mv-agent/generated-videos/users/user-497d8eda84ad4377b808b55db09fe71b/generated/videos/9f2bbcedf7d3-veo-3.1-generate-preview-task_YonNgKHalwoo8LdPp4GecpYQz1tV4AtT.mp4) | 1280×720，4 秒 | TOS 稳定链接 |
| Veo 3.1 Fast（英和海外） | [播放](https://media-generate-chouka.tos-cn-beijing.volces.com/mv-agent/generated-videos/users/user-497d8eda84ad4377b808b55db09fe71b/generated/videos/a68150eb1e50-veo-3.1-fast-generate-preview-task_GwA4JDZ2EwPXI24tiaPgBsAmesp4BJeT.mp4) | 1280×720，4 秒 | TOS 稳定链接 |
| Gemini Omni Flash（英和海外） | [播放](https://media-generate-chouka.tos-cn-beijing.volces.com/mv-agent/generated-videos/users/user-497d8eda84ad4377b808b55db09fe71b/generated/videos/b20002b67b1b-gemini-omni-flash-preview-task_idH5keGNOMHXqPeL3QioX718hL4ntbqd.mp4) | 1280×720，实际 10.01 秒 | 请求时长 4 秒，供应商实际返回 10 秒，需确认时长语义 |
| Grok Video 1.5（ToAPIs） |  |  | 待补稳定 Demo |
| H3（RunningHub） | [播放](https://media-generate-chouka.tos-cn-beijing.volces.com/mv-agent/generated-videos/users/user-497d8eda84ad4377b808b55db09fe71b/generated/videos/7d4b73b21f7a-h3-2093183704787812353.mp4) | 1280×736，4.46 秒 | 0.9MP 档位 |

### 已退役渠道的历史成片与费用证据

以下仅用于追溯既有工单，链接不代表当前支持。不得补生成、恢复调用或删除原媒体；历史费用与 Agent 归因保留。

| 已退役模型 | 历史媒体 | 当时记录规格 | 历史事实 |
|---|---|---|---|
| FLUX 3（BFL，已退役） | [历史成片](https://media-generate-chouka.tos-cn-beijing.volces.com/mv-agent/generated-videos/users/user-497d8eda84ad4377b808b55db09fe71b/generated/videos/a682d7a326ea-flux-3-bfl-test-88e4d4d4-563b-447a-8bb4-d3526b8f2192.mp4) | 5 秒，HD，16:9 | 实扣 85 Credits，即 $0.85 |
| SD2.0（PPIO，已退役） | 无稳定视频 URL | 1920×1080，4 秒 | 仅保留原规格记录，不再补测 |
| H3（PPIO，已退役） | [历史成片](https://media-generate-chouka.tos-cn-beijing.volces.com/mv-agent/generated-videos/users/user-497d8eda84ad4377b808b55db09fe71b/generated/videos/99964ceb1cc1-h3-435550529470738.mp4) | 1344×768，4.46 秒 | 请求档位 720P，供应商档位 768P |

## 六、盘点时的待确认项（仅保留未退役模型）

以下是当时的信息缺口，不构成新测试授权；是否仍未解决以现行费率及验收文档为准。

1. Kling V3 的 720P/1080P 结算单价及是否存在渠道折扣。
2. H3（英和）2K 档位的每秒价格；当前只录入了 768P 的 ¥0.425/秒。
3. SD2.0 Mini、SD2.0 Fast 的报价是否需要渠道折扣，当前按基础 Token 价格核算。
4. Wan3.0 与 Wan3.0 Prime 是否沿用官方华北 2 原价，还是使用英和实际折扣价。
5. 英和海外 Veo 3.1、Veo 3.1 Fast、Gemini Omni Flash 的人民币结算价、分辨率价差与折扣。
6. ToAPIs 1000 积分的购买成本、积分扣减规则、各分辨率和生成模式的实际价格。
7. RunningHub 币与人民币的换算规则，以及是否需要纳入正式对账。
8. Wan3.0/Wan3.0 Prime 参考图片、视频、音频的供应商数量与时长边界。
9. SD2.0（英和）线上能力中 480P/720P/1080P 的最终公开范围，当时模型种子依赖供应商动态能力。
10. Gemini Omni Flash 请求 4 秒、实际返回约 10 秒的计费口径与产品展示口径。
11. H3（英和）、Grok Video 1.5 的领导汇报用稳定 Demo 链接。

## 七、口径说明

- 并发上限为系统执行池限流值，不代表供应商合同保证的 QPS 或同时生成额度。
- 所有价格均应以生效中的供应商报价单和实际账单为最终依据。
- 失败工单在管理后台保留并明确标识；无供应商有效用量时费用为 0。
- Demo 仅证明指定参数下曾成功生成，不代表所有模式和清晰度均已完成验收。
