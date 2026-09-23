# 用户门户、生成方式费率与积分账本

## 部署边界

新增 `user-web/`：独立 Vue 3 / TypeScript / Pinia / Router 项目，开发端口 5181、容器端口 8080。Nginx 仅把 `/portal/` 转发到对外 API。用户身份接口属于 `public-api/gateway/portal.py`；管理操作属于独立的 `admin-api/control/billing.py`，管理后端没有供应商凭据，不 import 对外后端。

两端仅共享数据库契约；`db.py` 与 `credits.py` 在两个包明确复制，测试检查一致性。迁移 `0002` 只增列增表，不删除旧数据。先执行 Alembic，再分别部署 API / Worker、管理 API、管理 Web、用户 Web。用户 Web 可单独执行 `VERSION=<version> scripts/deploy.sh user` 发布。

## 用户与 API Key

- 用户自行注册、登录。用户名不区分大小写，密码至少 10 位，采用随机盐 scrypt；登录令牌是随机、不透明、数据库仅存散列的 8 小时会话。退出软删除会话，立即失效。浏览器只在内存保存令牌，刷新后重新登录。
- 注册及登录按来源 IP 记录尝试并限速；生产反代必须正确配置可信代理范围，不能信任任意客户端 X-Forwarded-For。
- 用户没有创建、轮换、绑定 Key 或充值接口。管理台「用户与积分」选择注册用户，生成并绑定 Key，设置初始月积分。Key 明文只在管理员创建时展示一次，管理员通过安全渠道交付。用户门户仅展示前缀。
- 已绑定 Key 固定归属用户，不能用 `X-User-Id` 冒充别人。门户令牌不能调用模型，模型 API Key 也不能登录门户或管理台。
- 绑定关系不可转移；已产生任务的旧系统 Key 不能再绑定其他用户。历史任务、流水按所有权隔离。
- 既有 MV 系统 Key 迁移时保持原调用行为，标为「额度控制未启用」；管理员设置其月额度或临时调整时启用额度控制。所有新 Key 默认启用额度控制，绑定用户的 Key 不允许关闭。

## 计价单位及费率管理

**1 积分 = 人民币 0.01 元，100 积分 = 1 元。** 使用十进制运算，积分保留 6 位小数，避免每次调用向上取整造成小额 Token 费用偏大。

每个模型可以发布多个规则，按以下组合匹配：

| 维度 | 示例 |
|---|---|
| 生成方式 | chat、text_to_image、image_to_image、text_to_video、image_to_video、reference_to_video、first_last_frame、edit |
| 规格 | 720p、1080p、768p、2k、1024x1024 |
| 质量 | low、medium、high、auto 等 |
| 声音 | 渠道字段对应的 on/off 或 true/false |

留空表示全部；更具体的规则优先。相同优先级且交叉覆盖的规则不允许发布。生成方式由服务从实际供应商请求结构识别，不接受客户端提交单独的计费模式覆盖它。H3 720 档在实际协议中为 `768p`，应按协议规格配置。

每条规则设置说明、费率来源、单任务预占、启用状态，以及一个或多个计价项：

| 计价项字段 | 含义 |
|---|---|
| label | 用户可读名称，例如输入 Token、输出 Token、缓存读取 |
| path | 渠道 usage 内的字段路径，例如 `prompt_tokens`、`completion_tokens`、`input_tokens` |
| unit | 单价对应数量，例如 1,000,000 Token，或 1 秒 / 张 |
| cny | 该单位的人民币价格，由管理员填写账户实际适用费率 |
| subtract | 从该字段数量扣除的其他 usage 字段，例如输入总 Token 扣除已单独计价的缓存 Token |
| optional | 仅在供应商明确字段缺省代表 0 时开启；否则缺失字段进入待核账 |

**积分 = Σ（渠道实际用量 ÷ unit × cny）× 100。** 先合计后保留六位小数。按用户确认，金额属于根据实际用量和费率计算的估算费用，界面标识「按用量计价」，不冒称渠道逐请求实付账单。

示例仅解释公式，并非英和报价：输入 1,000 Token、输入价 ¥2/百万，输出 500 Token、输出价 ¥8/百万，则费用 ¥0.006，扣 0.6 积分。不同模型、生成方式的费率必须由管理员依据英和账户适用价格配置；本版不把旧 MV 中注明「待供应商复核」的价格自动作为已确认价格。

如果渠道返回独立、已确认单位为人民币的实付字段，可以配置 `actual_cny_path`（如 `response.data.billing.actual_cny`）。该字段存在时优先于用量估算。不能把含义不明的 `cost`、聚合余额差或其他货币直接认定为单次人民币费用。

发布相同组合的新规则时，旧规则软退役；任务接收时保存费率快照，改价不追溯已接单任务。管理后台和用户 API 文档从同一组规则读取，用户无需登录即可查看已配置模型说明与费率。

