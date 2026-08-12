import type { StoryboardCategoryOption } from './types'

const leaf = (name: string): StoryboardCategoryOption => ({ value: name, label: name })
const node = (name: string, children: StoryboardCategoryOption[]): StoryboardCategoryOption => ({
  value: name,
  label: name,
  children,
})

/**
 * 通用分镜「音乐属性」三级分类 —— 由曲库打标数据统计得出（2124 首，
 * backend/app/data/song_emotions.json，已与生产库 song_emotion_profiles 核对一致），
 * 统计明细见项目根目录《歌曲类型三级分类.md》。
 * 同级按曲库歌曲数量降序；戏曲、中文喊麦无下级分类（提交时二级留空）。
 * value 与 label 均为中文分类名，与后端 storyboard_config 存储口径一致。
 */
export const SONG_CATEGORY_GENRES: StoryboardCategoryOption[] = [
  node('流行歌曲', [
    node('爱情消极', [leaf('失恋'), leaf('爱而不得'), leaf('背叛'), leaf('土味情歌')]),
    node('爱情积极', [
      leaf('岁月守心'),
      leaf('青涩心动'),
      leaf('热恋情深'),
      leaf('勇敢追爱'),
      leaf('静待良缘'),
      leaf('烟火相伴'),
      leaf('土味情歌'),
      leaf('婚礼'),
    ]),
    node('通用积极', [
      leaf('生活'),
      leaf('校园'),
      leaf('老年生活'),
      leaf('运动'),
      leaf('家庭'),
      leaf('职场'),
    ]),
    node('通用消极', [leaf('生活'), leaf('老年生活'), leaf('家庭')]),
    node('亲情积极', [leaf('感恩父母'), leaf('天伦之乐'), leaf('歌颂母爱')]),
    node('亲情消极', [leaf('缅怀逝去'), leaf('父寻子')]),
    node('友谊积极', [leaf('兄弟情'), leaf('闺蜜情')]),
    node('友谊消极', [leaf('背刺')]),
  ]),
  node('民族歌曲', [
    leaf('草原类'),
    leaf('山歌'),
    leaf('藏族歌曲'),
    leaf('二人转'),
    leaf('陕北民歌'),
  ]),
  node('国风', [leaf('古代'), leaf('现代'), leaf('宗教'), leaf('民国')]),
  node('红歌', [leaf('歌颂祖国'), leaf('军营')]),
  node('舞曲', [leaf('中文DJ'), leaf('电音'), leaf('慢摇')]),
  node('中文说唱', [leaf('说唱元素'), leaf('人物元素')]),
  node('儿童歌曲', [leaf('动漫'), leaf('校园')]),
  node('祝福歌曲', [leaf('节日'), leaf('人物'), leaf('生日')]),
  leaf('戏曲'),
  node('外语歌曲', [leaf('日韩'), leaf('欧美')]),
  leaf('中文喊麦'),
]
