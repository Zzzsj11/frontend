# Toapis 与所选 19 个模型的目录核对

核对时间：2026-09-22。使用现有 Toapis Key 只读请求 `GET https://toapis.cn/v1/models`，返回 163 条。未执行生成或切换渠道。

10 个精确同名，9 个同系列/版本候选映射均出现在返回目录中。不同渠道命名对应不证明上游、地区、质量或参数完全一致，尤其英和 `-sg` 与 Toapis 无地区后缀。

| 类型 | 英和编码 | Toapis 目录编码 | 匹配 |
|---|---|---|---|
| chat | `claude-fable-5-1` | `claude-fable-5-1` | 同名 |
| chat | `claude-opus-4-8` | `claude-opus-4-8` | 同名 |
| chat | `gpt-6-astra` | `gpt-6-astra` | 同名 |
| chat | `gpt-5.6-sol` | `gpt-5.6-sol` | 同名 |
| chat | `gemini-3.1-pro-preview` | `gemini-3.1-pro-preview-official` | 对应候选，需能力验收 |
| chat | `gemini-3.8-flash` | `gemini-3.8-flash` | 同名 |
| image | `gpt-image-2.5-sunburst` | `gpt-image-2.5-sunburst` | 同名 |
| image | `gpt-image-2.5-flare` | `gpt-image-2.5-flare` | 同名 |
| image | `gpt-image-2` | `gpt-image-2` | 同名 |
| image | `gemini-3.1-flash-image-preview` | `gemini-3.1-flash-image-preview` | 同名 |
| image | `gemini-3-pro-image-preview` | `gemini-3-pro-image-preview` | 同名 |
| image | `seedream-5.0` | `doubao-seedream-5-0` | 对应候选，需能力验收 |
| video | `dreamina-seedance-2.5` | `seedance-2-5` | 对应候选，需能力验收 |
| video | `dreamina-seedance-2.0` | `seedance-2` | 对应候选，需能力验收 |
| video | `dreamina-seedance-2.0-fast` | `seedance-2-fast` | 对应候选，需能力验收 |
| video | `dreamina-seedance-2.0-mini` | `seedance-2-mini` | 对应候选，需能力验收 |
| video | `gemini-omni-flash-preview` | `gemini-omni-flash-preview-official` | 对应候选，需能力验收 |
| video | `wan3.0-video-sg` | `wan3.0-video` | 对应候选，需能力验收 |
| video | `wan3.0-video-prime-sg` | `wan3.0-video-prime` | 对应候选，需能力验收 |
