"""Read-only provider permission audit and local task evidence report; never generates."""

import asyncio
import json
import os
from collections import Counter
from pathlib import Path

import httpx
from gateway.db import Job, Model, Session
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]


async def main():
    manifest = json.loads((ROOT / ".runtime/overseas-live.json").read_text())
    catalog = json.loads((ROOT / "catalog/yseeai-2026-09-21.json").read_text())["models"]
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get("https://ai-aigc.yseeai.com/v1/models", headers={"Authorization": "Bearer " + os.environ["YSEEAI_API_KEY"]})
        r.raise_for_status()
        allowed = {m["id"] for m in r.json()["data"]}
    async with Session() as db:
        jobs = (await db.scalars(select(Job).where(Job.agent_run_id == manifest["run_id"]))).all()
        by_model = {j.model_id: j for j in jobs}
        evidence = []
        for item in catalog:
            name = item["innerCode"]
            job = by_model.get("yseeai--" + name)
            model = await db.get(Model, "yseeai--" + name)
            evidence.append(
                {
                    "model": name,
                    "kind": item["modelType"],
                    "permitted": name in allowed,
                    "protocol": model.protocol,
                    "job_id": job.id if job else None,
                    "status": job.status if job else "not_submitted",
                    "error": job.error if job else manifest["models"].get(name, {}).get("reason"),
                    "provider_id": job.provider_id if job else None,
                    "usage": job.usage if job else {},
                    "result": job.result if job else None,
                }
            )
    (ROOT / ".runtime/overseas-evidence.json").write_text(
        json.dumps({"run_id": manifest["run_id"], "allowed_models": sorted(allowed), "models": evidence}, ensure_ascii=False, indent=2)
    )
    lines = [
        "# 英和海外接入与真实测试记录",
        "",
        "来源：https://admin-aigc.yseeai.com/async/doc；目录快照：2026-09-21。",
        "",
        "范围：文本 55、图片 25、视频 17，共 97 个模型。排除视频增强和字幕擦除。",
        "",
        "## 接入简化方案",
        "",
        "采用模型目录驱动的协议适配；每个模型保留原始模型编码。海外新增服务模型 ID 使用 `yseeai--原始模型编码`，避免覆盖 MV 现用渠道。",
        "",
        "| 类型 | 渠道接口 | 本服务接口 | 处理方式 |",
        "|---|---|---|---|",
        "| 文本 Chat | `https://ai-aigc.yseeai.com/v1/chat/completions` | `/v1/chat/completions` | 非流式/流式，用量记录 |",
        "| 文本 Claude | 同域 `/v1/messages` | `/v1/messages` | Anthropic 消息及流式事件 |",
        "| Responses | 同域 `/v1/responses` | `/v1/responses` | input、max_output_tokens；独立事件格式 |",
        "| Seedream 图片 | 同域 `/v1/images/generations` | `/v1/images` 或 `/v1/jobs` | 同步渠道响应存为本地异步工单，转存失败不再生成 |",
        "| GPT/Gemini/万相图片 | `https://api-aigc.yseeai.com/image/generation/tasks` | `/v1/images` 或 `/v1/jobs` | 创建一次，GET 原任务 ID 轮询 |",
        "| Seedance 2.x | 同域 `/v3/video/tasks` | `/v1/videos` 或 `/v1/jobs` | content 多模态数组 |",
        "| 其余视频 | 同域 `/video/generation/tasks` | `/v1/videos` 或 `/v1/jobs` | 按模型组装 payload，共用轮询归档 |",
        "",
        '高级调用 `/v1/jobs` 接收 `{"model":"服务模型ID","payload":{原始渠道字段}}`；路由与真实 model 字段由服务控制，不允许调用者传任意上游 URL。所有异步结果查询 `/v1/jobs/{id}`。',
        "",
        "## 参数差异",
        "",
        "- Gemini Omni：顶层 prompt、images、duration，metadata.task；原图 URL 转 Base64。",
        "- Veo：prompt、images（最多 3 张）、duration、resolution、metadata；本轮文生视频 8 秒 720p。",
        "- Seedance：content 包含 text/image_url/video_url，duration、ratio、resolution；1.5 使用统一视频路由，2.x 使用 v3。尚未获得权限实测的版本仍须验收。",
        "- Wan 2.6：t2v 为 input.prompt + parameters.size；i2v 为 input.img_url；r2v 为 input.reference_urls。",
        "- Wan 2.7/3.0：input.media 类型区分 first_frame、reference_image、reference_video；videoedit 的源视频类型是 video，时长取源视频。",
        "- DreamActor：人物 image_urls 或 binary_data_base64 二选一且仅 1 张，video_url 为动作模板；不能拿风景视频当有效验收素材。图片 ≤4.7MB，视频 ≤30秒，结果 URL 仅有效 1 小时。",
        "- Wan 图片使用 input.messages[].content[].text/image 和 parameters；其他图片使用 prompt/image。Seedream 走同步接口，返回 data[].url。",
        "",
        "## 测试方法与边界",
        "",
        f"- Agent 批次：`{manifest['run_id']}`；所有真实请求使用 code-agent 来源、独立幂等键、数据库工单与用量。",
        "- 每模型最小有效调用一次；未自动重发失败或不确定请求。并发提交上限 3；服务端仍遵守用户/模型/渠道限制。",
        "- 首轮发现当前 Key 权限与公开目录不同；后续运行增加只读 /v1/models 权限预检。部分文本在本地并发限制阶段被拒绝，不能算已到渠道。",
        "- 成功只表示本轮参数组合成功；不表示所有图生/编辑/流式/续编组合均已真实验证。",
        "- 缺少 usage 的成功任务保留空用量，不能凭空计算真实成本。公开报价不等于账户实际费率；保持管理员配置。",
        "",
        f"当前 Key 可见模型：{', '.join(sorted(allowed))}。",
        "",
        "## 逐模型证据",
        "",
        "| 模型 | 类型 | Key 权限 | 本轮状态 | 工单/原因 |",
        "|---|---|---|---|---|",
    ]
    for row in evidence:
        detail = row["job_id"] or row["error"] or "未提交"
        if row["error"] and row["job_id"]:
            detail += "；" + row["error"]
        lines.append(
            f"| `{row['model']}` | {row['kind']} | {'有' if row['permitted'] else '未开放'} | {row['status']} | {detail.replace('|', '/')} |"
        )
    lines.extend(
        [
            "",
            "## 本轮成功结果的实际规格",
            "",
            "| 模型 | 请求 | 实际结果 | 用量 |",
            "|---|---|---|---|",
            "| Gemini 3.8 Flash | 最多 32 输出 Token | 成功返回 OK | 输入 259、输出 17、合计 276 Token |",
            "| Veo 3.1 标准 | 8 秒 720p | 1280×720，24fps，8 秒 | 查询未提供 tokenUsage |",
            "| Veo 3.1 快速 | 8 秒 720p | 1280×720，24fps，8 秒 | 查询未提供 tokenUsage |",
            "| Gemini Omni | 5 秒 720p | 1280×720，24fps，10 秒；时长不符合请求 | 查询未提供 tokenUsage |",
            "",
            "Gemini Omni 本轮只能算生成链路成功，不能算时长遵循验收通过。缺失用量不能记为零成本，仍需渠道账单或计费规则补充。",
            "",
            "## 尚需完成",
            "",
            "- 为当前海外 Key 开放其余模型；缺少接口配置的 3 个文本模型需渠道补全。",
            "- DreamActor 准备合规人物动作模板后单独验收。",
            "- 对尚未到达渠道/被权限拒绝的项，开通后使用新的明确批次补测；原有不确定任务先对账，不自动重发。",
            "- 完成基础单模型验收后，再按图生、视频编辑、流式、续编等能力补齐模式覆盖与并发压力验收。",
            "",
        ]
    )
    out = ROOT / "docs/OVERSEAS-API-AND-TESTS.md"
    out.write_text("\n".join(lines))
    print(dict(Counter(row["status"] for row in evidence)))
    print(out)


if __name__ == "__main__":
    asyncio.run(main())
