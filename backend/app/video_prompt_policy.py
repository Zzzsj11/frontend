"""Final video-prompt policies that must hold regardless of the upstream LLM output."""

from __future__ import annotations

import re

IDENTITY_REFERENCE_MARKER = "人物身份参考硬约束"
_VAGUE_REFERENCE_PATTERNS = (
    re.compile(r"严格(?:参照|参考|遵循)人物参考图"),
    re.compile(r"人物(?:形象|造型|穿着|服装)与参考图(?:保持)?(?:严格)?一致"),
)
_PUBLIC_CELEBRATION_PATTERN = re.compile(r"红歌|歌颂祖国|国庆|建国|爱国(?:主义)?")
_PUBLIC_CELEBRATION_REPLACEMENTS = (
    (re.compile(r"红歌\s*/\s*歌颂祖国"), "庄重、明亮、积极的节庆音乐氛围"),
    (re.compile(r"红歌"), "庄重昂扬的节庆音乐"),
    (re.compile(r"歌颂祖国"), "展现自然风光、现代城市与普通人的美好生活"),
    (re.compile(r"国庆(?:期间)?"), "公共节庆期间"),
    (re.compile(r"建国"), "城市发展"),
    (re.compile(r"爱国主义?"), "积极温暖的公共情感"),
)
_SAFE_RANDOM_EMPTY_MOTIFS = (
    "以日出下的山河、河流与云海为主体，镜头舒缓推进",
    "以明亮整洁的现代城市天际线和公共建筑为主体，镜头平稳移动",
    "以田野、桥梁和交通脉络组成的开阔景观为主体，避免任何文字特写",
)
_SAFE_RANDOM_CHARACTER_MOTIFS = (
    "表现普通家庭在明亮公共空间里的温暖相聚，人物自然微笑",
    "表现青年朋友在城市公园里轻松同行，动作真实克制",
    "表现普通劳动者完成日常工作后的轻松时刻，不突出职业制服或组织标志",
)
_PUBLIC_CELEBRATION_SAFETY_RULE = (
    "画面只表现自然风光、现代城市和普通人的日常幸福感；不得出现现实政治人物、军事行动、武器、冲突、新闻事件复刻、政治集会；不得出现旗帜、徽章、口号、地图边界或可读文字的特写。"
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


def _neutralize_public_celebration_terms(prompt: str) -> str:
    result = prompt
    for pattern, replacement in _PUBLIC_CELEBRATION_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    return result


def compile_general_random_provider_prompt(prompt: str, *, shot_type: str, shot_index: int) -> tuple[str, bool]:
    """Keep the UI prompt untouched while compiling risky category labels into concrete, benign visuals."""
    source = prompt.strip()
    if not _PUBLIC_CELEBRATION_PATTERN.search(source):
        return source, False
    neutral = _neutralize_public_celebration_terms(source)
    motifs = _SAFE_RANDOM_EMPTY_MOTIFS if shot_type == "empty" else _SAFE_RANDOM_CHARACTER_MOTIFS
    motif = motifs[max(0, shot_index) % len(motifs)]
    return f"{neutral}\n【安全视觉执行】{motif}。{_PUBLIC_CELEBRATION_SAFETY_RULE}", True


def compile_content_safety_retry_prompt(prompt: str, *, shot_type: str = "character", shot_index: int = 0) -> str:
    """Create one stricter visual-only retry after the provider rejects a generated output."""
    neutral = _neutralize_public_celebration_terms(prompt.strip())
    motifs = _SAFE_RANDOM_EMPTY_MOTIFS if shot_type == "empty" else _SAFE_RANDOM_CHARACTER_MOTIFS
    motif = motifs[(max(0, shot_index) + 1) % len(motifs)]
    return f"{neutral}\n【合规重试】{motif}。画面写实、温暖、克制，只呈现虚构的普通生活场景。{_PUBLIC_CELEBRATION_SAFETY_RULE}"
