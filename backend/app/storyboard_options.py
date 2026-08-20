"""通用分镜选项：内置种子数据 + 选项组装。

数据口径与前端 src/songCategories.ts 一致（曲库 2124 首打标统计，见根目录《歌曲类型三级分类.md》）。
启动时由 seed.py 幂等写入 storyboard_option_items 表；管理后台可增删改排序，
已生成项目 storyboard_config 存中文名，不受后续编辑影响。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from .models import StoryboardOptionItemModel

# kind 合法值：genre 为三级分类树，其余为平铺列表
OPTION_KINDS = ("genre", "season", "age_group", "visual_style")

# 画幅比例由视频模型能力决定，不进 storyboard_option_items（与默认视频模型 capabilities 口径一致）
DEFAULT_RATIOS = ["16:9", "9:16", "4:3", "1:1"]

DEFAULT_SEASONS = ["春", "夏", "秋", "冬", "通用"]
DEFAULT_AGE_GROUPS = ["少儿", "青少年", "青年", "中年", "老年"]
DEFAULT_VISUAL_STYLES = ["电影写实", "动漫", "国风", "复古", "赛博朋克"]

# 曲风三级分类树：(名称, 子级列表)；子级为字符串（叶）或嵌套元组；空列表 = 无下级分类
DEFAULT_GENRE_TREE: list[tuple[str, list]] = [
    (
        "流行歌曲",
        [
            ("爱情消极", ["失恋", "爱而不得", "背叛", "土味情歌"]),
            ("爱情积极", ["岁月守心", "青涩心动", "热恋情深", "勇敢追爱", "静待良缘", "烟火相伴", "土味情歌", "婚礼"]),
            ("通用积极", ["生活", "校园", "老年生活", "运动", "家庭", "职场"]),
            ("通用消极", ["生活", "老年生活", "家庭"]),
            ("亲情积极", ["感恩父母", "天伦之乐", "歌颂母爱"]),
            ("亲情消极", ["缅怀逝去", "父寻子"]),
            ("友谊积极", ["兄弟情", "闺蜜情"]),
            ("友谊消极", ["背刺"]),
        ],
    ),
    ("民族歌曲", ["草原类", "山歌", "藏族歌曲", "二人转", "陕北民歌"]),
    ("国风", ["古代", "现代", "宗教", "民国"]),
    ("红歌", ["歌颂祖国", "军营"]),
    ("舞曲", ["中文DJ", "电音", "慢摇"]),
    ("中文说唱", ["说唱元素", "人物元素"]),
    ("儿童歌曲", ["动漫", "校园"]),
    ("祝福歌曲", ["节日", "人物", "生日"]),
    ("戏曲", []),
    ("外语歌曲", ["日韩", "欧美"]),
    ("中文喊麦", []),
]


def seed_item_id(kind: str, path: str) -> str:
    """确定性种子 id：同名同路径幂等，重复启动/多实例不重复入库。"""
    return "soi-" + uuid.uuid5(uuid.NAMESPACE_URL, f"mv-agent/storyboard-option/{kind}/{path}").hex[:16]


def _option_node(item: StoryboardOptionItemModel, children_map: dict[str | None, list[StoryboardOptionItemModel]]) -> dict:
    node: dict = {"value": item.name, "label": item.name}
    if item.cast_policy:
        node["castPolicy"] = item.cast_policy
    children = [_option_node(child, children_map) for child in children_map.get(item.id, [])]
    if children:
        node["children"] = children
    return node


async def load_general_storyboard_options(db) -> dict:
    """组装公开端点响应（camelCase）：genres 三级树 + seasons/ageGroups/visualStyles/ratios。"""
    rows = list(
        (
            await db.execute(
                select(StoryboardOptionItemModel)
                .where(StoryboardOptionItemModel.deleted_at.is_(None))
                .order_by(StoryboardOptionItemModel.kind, StoryboardOptionItemModel.sort_order, StoryboardOptionItemModel.created_at)
            )
        )
        .scalars()
        .all()
    )
    children_map: dict[str | None, list[StoryboardOptionItemModel]] = {}
    for row in rows:
        if row.kind == "genre":
            children_map.setdefault(row.parent_id, []).append(row)
    flat = lambda kind: [row.name for row in rows if row.kind == kind]  # noqa: E731
    return {
        "genres": [_option_node(item, children_map) for item in children_map.get(None, [])],
        "seasons": flat("season"),
        "ageGroups": flat("age_group"),
        "visualStyles": flat("visual_style"),
        "ratios": list(DEFAULT_RATIOS),
    }


async def resolve_genre_cast_policy(db, genre: str, secondary: str | None, tertiary: str | None) -> str:
    """沿分类路径读取最深层显式策略；未配置时允许后端自动匹配系统人物。"""
    rows = list(
        (
            await db.execute(
                select(StoryboardOptionItemModel).where(
                    StoryboardOptionItemModel.kind == "genre",
                    StoryboardOptionItemModel.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    children: dict[str | None, list[StoryboardOptionItemModel]] = {}
    for row in rows:
        children.setdefault(row.parent_id, []).append(row)
    current_parent: str | None = None
    policy: str | None = None
    for name in (genre, secondary, tertiary):
        if not name:
            continue
        item = next((row for row in children.get(current_parent, []) if row.name == name), None)
        if not item:
            break
        if item.cast_policy:
            policy = item.cast_policy
        current_parent = item.id
    return policy or "optional_random"
