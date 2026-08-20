# 歌曲类型三级分类

## 数据来源与口径

- **数据源**:`backend/app/data/song_emotions.json`（歌曲情感打标结果，源自《歌曲情感打标结果.xlsx》)，已导入生产库 `song_emotion_profiles` 表。
- **样本量**:2124 首歌曲（与生产库逐字段核对一致：2124 行、11 个一级分类、31 个非空「一级+二级」组合 + 2 个二级为空的组合 = 33，完全吻合）。
- **统计口径**:以每首歌的「一级分类 / 二级分类 / 三级分类」三个字段为准（已与拼接字段「素材分类」逐条反向校验，0 不一致）;JSON 中每个节点附 `count` 为该分类下的歌曲数量；同级按数量降序排列。

## 统计概览

| 一级分类 |   歌曲数 | 二级分类数 | 是否有三级                        |
| -------- | -------: | ---------: | --------------------------------- |
| 流行歌曲 |     1789 |          8 | 有（29 个三级全部挂在流行歌曲下） |
| 民族歌曲 |      107 |          5 | 无                                |
| 国风     |       69 |          4 | 无                                |
| 红歌     |       45 |          2 | 无                                |
| 舞曲     |       39 |          3 | 无                                |
| 中文说唱 |       22 |          2 | 无                                |
| 儿童歌曲 |       15 |          2 | 无                                |
| 祝福歌曲 |       12 |          3 | 无                                |
| 戏曲     |       11 |          0 | 无（仅一级）                      |
| 外语歌曲 |       11 |          2 | 无                                |
| 中文喊麦 |        4 |          0 | 无（仅一级）                      |
| **合计** | **2124** |     **31** | **29**                            |

## 数据质量核查

