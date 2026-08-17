# AIGC API Key 模型权限查询工具

## 用途

查询银河 AIGC 平台某个 API Key 下已开通的模型列表，或与项目当前 key 对比差异。典型场景：

- 拿到新 key 后，确认它开通了哪些模型、能否替换项目现有 key
- 排查「当前key未启用该模型」「模型未授权」类报错
- 换 key 前评估对项目功能的影响（项目默认模型：图像 `gpt-image-2`、视频 `doubao-seedance-2.0`、LLM `gpt-5.5`，见 `backend/app/config.py`）

## 等价 curl

工具封装的就是这个上游接口（OpenAI 风格）：

```bash
curl -i https://api-aigc.fzyinghe.com/v1/models \
  -H "Authorization: Bearer yh-xxx"
```

返回 `{"object":"list","data":[{"id":"gpt-5.5",...},...]}`，`data[].id` 即该 key 可用的模型编码。

## 工具用法

脚本：`scripts/check-aigc-models.py`（纯标准库，宿主机 python3 直接运行，无需进入容器或安装依赖）。

```bash
# 查项目 backend/.env 当前 key（读取顺序 VIDEO_API_KEY → IMAGE_API_KEY → AIGC_TOKEN）
python3 scripts/check-aigc-models.py

# 查任意指定 key（输出默认脱敏，只显示头尾几位）
python3 scripts/check-aigc-models.py --key yh-xxx

# 指定 key 与 .env 当前 key 对比（列出各自独有的模型）
python3 scripts/check-aigc-models.py --key yh-xxx --compare

# 两个 key 互相对比
python3 scripts/check-aigc-models.py --key yh-aaa --key yh-bbb

# 其他平台接入域名
python3 scripts/check-aigc-models.py --base-url https://other-host.example.com --key yh-xxx

# 输出中显示完整 key（默认脱敏）
python3 scripts/check-aigc-models.py --show-key
```

输出示例（对比模式）：

```text
.env 当前 key（VIDEO_API_KEY） yh-qu78...kk（共 17 个模型）
  - doubao-seedance-2.0
  ...
传入 key yh-ftbq...ald（共 17 个模型）
  - doubao-seedance-2.0
  ...

对比 .env 当前 key（VIDEO_API_KEY） vs 传入 key：
  仅 .env 当前 key（VIDEO_API_KEY） 有：无
  仅 传入 key 有：无
```

## 注意事项

- 该接口只反映**模型开通情况**。素材（`asset://`）链路另有账户级隔离：素材组、素材通道授权（`virtualAssetChannelId`）按 key 所属账户划分，模型列表相同不代表素材互通。换 key 后数字人头像需用新 key 重新注册素材。
- 模型列表为「可用」不代表每个模型的所有参数组合都被支持，具体以实际生成调用为准。
- 平台对无效 key 也会返回 HTTP 200 + 空列表；工具对「0 个模型」输出警告并以退出码 2 结束，网络/协议错误退出码为 1，便于接入巡检脚本。
