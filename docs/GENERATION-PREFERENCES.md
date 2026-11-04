# 用户级模型与渠道偏好

## 约定

文本、图片、视频分别保存一份用户偏好，所有项目共用。模型菜单每一行提供渠道入口；“自动（平台推荐）”存为 `null`，发送平台请求时省略 `channel`。指定渠道使用平台公开渠道键，原样传给同一个模型，不允许客户端在失败时换模型或改为自动渠道。

偏好只影响后续提交。已经排队、运行或恢复执行的工单使用自己的请求快照，不重新读取用户当前偏好。更改比例等参数不能自动替换模型；不兼容配置由界面提示或服务端校验拒绝。

## 数据与 API

- `users.generation_preferences`：按 `text`、`image`、`video` 保存 `{model, channel}`；通过 Alembic 版本 `d6b72a91e430` 新增。
- `GET /api/generation-preferences`：当前登录用户偏好。
- `PUT /api/generation-preferences/{modality}`：校验模型类型、启用和可见状态，指定渠道还要检查平台可用目录；写入失败保留原选择。
- `GET /api/model-options/{model}/channels`：使用模型的 `provider_model_id` 查询当前环境平台的 `/v1/models/{id}/channels?available_only=true`。不跨环境兜底，不向浏览器暴露平台 Key。
- 图片、视频工单保存 `model/channel`；文本工单保存 `_textSelection`，执行时通过 ContextVar 恢复并在结束后清理。
- 文本请求使用 OpenAI SDK `extra_body.channel`，媒体请求使用顶层 `channel`。自动模式不发送该字段。

新用户未保存偏好时保留原默认配置。旧任务不补写渠道；费用详情将缺少渠道快照的旧视频记录显示为未知，避免伪造历史路由。

## 可观测性

请求快照保留用户指定渠道；文本 token 用量的 `raw_usage` 记录 `requestedChannel` 和 `routingMode`，视频费用详情展示请求渠道。平台自动路由的最终实际渠道不能由用户偏好推断；当前平台 OpenAPI 没有声明稳定的实际渠道返回字段，尚未实现该字段的展示。

现有 Agent 来源、批次和计费归因继续生效。验收使用 mock，不触发付费模型调用。

## 平台依据与待联调项

依据平台 [快速入门](https://mg.epaipix.com/guide/quickstart) 和登录后的 OpenAPI：渠道通过公开 `channel` 键选择，省略时平台自动路由，固定渠道不切换其他渠道。目录中的 `available` 表示可选状态，不表示实时空闲容量。

2026-10-29 更新本地测试 Key 后，对 `mg-test.epaipix.com` 完成只读渠道目录联调，四个模型均返回 200，响应包含 `model`、`selection_parameter: channel`、`channels`，与实现契约一致：

| 模型             | 可选渠道键（按优先级）                                                                 |
| ---------------- | -------------------------------------------------------------------------------------- |
| Gemini 3.8 Flash | `yinghe`、`toapis`、`apimart`、`yseeai`                                                |
| Nano Banana 2.1  | `toapis-official`、`apimart-official`、`toapis-standard`、`apimart-extended`、`yseeai` |
| Seedance 2.0     | `yinghe`、`apimart`                                                                    |
| Seedream 5.0 Pro | 空列表，界面仅保留自动渠道                                                             |

目录为环境相关的动态数据，以上仅为当次观察，不硬编码到界面。空列表不证明自动生成一定可用。只读请求带 Agent 名称及唯一运行批次，未触发生成或付费调用。

当前不臆造渠道专属能力、价格和实际执行渠道字段；这些扩展需取得平台稳定契约后接入。平台目录故障不覆盖已保存偏好，指定渠道提交验证失败会明确报错。

## 并发与预览约定

- 偏好保存持有用户行锁，并刷新认证阶段已加载的 ORM 数据后合并，避免不同模态并发保存相互覆盖。
- 子项目视频模型弹窗使用本地草稿；预览、取消和校验失败均不保存偏好。确认应用时，模型、渠道、分镜配置和用户视频偏好在同一事务中提交，预览令牌包含渠道。
- 视频请求同时保存原始提交参数与生效参数。相同 `request_id` 和原始参数直接复用原工单，即使用户后来修改偏好或渠道失效；更改参数仍返回 409。
- 浏览器仅对 GET、HEAD、OPTIONS 自动重试网关错误；生成等写请求不会自动重放。
- 历史视频通过 `PUT /api/storyboard-lines/{line_id}/current-shot/{asset_id}` 保存选用状态，服务器校验归属、可用状态和软删除。保存成功后更新界面；保存期间禁用导出，导出快照读取持久化的当前版本。