- **孤儿路径（下级存在但上级缺失）:0 条**，无需舍弃的数据。
- **仅有一级的歌曲 15 首**：戏曲 11 首、中文喊麦 4 首 —— 不属于缺失上级，因此保留为无下级的一级分类节点。
- **命名脏数据（首尾空格等）**：无。
- **同名三级挂不同二级**：`土味情歌` 同时存在于「爱情消极」(2 首）与「爱情积极」(3 首）下，为原始打标语义，按数据原样保留。

## 接入现状

分类树已迁移至后端 `storyboard_options` 表（kind=genre，三级树），种子数据由 `backend/app/storyboard_options.py` 写入，管理后台「通用分类」页可全量自定义（增删改、同级排序、种子重置）；前端经 `GET /api/storyboard-options` 动态拉取，通用分镜弹框（`GeneralStoryboardModal.vue`）直接使用下发数据。表单提交时经 `labelOf` 把中文分类名写入 `storyboard_config`，与曲库打标数据口径完全一致，也使 storyBible logline 与 LLM 上下文保持中文语义。

原前端硬编码树 `src/songCategories.ts`（`SONG_CATEGORY_GENRES`）已无任何引用，随本轮文档整治删除。

特殊处理：戏曲、中文喊麦无下级分类，选中后二级分类下拉禁用并提示「无下级分类」，留空即可提交；后端 `GeneralStoryboardCreate.secondary_category` 已同步改为可选，storyBible logline 拼接时跳过空段（如「戏曲 风格的完整 MV 视觉弧光…」）。

人物选择策略由分类节点的 `cast_policy` 配置并向下继承：`required` 表示有人物镜时必须由用户手动选角，`optional_random` 表示未选角时由后端仅从可用系统人物中按性别构成自动匹配。未配置节点默认 `optional_random`。种子分类「爱情积极」「爱情消极」配置为 `required`，其他分类默认允许自动匹配；人物镜数量为 0 时任何分类均无需选角。实际选中人物会写入任务角色阵容，后续大纲、逐镜提示词与媒体生成保持一致，不会在刷新或切换任务后重新随机。

## 三级分类 JSON

```json
[
  {
    "name": "流行歌曲",
    "count": 1789,
    "children": [
      {
        "name": "爱情消极",
        "count": 928,
        "children": [
          { "name": "失恋", "count": 417 },
          { "name": "爱而不得", "count": 363 },
          { "name": "背叛", "count": 146 },
          { "name": "土味情歌", "count": 2 }
        ]
      },
      {
        "name": "爱情积极",
        "count": 404,
        "children": [
          { "name": "岁月守心", "count": 128 },
          { "name": "青涩心动", "count": 91 },
          { "name": "热恋情深", "count": 90 },
          { "name": "勇敢追爱", "count": 43 },
          { "name": "静待良缘", "count": 28 },
          { "name": "烟火相伴", "count": 20 },
          { "name": "土味情歌", "count": 3 },
          { "name": "婚礼", "count": 1 }
        ]
      },
      {
        "name": "通用积极",
        "count": 172,
        "children": [
          { "name": "生活", "count": 150 },
          { "name": "校园", "count": 11 },
          { "name": "老年生活", "count": 5 },
          { "name": "运动", "count": 4 },
          { "name": "家庭", "count": 1 },
          { "name": "职场", "count": 1 }
        ]
      },
      {
        "name": "通用消极",
        "count": 167,
        "children": [
          { "name": "生活", "count": 164 },
          { "name": "老年生活", "count": 2 },
          { "name": "家庭", "count": 1 }
        ]
      },
      {
        "name": "亲情积极",
        "count": 59,
        "children": [
          { "name": "感恩父母", "count": 32 },
          { "name": "天伦之乐", "count": 15 },
          { "name": "歌颂母爱", "count": 12 }
        ]
      },
      {
        "name": "亲情消极",
        "count": 34,
        "children": [
          { "name": "缅怀逝去", "count": 31 },
          { "name": "父寻子", "count": 3 }
        ]
      },
      {
        "name": "友谊积极",
        "count": 22,
        "children": [
          { "name": "兄弟情", "count": 17 },
          { "name": "闺蜜情", "count": 5 }
        ]
      },
      {
        "name": "友谊消极",
        "count": 3,
        "children": [{ "name": "背刺", "count": 3 }]
      }
    ]
  },
  {
    "name": "民族歌曲",
    "count": 107,
    "children": [
      { "name": "草原类", "count": 49 },
      { "name": "山歌", "count": 48 },
      { "name": "藏族歌曲", "count": 8 },
      { "name": "二人转", "count": 1 },
      { "name": "陕北民歌", "count": 1 }
    ]
  },
  {
    "name": "国风",
    "count": 69,
    "children": [
      { "name": "古代", "count": 47 },
      { "name": "现代", "count": 16 },
      { "name": "宗教", "count": 5 },
      { "name": "民国", "count": 1 }
    ]
  },
  {
    "name": "红歌",
    "count": 45,
    "children": [
      { "name": "歌颂祖国", "count": 36 },
      { "name": "军营", "count": 9 }
    ]
  },
  {
    "name": "舞曲",
    "count": 39,
    "children": [
      { "name": "中文DJ", "count": 18 },
      { "name": "电音", "count": 17 },
      { "name": "慢摇", "count": 4 }
    ]
  },
  {
    "name": "中文说唱",
    "count": 22,
    "children": [
      { "name": "说唱元素", "count": 17 },
      { "name": "人物元素", "count": 5 }
    ]
  },
  {
    "name": "儿童歌曲",
    "count": 15,
    "children": [
      { "name": "动漫", "count": 9 },
      { "name": "校园", "count": 6 }
    ]
  },
  {
    "name": "祝福歌曲",
    "count": 12,
    "children": [
      { "name": "节日", "count": 9 },
      { "name": "人物", "count": 2 },
      { "name": "生日", "count": 1 }
    ]
  },
  { "name": "戏曲", "count": 11 },
  {
    "name": "外语歌曲",
    "count": 11,
    "children": [
      { "name": "日韩", "count": 6 },
      { "name": "欧美", "count": 5 }
    ]
  },
  { "name": "中文喊麦", "count": 4 }
]
```
