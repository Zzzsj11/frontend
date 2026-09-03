"""Final video-prompt policies that must hold regardless of the upstream LLM output."""

from __future__ import annotations

import re

IDENTITY_REFERENCE_MARKER = "人物身份参考硬约束"
_VAGUE_REFERENCE_PATTERNS = (
    re.compile(r"严格(?:参照|参考|遵循)人物参考图"),
    re.compile(r"人物(?:形象|造型|穿着|服装)与参考图(?:保持)?(?:严格)?一致"),
)


def compile_identity_safe_video_prompt(
    prompt: str,
    wardrobe_by_character: dict[str, str] | None = None,
    *,
    season: str = "",
) -> str:
    """Keep a character card's identity while making its placeholder styling non-authoritative."""
    source = prompt.strip()
    if IDENTITY_REFERENCE_MARKER in source:
        return source
    # 消除最容易让视频模型把“身份一致”误解为“整张图都照抄”的模糊指令；
    # 更具体的五官身份约束会在下方以最高优先级重新补齐。
    for pattern in _VAGUE_REFERENCE_PATTERNS:
        source = pattern.sub("严格保持人物面部身份与参考图一致", source)

    wardrobe = "；".join(value.strip() for value in (wardrobe_by_character or {}).values() if isinstance(value, str) and value.strip())
    season_rule = f"除非用户明确另有要求，服装必须严格符合{season}季的温度、天气与穿着逻辑。" if season else ""
    wardrobe_rule = (
        f"本镜必须明确描写并使用剧情造型：{wardrobe}。{season_rule}"
        if wardrobe
        else f"本镜必须明确描写服装，并按‘用户明确要求 > 季节 > 曲风 > 歌词与叙事 > 场景和动作 > 光线、色彩和视觉风格’重新设计。{season_rule}"
    )
    contract = (
        f"【{IDENTITY_REFERENCE_MARKER}】人物参考图只用于锁定五官、脸型、肤色、年龄感、发型和身体比例；"
        "纯白圆领T恤、浅灰棉质短裤、赤脚或基础鞋履、中性灰背景、多视图排版均为身份采集占位信息，"
        "绝对不得继承到剧情画面，也不得从参考图推断人物职业、年代或剧情。"
        f"{wardrobe_rule}若前文存在‘严格参考整张图’或与本约束冲突的描述，以本硬约束为准。"
    )
    return f"{source}\n\n{contract}"
