# 已有任务用量补查与修复记录

2026-09-23。使用已有上游任务ID执行13次GET查询，全部HTTP 200；没有提交生成请求。查询携带code-agent及独立运行批次标识。未修改历史任务账本或发布正式用户费率。

已确认：成本价扣费，各渠道独立；底层保留精度、前端整数；账号−1000积分为新任务准入下限，已受理任务允许据实突破；自然月不结转欠款，历史消费保留。额度规则尚未在本轮实现。

|路由|上游最终计费字段|成本参考人民币|
|---|---|---|
|toapis--gpt-image-2.5-sunburst|{}|缺失|
|toapis--gpt-image-2.5-flare|{}|缺失|
|toapis--gpt-image-2|{}|缺失|
|toapis--gemini-3.1-flash-image-preview|{}|缺失|
|toapis--gemini-3-pro-image-preview|{"billing": {"status": "refunded", "credits": "0", "cost_usd": "0"}}|0.000|
|toapis--seedream-5.0|{}|缺失|
|toapis--dreamina-seedance-2.5|{"generation": {"usage": {"completion_tokens": 87300, "total_tokens": 87300}}, "billing": {"status": "settled", "credits": "174.6", "cost_usd": "0.873"}}|6.1110|
|toapis--dreamina-seedance-2.0|{"billing": {"status": "settled", "credits": "114.7368", "cost_usd": "0.573684"}, "generation": {"usage": {"completion_tokens": 87300, "total_tokens": 87300}}}|4.0157880|
|toapis--dreamina-seedance-2.0-fast|{"billing": {"status": "settled", "credits": "69.2164", "cost_usd": "0.346082"}, "generation": {"usage": {"completion_tokens": 87300, "total_tokens": 87300}}}|2.4225740|
|toapis--dreamina-seedance-2.0-mini|{"generation": {"usage": {"completion_tokens": 87300, "total_tokens": 87300}}, "billing": {"status": "settled", "credits": "22.9472", "cost_usd": "0.114736"}}|0.8031520|
|toapis--gemini-omni-flash-preview|{"billing": {"status": "settled", "credits": "160", "cost_usd": "0.8"}}|5.600|
|toapis--wan3.0-video-sg|{"billing": {"status": "settled", "credits": "48", "cost_usd": "0.24"}}|1.680|
|toapis--gemini-3-pro-image-preview|{}|缺失|

Toapis按历史确认的1供应商积分=¥0.035折算；上游cost_usd与积分的换算是200积分/USD，与英和6.9汇率不能混用。人民币数值是成本参考，不代表已写入用户扣费。

关键发现：Seedance 2.5真实结算174.6供应商积分，旧余额差191.4；Seedance 2.0真实114.7368，旧余额差100.9420。余额差不能作为任务最终成本。四条Seedance均返回generation.usage.total_tokens=87300；Mini费率存在供应商小数舍入差异，需要确认其最终取整规则。
GPT/Gemini等Toapis图片成功查询仍无billing/usage；一个失败Gemini图像任务明确返回refunded、credits=0。不能将其他无字段任务视为0。后续需确认供应商是否另有按请求计费明细接口。

本轮代码修复：

- 提取generation.usage并保留billing，补上Toapis视频真实用量。
- 保留rawUsage原字段与缓存等所有内容，新增有真实样本支持的input_tokens/output_tokens别名；不推断缺失数据、不把image_tokens重复加到输入。
- 文本同步与流式最终响应也通过相同别名映射。
- 缓存扣除字段缺失/null时停止自动计算，进入现有待核账流程；明确0才按0处理。管理端与公开端计费实现保持一致。

尚未完成：后台在生成成功但billing pending之后的定时补查和回填、原始用量事件完整留存、逐路由正式计费规则、1000积分透支及月度规则、供应商积分结算路径与舍入校验。本次改动不等于19模型已能正式收费。
