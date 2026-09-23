"""Render immutable requests, outputs, fees and manual media review from the paid journal."""

import html
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".runtime/comparison-20260922"
D = Decimal


def metric(usage, names):
    for name in names:
        if usage.get(name) is not None:
            return D(str(usage[name]))
    return None


def expected(row, yprices, tprices, textprices):
    u = row.get("job", {}).get("usage") or {}
    inp = metric(u, ["prompt_tokens", "inputTokens", "input_tokens"])
    out = metric(u, ["completion_tokens", "outputTokens", "output_tokens"])
    total = metric(u, ["total_tokens", "totalTokens"])
    if total is None and inp is not None and out is not None:
        total = inp + out
    cached = metric(u, ["cache_read_input_tokens", "cached_tokens"]) or D(0)
    cached += D(str((u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)))
    cache_reported = any(k in u for k in ("cache_read_input_tokens", "cached_tokens")) or "cached_tokens" in (
        u.get("prompt_tokens_details") or {}
    )
    rate = None
    supplier = row["supplier"]
    if supplier == "yseeai":
        rate = yprices[row["model"]]["billingRule"]
        if rate.get("scenarioRules"):
            candidates = [
                r for r in rate["scenarioRules"] if "720p" in str(r.get("resolution", "")).lower() and r.get("inputMode") != "含输入视频"
            ]
            rate = candidates[0] if candidates else None
        if rate and rate.get("tiers") and inp is not None:
            rate = next((r for r in rate["tiers"] if r.get("inputThresholdK") is None or inp <= D(r["inputThresholdK"]) * 1000), rate)
        if row["model"] == "seedream-5.0":
            value = D("0.035") if row["status"] == "succeeded" else None
        elif rate and rate.get("pricePerSecond"):
            value = D(rate["pricePerSecond"]) * D(row["request"]["duration"])
        elif rate and rate.get("outputPricePerMillion") is not None and out is not None:
            value = (D(str(rate.get("inputPricePerMillion") or 0)) * (inp or 0) + D(rate["outputPricePerMillion"]) * out) / 1000000
        else:
            value = None
    else:
        upstream = row.get("job", {}).get("route", {}).get("provider_model")
        if row["kind"] == "chat":
            rate = textprices.get(upstream)
            value = (
                (inp + out * D(str(rate["completion_ratio"]))) * D(str(rate["model_ratio"])) * 2 / 1000000
                if rate and inp is not None and out is not None
                else None
            )
        else:
            rates = tprices.get(upstream, {}).get("prices", [])
            target_resolution = "2K" if row["model"] == "seedream-5.0" else "1K" if row["kind"] == "image" else "720p"
            candidates = [
                r
                for r in rates
                if r.get("group") == "default"
                and str(r.get("conditions", {}).get("resolution", target_resolution)).lower() == target_resolution.lower()
                and not r.get("conditions", {}).get("has_video_input")
            ]
            rate = candidates[0] if candidates else None
            if rate:
                count = (
                    D(1)
                    if rate["price_basis"] == "request"
                    else D(row["request"]["duration"])
                    if rate["price_basis"] == "output_seconds"
                    else total
                    if rate["price_basis"] == "total_tokens"
                    else inp
                )
                value = count * D(rate["unit_price"]) / (1000000 if rate["unit"] == "1m_tokens" else 1) if count is not None else None
            else:
                value = None
    if supplier == "yseeai" and value is not None:
        value *= D(str(yprices[row["model"]].get("discount") or 1))
    actual = D(row["balance_delta_usd"]) if row.get("balance_delta_usd") is not None else None
    difference = actual - value if actual is not None and value is not None else None
    return {
        "input_tokens": str(inp) if inp is not None else None,
        "output_tokens": str(out) if out is not None else None,
        "total_tokens": str(total) if total is not None else None,
        "cache_tokens": str(cached),
        "cache_status": "hit" if cached else "zero_confirmed" if cache_reported else "not_reported",
        "expected_usd_no_cache": str(value) if value is not None else None,
        "balance_difference_usd": str(difference) if difference is not None else None,
        "rate": rate,
        "verdict": "缓存命中，排除无缓存验价"
        if cached
        else "未返回缓存用量，无缓存状态未确认"
        if row["kind"] == "chat" and not cache_reported
        else "缺少用量或费率"
        if value is None
        else "余额差与标价一致"
        if difference is not None and abs(difference) <= D("0.00001")
        else "余额差与标价存在差异，待核账",
    }