## 月额度、预占和临时调整

- 月额度采用北京时间自然月。Worker 每 60 秒检查，API 读余额或接单时同时兜底，因此进程停机跨月后恢复也不会使用过期额度。
- 每月重置「月余额」为配置的月额度，未用月额度不结转；临时余额和已产生的负余额不被清零。跨月未完成任务继续占用预占额度，最终结算从结算当月余额扣减。
- 新 Key 初始月额度立即入账。后续修改月额度从下一次重置生效，不重置当前月已消费金额；当月增加或扣减使用临时调整。
- 管理员临时增加、临时扣减必须填写原因和幂等操作号。扣减不能侵占其他任务的预占额，也不能主动把可用余额扣为负数。
- 可用积分 = 月余额 + 临时余额 − 未释放预占。接单在数据库事务锁内校验并预占，支持多 API / Worker 并发。
- 结算优先扣月余额，再扣临时余额；释放本任务预占。若实际用量超出管理员配置的预占，完整记录应付费用并可能产生欠额，后续不足额请求返回 402。预占是风险额度，不是供应商实际费用的硬上限，管理员应按请求规格配置足够的预占。
- 无有效费率的受控 Key 请求返回 503；缺失必要用量时保留预占并显示「待核账」，不把缺失费用计为 0。管理员可通过核账接口根据账单确认费用（包括确认为 0），释放预占。
- 并发限制导致明确未向供应商提交的 Chat 任务记零消费并释放预占；提交结果不确定、失败但缺失账单等情形保持待核账，禁止自动重发生成。

## 流水类型

| kind | 显示标识 | 对余额的影响 |
|---|---|---|
| monthly_reset | 月度重置 | 记录旧月过期与新月发放的净变化，凭据保存两者原值 |
| manual_credit | 临时增加 | 增加临时余额，正数 |
| manual_debit | 临时扣减 | 减少临时余额，负数 |
| task_charge | 任务消费 | 逐任务扣费，记录用量、费率及公式分项 |
| reconciliation | 账单校正 | 原扣款与最终金额的差额，不覆盖原流水 |

流水包含用户、Key、任务、操作号、操作者、原因、变动积分、月余额、临时余额、证据和三个生命周期时间字段。无编辑或删除流水接口；重复操作号相同内容返回原记录，不同内容返回 409。重复 Worker 回调不会重复扣款。

## 接口清单

用户门户（登录接口除外均按用户隔离）：

- `POST /portal/register`、`POST /portal/login`、`POST /portal/logout`
- `GET /portal/me`：所属 Key 及月额度、临时余额、预占、可用积分
- `GET /portal/models`：公开模型能力、分生成方式费率
- `GET /portal/jobs?page=1&limit=30`：自己的每次任务、用量、扣分、费率快照
- `GET /portal/ledger?page=1&limit=50`：自己的积分流水

管理员（独立管理 Token）：

- `GET /admin/users`：已注册用户
- `POST /admin/clients`：支持 `user_id`、`monthly_points`，生成并绑定
- `POST /admin/clients/{id}/bind`：绑定未使用的 Key，禁止转移
- `GET /admin/wallets`：各 Key 钱包
- `POST /admin/clients/{id}/quota`：`{"points":"10000"}`，设置下月额度
- `POST /admin/clients/{id}/adjust`：`{"points":"100","reason":"项目临时额度","operation_id":"unique-operation-id"}`；负数表示扣减
- `GET /admin/ledger?client_id=...&kind=manual_credit&page=1`
- `GET /admin/pricing`、`POST /admin/pricing/{model}`：读取 / 发布费率版本
- `POST /admin/jobs/{id}/reconcile`：`actual_cny`、`operation_id`、`reason`、`reference`；关联渠道账单证据，仅扣或退差额

生成查询 `/v1/jobs/{id}` 新增 `billing`：包含 `status`、`points`、`cny`、`reserved_points`、`rule`。其中 `usage_priced` 表示实际用量 × 配置费率，`settled` 表示明确实付金额或人工核账，`pending_reconciliation` 表示金额未知。

## 验证方式

`make check` 覆盖注册、所有权、权限、费率模式、缓存 Token 去重计价、价格快照、并发额度、幂等结算、月度重置和临时增减。`node tests/portal-browser.mjs` 使用隔离临时数据库及 8191–8194 端口验收全链路；没有供应商密钥，也不启动 Worker 或发模型请求。`tests/postgres-concurrency.py` 另在隔离 PostgreSQL 验证跨事务并发。


对外任务状态只展示 `queued/running/succeeded/failed`。`recoverable` 投影为 `running`，`manual_review` 投影为 `failed`；数据库与管理 API 保留细分状态及原始错误原因。映射不会触发重提、释放积分预占或改变人工复核要求。
