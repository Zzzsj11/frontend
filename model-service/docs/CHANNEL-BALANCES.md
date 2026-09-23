# 渠道余额、币种和英和模型授权

实现位置：独立模型服务管理后台「渠道余额」。供应商资金与本服务发给用户的积分账本分开管理。

## 余额模型

`channel_accounts` 每行代表一个渠道账户/目标调用 Key。仅存目标密钥的环境变量名和脱敏展示值；完整 Key、商户签名密钥不入数据库、管理 API 或浏览器。表包含 `created_at / updated_at / deleted_at`，结构通过 Alembic `0003` 创建。

| 字段 | 含义 |
|---|---|
| `currency` | `CNY` 人民币、`USD` 美元、`POINTS` 积分、`UNKNOWN` 尚未确认 |
| `usd_cny` | 1 美元对应人民币元，初始 6.9，可按渠道修改 |
| `points_per_unit` | 兑换 1 元或 1 美元需要多少积分；未确认时留空 |
| `points_currency` | 积分兑换目标币种 CNY 或 USD |
| `snapshot` | 最近成功的原余额、脱敏 Key、Key 限额/已用/剩余、来源 |
| `queried_at / attempted_at` | 最近成功时间 / 最近尝试时间 |
| `error` | 最新查询失败原因，不覆盖上次成功余额 |

人民币折算公式使用 Decimal，API 返回十进制字符串，页面最多展示 6 位小数：

- 人民币：原余额。
- 美元：原余额 × `usd_cny`。
- 积分兑换人民币：积分余额 ÷ `points_per_unit`。
- 积分兑换美元：积分余额 ÷ `points_per_unit` × `usd_cny`。
- Toapis 特例：使用接口原始 `remain_credits`，按用户确认的 **1000 Toapis 积分 = 35 元人民币**计算，即积分 × `0.035`。不经美元或四舍五入后的倒数换算。旧美元快照不参与计算。
- 未确认币种或兑换比例：参考金额为空，显示待配置，不能假定为 0。

参考折算不修改供应商资金、用户积分或历史任务账单。管理端修改兑换配置和人工录入均记录操作审计。修改原币种会清空旧快照，避免把旧积分数值误解释为美元。

商户余额与 Key 限额分开：`quotaAmt=null` 表示未设置该 Key 限额，不代表商户有无限资金。Key 已用额度不等于商户总消费。多个 Key 可以共享商户资金，页面不直接汇总商户余额，避免重复计算。当前不把这套管理展示用余额自动接入 MV 生成预检。

## 渠道接入范围

| 渠道 | 币种 | 查询方式 |
|---|---|---|
| 英和国内 | CNY | 商户签名查询余额 + 分页匹配当前 Key 额度 |
| 英和海外 | USD，用户已确认 | 同上，完全独立商户凭据与域名 |
| RunningHub | 积分 | 暂用人工快照，兑换比例待业务确认 |
| Toapis | 供应商积分 | `GET https://toapis.cn/v1/user/balance`；人民币 = 积分 × 0.035 |


没有已验证余额接口的渠道明确标记为人工记录，不伪装成实时查询。未填入凭据的自动渠道显示配置错误。生成接口是否启用与余额采集是两件事。

Toapis 任务费用优先保留供应商确认的 `billing.credits`，余额变化另行对账；缺失确认费用不等于免费。测试报告按实扣积分汇总后乘 `0.035`，美元字段仅供交叉核对。该供应商积分与本平台用户积分（1 积分 = ¥0.01）不同，不直接互换数量。

公开执行服务的 Worker 每 5 分钟采集自动渠道，跨 Worker 通过数据库锁领取，每个账户一次查询。后台「刷新余额」写入刷新请求，不直接访问供应商，60 秒内合并强刷。超过 10 分钟或最新查询失败时，旧快照标记为历史数据。Key 额度单独失败时保留商户余额并显示额度错误。管理 API 继续没有供应商密钥。

## 配置与上线

1. 执行独立服务 Alembic `upgrade head`，新增 0003；不用 MV 数据库。
2. 公开服务/Worker 配置 `YINGHE_API_KEY` 与 `YINGHE_BUSINESS_USER_ID / YINGHE_BUSINESS_API_KEY`；海外对应 `YSEEAI_*`，不能跨站回退凭据。
3. 国内业务域名固定为 `https://api-aigc.fzyinghe.com`，海外固定为 `https://api-aigc.yseeai.com`；不能将商户凭据发给任意地址。
4. 管理数据库角色需读写 `channel_accounts` 与 `audits`；执行角色需读写 `channel_accounts`。管理 API 不需要供应商配置。
5. 使用版本化镜像独立部署管理 API/Web 和公开 Worker。部署 Worker 前按现有任务排空流程处理，不中断生成中的请求。
6. 本机只读验证可单独执行余额采集，不触发任何生成。

## 国内/海外共用模型增量授权工具

入口：`scripts/yinghe-business.py`；在 `model-service` 目录运行，使用安装了公开服务依赖的 Python。

```bash
# 海外余额：原美元余额 + 按 6.9 计算的人民币参考余额
../backend/.venv/bin/python scripts/yinghe-business.py --channel yseeai balance

# 国内已授权模型列表
../backend/.venv/bin/python scripts/yinghe-business.py --channel yinghe models

# 检查给海外当前 Key 开通模型的计划，不调用供应商
../backend/.venv/bin/python scripts/yinghe-business.py --channel yseeai --dry-run grant gpt-image-2 seedream-5.0

# 实际增量开通并查询授权列表复核
../backend/.venv/bin/python scripts/yinghe-business.py --channel yseeai grant gpt-image-2 seedream-5.0

# 指定另一个 Key：值由私有文件或环境变量注入，不把 Key 写入命令
../backend/.venv/bin/python scripts/yinghe-business.py --channel yinghe --target-key-env YINGHE_SECOND_API_KEY grant gpt-image-2

# 沿用单独保存的海外业务凭据文件（BUSINESS_* 会映射到指定站点）
../backend/.venv/bin/python scripts/yinghe-business.py --channel yseeai --business-env-file .secrets/yseeai-business.env balance
```

`--env-file` 默认独立服务 `.env`；`--business-env-file` 可使用原国内工具的 `BUSINESS_USER_ID / BUSINESS_API_KEY` 格式，但必须显式选择渠道。完整 Key 不接受命令行参数，不输出。`--usd-cny` 可覆盖 CLI 参考汇率，默认 6.9。

流程为查询当前授权 → 仅添加差集 → 再次查询复核。调用 `POST /business/tokens/addModel`，永不全量替换已有模型；业务签名采用非空字段按 ASCII 排序、拼接 `&key=`、MD5 大写，时间戳单位为秒。调用失败或超时不自动重试，先复核实际授权，部分成功返回缺失模型并以退出码 2 结束。下一次显式执行先重新查差集。授权日志以脱敏 JSONL 保存至被 Git 忽略的 `.runtime/business-grants.jsonl`。

开通供应商权限不会自动启用产品模型；协议、参数能力和用量计费仍需在模型注册中完成适配。这些操作不调用真实生成模型。

迁移 0012 软删除 Gemini / MiniMax 提示词渠道，不再展示或刷新余额；历史任务和流水保留。全新安装执行完整迁移后也不会显示这两个渠道。
