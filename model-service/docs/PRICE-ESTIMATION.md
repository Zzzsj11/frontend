# 单任务参考价格与供应商费率同步

## 调用

在原始文本、图片请求里加 `"estimate_only": true` 即可自动估价；也支持单独 `POST /v1/pricing/estimate`。使用管理员分配的 Bearer Key，无需 Idempotency-Key，不创建任务、不预占积分、不扣费、不调用生成模型或下载参考图。

```json
{
  "model": "gpt-5.6-sol",
  "messages": [{"role":"user","content":"帮我写一段产品介绍"}],
  "max_tokens": 500,
  "estimate_only": true
}
```

## 自动估算方法

文本输入采用本地字符启发式：ASCII 约 4 字符/Token，其他字符暂按 1.5 Token/字符，加 12 Token 消息开销。该比例是工程近似，非厂商精确 tokenizer。计入 messages、input、system、tools，不把图片 URL/base64 当作正文。结合相同模型、相同供应商历史记录的中位输入差额，补偿可观察到的渠道额外上下文。

文本输出使用相同模型、供应商最近最多 50 条成功记录的输出 Token 中位数；无样本默认 512，可通过路由 `pricing.estimate_policy.default_output_tokens` 配置。显式 max_tokens/max_output_tokens/max_completion_tokens 会限制预计输出值。历史仅使用本 Key 所属用户的数据及专用验收账户的测试数据，不使用其他用户的私有任务。

图片优先使用渠道按次/张价格 × 数量，并匹配分辨率、质量、参考图数量等价格条件。按 Token 收费时，使用同模型/供应商/分辨率/质量历史输出中位数，按 n 计算。无样本时采用内部保守默认：low=512、medium=2048、high/auto=8192 输出 Token；2K 乘2、4K乘4。这是粗估参数，不是厂商承诺。参考图暂按每张1536输入Token粗估，不为估价下载用户图片。

`estimate_usage` 仍可覆盖 input_tokens/output_tokens/image_tokens 等用量。视频保持原有按秒/Token估价方式，Token制视频尚不自动推导输出Token。

返回 `amount_cny`、平台 `points`（1积分=¥0.01）、用量、`estimation.method/sample_count/automatic_fields`、规则版本。用到自动预测且影响金额时附参考区间（点估计的50%～150%）；它不是置信区间或价格上下限保证。仅按明确数量和固定费率计算时不额外扩大区间。

无任务内容、无用量时返回 needs_usage；条件无匹配返回 needs_parameters；费率缺失返回503，金额不会伪装成0。缓存优惠不参与本轮估价，实际命中缓存可能便宜。

## 价格同步与数据库

读取供应商价格并写入本地快照、估价规则和审计记录的同步命令（不调用生成模型）：

```bash
backend/.venv/bin/python model-service/scripts/publish-estimate-rates.py --env-file model-service/.env --snapshot-dir model-service/.runtime/pricing-current --refresh
```

同步以下来源，使用私有环境变量中已有凭据，管理后端不持有供应商密钥：

脚本不再自动读取开发 `.env`，也不再使用写死日期的本机目录。目标 `DATABASE_URL` 必须来自环境或显式 `--env-file`（环境优先），`--snapshot-dir` 必填。不加 `--refresh` 时导入该目录已有快照。首次无密钥报价产物由 Alembic 0006 安装，不需要复制开发数据库。

- 英和海外模型广场的账户价格接口：按精确模型ID保存原始 billingRule、账户discount，包含阶梯、场景、附加计费字段。不能用公开原价重复乘已折扣价格。
- Toapis `GET /v1/pricing`，完整分页获取当前Key图片/视频有效费率；文本采用站点公开 `/api/pricing` 目录参考值，明确不是已验证账户专属价。
- Toapis `/v1/user/balance` 读取 credits_per_usd，目录金额先换算为供应商积分，再按1000积分=¥35换成人民币。英和美元采用6.9参考汇率。

数据库复用独立服务 `model_routes.pricing`：

- `supplier_price_snapshot.raw`：该精确模型原始费率及价格条件；
- `source_url/synced_at/currency/conversion`：来源、更新时间、币种、换算口径；
- `estimate_rules`：本地可执行的无缓存规则；
- `estimate_version`：价格内容版本；
- `audits`：记录同步前后供应商快照，保留历史。

目前38个模型/供应商组合均保存对应快照，36个有可执行估价规则；Toapis Seedance 2.0/2.0 Fast 的 prices 为空，保留缺价状态。管理员发布的有效模型计价规则优先；同步不改人工计费规则、不启用模型、不改历史任务的费率快照。同步是显式执行，尚未设置定时刷新。

同名系列不同版本不得混价。例如截图中的 Gemini Omni VIP 和当前官方版模型是不同精确ID，不能借用VIP价格。原始费率即使含缓存项也完整保存，但本轮估算忽略缓存计费。

## 调研依据

- [Anthropic Token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting)：可在发送前统计输入Token；统计仍可能与实际使用略有不同。不同模型tokenizer也可能不同。
- [Gemini Token counting](https://ai.google.dev/gemini-api/docs/tokens)：输入可计数，输出用量来自生成响应。
- [Gemini官方价格](https://ai.google.dev/gemini-api/docs/pricing)：图片规格与输出Token影响费用。
- [Toapis价格文档](https://docs.toapis.com/api-reference/account/pricing)：目录不是单次报价，不锁价；空价格不代表免费。

本项目暂不依赖两家中转渠道尚未验证的 count_tokens 接口。字符估算、历史中位数及默认图片Token属于本项目工程策略，而非宣称所有厂商都使用相同算法。正式实际扣费仍是独立流程，本次不把参考报价作为已确认实付账单。

## 后台按模型、渠道独立配置

入口：管理后台 → 模型供应商 → 对应行「配置预估费用」。可配置：

- 文本字符/Token比例、消息开销、默认输出Token、是否使用历史样本；
- 图片各质量的默认Token、2K/4K倍率、参考图Token；
- 按规格匹配的计价公式（JSON中的conditions、rates）；
- 费用调整倍率、固定加价、最低预估费用、参考区间系数。

公式：`人民币 = max(最低费用, Σ(用量 / 单位 × 人民币单价) × 费用倍率 + 固定加价)`。

保存接口 `PUT /admin/routes/{route_id}/estimate-pricing` 仅管理员可用。数值与计价量字段受校验，不执行任意代码。保存生成新版本并记录前后配置审计，不更改历史工单或实际扣费。手工覆盖标记开启后，供应商同步只更新原始快照和候选规则，不覆盖手工公式。

更新：通过登录态 Toapis 价格工作台，已核实 Seedance 2 的8组价格、Fast的4组价格。原 Key API 空费率快照仍保留；登录态网页价格单独存入 `dashboard_price_snapshot`，作为有来源的估价补充。目前38个模型/渠道组合均有估价规则（不等于全部已验证可生成）。

若调用方传入 total_tokens，则按网页Token费率估算；未提供时按网页「低至」秒价做预算参考。有输入视频还需 estimate_usage.input_seconds，计算输入+输出视频秒数费用。实际账单仍按最终 total_tokens，不按预算秒价结算。