def main():
    state = json.loads((OUT / "run.json").read_text())
    extra = ROOT / ".runtime/comparison-nocache-20260922/run.json"
    if extra.exists():
        supplemental = json.loads(extra.read_text())
        state["supplemental_run_id"] = supplemental["run_id"]
        state["cases"].update({k + "--补测": v for k, v in supplemental["cases"].items()})
    # Read current archive state; recovery never changes the original charge evidence.
    with sqlite3.connect(f"file:{ROOT / '.runtime/service.db'}?mode=ro", uri=True) as db:
        for row in state["cases"].values():
            jid = row.get("job", {}).get("id")
            record = db.execute("SELECT status,result,usage,error FROM jobs WHERE id=?", (jid,)).fetchone() if jid else None
            if record:
                row["status"] = record[0]
                row["job"].update(status=record[0], result=json.loads(record[1]), usage=json.loads(record[2]), error=record[3])
    yp = {m["innerCode"]: m for m in json.loads((OUT / "yseeai-key-prices.json").read_text())["data"]}
    tp = {m["id"]: m for m in json.loads((OUT / "toapis-prices.json").read_text())["data"]}
    texts = {m["model_name"]: m for m in json.loads((OUT / "toapis-text-prices.json").read_text())["data"]}
    lines = [
        "# 双供应商模型与费用对比测试",
        "",
        "批次：`" + state["run_id"] + "`。复用 MV dev01 测试目录的秋雨空车站分镜，同模型两渠道输入一致。",
        "",
        "Toapis：按实扣积分 × 0.035 元计算；美元仅交叉核对。英和：保留美元实扣，人民币以 6.9 参考折算。忽略缓存价格，命中缓存的请求单列。余额差可能混入共享账户其他消费，不能替代逐任务账单。",
        "补测采用唯一请求前缀，GPT 同时传唯一 prompt_cache_key；缓存用量明确返回 0 才标记无缓存确认。上游未返回缓存字段不能当作 0。",
        "",
        "| 供应商 | 模型 | 状态 | 输入Token | 输出Token | 余额实扣USD | Toapis积分 | 人民币 | 验价 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    cards = []
    totals = {"yseeai": D(0), "toapis": D(0)}
    toapis_credits = D(0)
    for key, row in state["cases"].items():
        if "kind" not in row:
            continue
        calc = expected(row, yp, tp, texts)
        row["verification"] = calc
        cny = row.get("balance_delta_cny", row.get("balance_delta_cny_reference", "—"))
        totals[row["supplier"]] += D(row.get("balance_delta_usd", "0"))
        if row["supplier"] == "toapis":
            toapis_credits += D(row.get("balance_delta_credits", "0"))
        lines.append(
            "| "
            + " | ".join(
                [
                    row["supplier"],
                    row["model"] + ("（补测）" if key.endswith("补测") else ""),
                    row["status"],
                    calc["input_tokens"] or "缺失",
                    calc["output_tokens"] or "缺失",
                    row.get("balance_delta_usd", "—"),
                    row.get("balance_delta_credits", "—"),
                    cny,
                    calc["verdict"],
                ]
            )
            + " |"
        )
        media = row.get("job", {}).get("result", {}).get("media", [])
        previews = "".join(
            f'<video controls preload="metadata" src="{html.escape(m["url"], quote=True)}"></video>'
            if row["kind"] == "video"
            else f'<img loading="lazy" src="{html.escape(m["url"], quote=True)}"/>'
            for m in media
        )
        output = row.get("job", {}).get("result", {})
        text_output = (
            json.dumps(output, ensure_ascii=False, indent=2)
            if row["kind"] == "chat"
            else json.dumps(row.get("job", {}).get("error"), ensure_ascii=False)
        )
        cards.append(
            f"<article><h2>{html.escape(key)}</h2><p>{html.escape(row['status'])} · 人民币 {html.escape(cny)}</p>{previews}<details><summary>输入、输出与费用证据</summary><pre>{html.escape(json.dumps({'request': row['request'], 'source_task_id': row.get('source_task_id'), 'verification': calc, 'billing': row.get('job', {}).get('usage', {}).get('billing'), 'text_output': text_output}, ensure_ascii=False, indent=2))}</pre></details></article>"
        )
    lines.extend(
        [
            "",
            f"余额差合计：英和 ${totals['yseeai']}；Toapis {toapis_credits} 积分，人民币 ¥{toapis_credits * D('0.035')}。",
            "",
            "本测试不对图片、视频主观质量下结论，打开 HTML 报告人工核查；缺失 Token 保持缺失，不填 0。",
        ]
    )
    (OUT / "report.md").write_text("\n".join(lines) + "\n")
    (OUT / "evidence.json").write_text(json.dumps(state, ensure_ascii=False, indent=2))
    (OUT / "report.html").write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>模型费用与素材对比</title><style>body{font:16px system-ui;background:#f3f5f8;color:#172334;margin:32px}article{background:white;padding:24px;border-radius:16px;margin:20px 0}video,img{max-width:640px;width:100%;max-height:480px;object-fit:contain}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}h2{font-size:20px}</style><h1>英和海外 × Toapis 对比测试</h1><p>同一 MV 场景。Toapis 1000 积分＝35 元。媒体由用户人工核查；详细原始证据随报告保存。</p>'
        + "".join(cards)
        + "</html>"
    )
    print(OUT / "report.html")


if __name__ == "__main__":
    main()
