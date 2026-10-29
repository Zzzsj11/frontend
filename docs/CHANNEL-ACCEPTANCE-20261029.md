# 模型渠道真实验收（2026-10-29）

目标：`https://mg-test.epaipix.com`；Agent：`code-agent`；批次：`code-channel-d441edc91a9d49949c40d8b6eac274ed`。全部请求携带 Agent 三头和稳定幂等键。

15 个生成组合全部成功，全部已结算。当前开放渠道未遇到欠费；Seedance RunningHub 渠道目录标记不可用，未提交。Seedream 未发布手动渠道键，因此仅验收自动路由。

| 模型             | 渠道             | 结果      | 账务    | 人民币     | 平台工单                               |
| ---------------- | ---------------- | --------- | ------- | ---------- | -------------------------------------- |
| gemini-3.8-flash | apimart          | succeeded | settled | 0.0001536  | `job-e9a81ca712a8494ea8cb2a82a0c6e848` |
| gemini-3.8-flash | 自动             | succeeded | settled | 0.000184   | `job-7c5a59c282204d2599bb1db3d959c1ed` |
| gemini-3.8-flash | toapis           | succeeded | settled | 0.0013965  | `job-b2a9a6d5d82e47adbade76ef442f40ee` |
| gemini-3.8-flash | yinghe           | succeeded | settled | 0.000184   | `job-65cb8fa41d114b979b237758d87daced` |
| gemini-3.8-flash | yseeai           | succeeded | settled | 0.000072   | `job-cd5c6371cbc74d67a32ef05dc8a3bb42` |
| nano-banana-2.1  | apimart-extended | succeeded | settled | 0.083784   | `job-b3fce2010f3c4f818f6abfe26f3f95d6` |
| nano-banana-2.1  | apimart-official | succeeded | settled | 0.22334022 | `job-f7a45b6e438043499969a77f12c19008` |
| nano-banana-2.1  | 自动             | succeeded | settled | 0.230524   | `job-759843beb1d140d7b9edcaa6491499c0` |
| nano-banana-2.1  | toapis-official  | succeeded | settled | 0.237202   | `job-7200916fc58a4ea28219af2a43b7dfda` |
| nano-banana-2.1  | toapis-standard  | succeeded | settled | 0.105000   | `job-f082bfc9a5d74cad82478d6d868e8277` |
| nano-banana-2.1  | yseeai           | succeeded | settled | 0.139213   | `job-2f602830e663464fbb75b20b4f7de50a` |
| seedance-2.0     | apimart          | succeeded | settled | 1.843248   | `job-28a5139b8bf348f38b7375e538953eb4` |
| seedance-2.0     | 自动             | succeeded | settled | 1.493859   | `job-91154846166c4a1ea8d75b61b565c51c` |
| seedance-2.0     | yinghe           | succeeded | settled | 1.493859   | `job-88f49e7157324770b19b823966ea89bb` |
| seedream-5.0-pro | 自动             | succeeded | settled | 0.300000   | `job-1961c306079a4d858c6a2ca2d31bc474` |

本轮平台实付合计 ¥6.15201932。视频使用4秒、480p纯文本，图片使用1K方形单张，文本只请求简短连通响应。计时包含并发排队，不能用于比较供应商速度。

文本正文均正确返回；七张图片可完整解码为1024×1024；三段视频均可解码，输出864×496、约4.042秒，抽帧符合绿叶场景。媒体和原始响应保留在平台账本及本次本机临时验收目录，不提交测试媒体或凭据。

本轮尚未发现需要修改 all in one 的生成或结算问题。MV 补充了指定渠道清晰度、比例和参考素材上限校验，阻止不兼容配置进入付费工单。
