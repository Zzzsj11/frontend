import type {
  DigitalHuman,
  GeneralStoryboardOptions,
  GeneralStoryboardRequest,
  GeneralStoryboardResult,
  ScriptLine,
  ShotGenOptions,
  SongProject,
} from '../types'
import {
  magicScripts,
  makeSceneImage,
  makeShotCover,
  makeSilentWav,
  makeSongScript,
  mockDigitalHumans,
  mockSongProjects,
  nextId,
} from './data'
import type { MagicScript } from './data'

/**
 * Mock API 层 —— 模拟后端接口，每个函数对应一个规划中的 HTTP 接口：
 *  GET  /api/songs                 -> fetchSongProjects
 *  GET  /api/songs/{id}/script     -> fetchSongScript
 *  POST /api/songs                 -> createSongProject
 *  GET  /api/assets/digital-humans -> fetchDigitalHumans
 *  POST /api/script/magic          -> generateMagicScript
 *  POST /api/voice/generate        -> generateVoice
 *  POST /api/scene/generate        -> generateSceneImage
 *  POST /api/shot/generate-video   -> generateShotVideo
 *  POST /api/video/synthesize      -> synthesizeVideo
 */

const delay = (min = 800, max = 2000) =>
  new Promise<void>((resolve) => setTimeout(resolve, min + Math.random() * (max - min)))

/** GET /api/songs — 歌曲项目列表（侧边栏目录，一个目录处理一首歌曲） */
export async function fetchSongProjects(): Promise<SongProject[]> {
  await delay(150, 400)
  return mockSongProjects.map((s) => ({ ...s, tasks: s.tasks.map((t) => ({ ...t })) }))
}

/** GET /api/songs/{id}/script — 载入某首歌曲的分镜脚本与角色阵容 */
export async function fetchSongScript(songId: string): Promise<{ cast: string[]; lines: ScriptLine[] }> {
  await delay(400, 900)
  return makeSongScript(songId)
}

/** POST /api/songs — 新建空歌曲项目，用户随后选择 ASS 分镜或通用分镜 */
export async function createSongProject(name: string): Promise<SongProject> {
  await delay(300, 600)
  return {
    id: nextId('song'),
    name,
    tasks: [],
  }
}

/** GET /api/assets/digital-humans — 数字人资产列表 */
export async function fetchDigitalHumans(): Promise<DigitalHuman[]> {
  await delay(100, 300)
  return mockDigitalHumans
}

let magicIndex = 0

/** POST /api/script/magic 的请求参数（规划为 multipart/form-data） */
export interface MagicScriptRequest {
  /** 歌曲编号 */
  songId: string
  /** 歌词字幕 .ass 文件 */
  assFile: File
  /** 从已有数字人角色库选择的角色 id（可空/可多选） */
  digitalHumanIds?: string[]
  /** 额外要求（可空） */
  extraRequirement?: string
}

/** POST /api/script/magic — 根据歌曲编号 + ass 字幕 + 已选角色生成一套 MV 脚本 */
export async function generateMagicScript(req?: MagicScriptRequest): Promise<MagicScript> {
  await delay(1200, 2000)
  const script = magicScripts[magicIndex % magicScripts.length]
  magicIndex++
  const selectedIds = (req?.digitalHumanIds ?? []).filter((id) =>
    mockDigitalHumans.some((human) => human.id === id),
  )
  if (!selectedIds.length) {
    return { cast: [...script.cast], lines: script.lines.map((line) => ({ ...line, digitalHumanIds: [...line.digitalHumanIds] })) }
  }
  let roleIndex = 0
  return {
    cast: [...selectedIds],
    lines: script.lines.map((line) => ({
      ...line,
      digitalHumanIds: line.digitalHumanIds.length
        ? [selectedIds[roleIndex++ % selectedIds.length]]
        : [],
    })),
  }
}

const generalStoryboardOptions: GeneralStoryboardOptions = {
  genres: [
    {
      value: 'pop', label: '流行', children: [
        { value: 'positive-love', label: '爱情积极', children: [
          { value: 'young-crush', label: '青涩心动' },
          { value: 'confession', label: '热烈告白' },
          { value: 'sweet-love', label: '甜蜜相恋' },
        ] },
        { value: 'negative-love', label: '爱情消极', children: [
          { value: 'regret', label: '遗憾错过' },
          { value: 'farewell', label: '失恋离别' },
          { value: 'lonely-memory', label: '孤独回忆' },
        ] },
        { value: 'inspiring', label: '励志', children: [
          { value: 'growth', label: '青春成长' },
          { value: 'dream', label: '追逐梦想' },
        ] },
      ],
    },
    {
      value: 'rock', label: '摇滚', children: [
        { value: 'passion', label: '热血', children: [
          { value: 'breakthrough', label: '突破束缚' },
          { value: 'live-stage', label: '现场舞台' },
        ] },
      ],
    },
    {
      value: 'folk', label: '民谣', children: [
        { value: 'narrative', label: '叙事', children: [
          { value: 'hometown', label: '故乡回忆' },
          { value: 'journey', label: '远方旅途' },
        ] },
      ],
    },
  ],
  seasons: ['春', '夏', '秋', '冬', '通用'],
  ageGroups: ['少儿', '青少年', '青年', '中年', '老年'],
  visualStyles: ['电影写实', '动漫', '国风', '复古', '赛博朋克'],
  ratios: ['16:9', '9:16', '4:3', '1:1'],
}

export async function fetchGeneralStoryboardOptions(): Promise<GeneralStoryboardOptions> {
  await delay(150, 350)
  return structuredClone(generalStoryboardOptions)
}

const emptyScenes = [
  ['深秋傍晚的城市旧街，潮湿路面倒映暖橙色路灯，金黄色落叶散落在石板路上', '低机位沿街道缓慢向前推进，落叶从镜头前掠过，浅景深，画面稳定，无人物出镜'],
  ['安静河岸边的空长椅，树叶在晚风中轻轻晃动，远处城市灯光刚刚亮起', '镜头从水面倒影缓慢抬升到长椅，轻微横摇，营造等待与思念的情绪'],
  ['老唱片机在暖色房间里缓慢旋转，唱针旁积着细小灰尘，窗外光线渐暗', '微距拍摄唱针落下，镜头沿唱片纹理缓慢旋转，柔和胶片颗粒'],
  ['空荡的旧火车站台延伸向远方，昏黄顶灯依次亮起，轨道泛着冷光', '大远景固定构图，列车灯光从远方靠近，风卷起站台上的落叶'],
  ['夜色中的天桥横跨城市车流，汽车灯光汇成流动光轨，天空呈深蓝色', '航拍镜头缓慢下降并向前推进，强调城市空间感和孤独氛围'],
]

const characterScenes = [
  ['老式公寓窗边，秋日余晖穿过薄纱窗帘，房间内漂浮细小尘埃', '歌手独自靠在窗边凝视远方，镜头从中景缓慢推进至面部近景，捕捉若有所思的微表情'],
  ['傍晚十字路口，人群在霓虹灯下匆匆经过，背景车辆虚化成彩色光斑', '歌手逆着人流缓慢前行，目光在人群中寻找熟悉身影，手持镜头平稳跟随'],
  ['临街咖啡馆靠窗座位，桌面放着两杯咖啡，其中一把椅子空着', '歌手抬头看见窗外熟悉背影，短暂停顿后起身，镜头快速跟焦到眼神变化'],
  ['旧车站候车区，电子钟闪烁，广播灯牌发出冷白色光线', '歌手站在站台边欲言又止，双手轻轻握紧，镜头绕人物小幅环拍'],
  ['城市天台的夜风吹动衣角，远方楼宇灯光铺满天际线', '歌手回头露出释然微笑，镜头缓慢后拉成远景，让人物融入城市夜色'],
]

export async function generateGeneralStoryboard(req: GeneralStoryboardRequest): Promise<GeneralStoryboardResult> {
  await delay(1200, 2000)
  const total = req.emptyShotCount + req.characterShotCount
  const plannedDuration = Math.round((req.totalDuration / total) * 10) / 10
  const cast = [...(req.digitalHumanIds ?? [])]
  const lines: GeneralStoryboardResult['lines'] = []
  let emptyIndex = 0
  let characterIndex = 0
  while (lines.length < total) {
    if (emptyIndex < req.emptyShotCount) {
      const [scene, shot] = emptyScenes[emptyIndex % emptyScenes.length]
      lines.push({
        shotType: 'empty', plannedDuration,
        scenePrompt: `${scene}。${req.season}季，${req.visualStyle}风格。`,
        shotPrompt: `${shot}。主题情绪：${req.tertiaryCategory || req.secondaryCategory}。${req.extraRequirement ?? ''}`.trim(),
        digitalHumanIds: [],
      })
      emptyIndex++
    }
    if (characterIndex < req.characterShotCount) {
      const [scene, shot] = characterScenes[characterIndex % characterScenes.length]
      const ids = cast.length ? [cast[characterIndex % cast.length]] : []
      lines.push({
        shotType: 'character', plannedDuration,
        scenePrompt: `${scene}。${req.season}季，${req.visualStyle}风格。`,
        shotPrompt: `${req.ageGroup}${req.singer ? `歌手${req.singer}` : '歌手'}，${shot}。主题情绪：${req.tertiaryCategory || req.secondaryCategory}。${req.extraRequirement ?? ''}`.trim(),
        digitalHumanIds: ids,
      })
      characterIndex++
    }
  }
  return {
    title: `通用分镜 · ${req.tertiaryCategory || req.secondaryCategory}`,
    cast,
    totalDuration: req.totalDuration,
    lines,
  }
}

/** POST /api/voice/generate — 返回当前分镜的演唱/配音音频与时长 */
export async function generateVoice(_lineId: string): Promise<{ url: string; duration: number }> {
  await delay()
  const duration = Math.round((2 + Math.random() * 4) * 10) / 10 // 2~6s
  return { url: makeSilentWav(duration), duration }
}

/** POST /api/scene/generate — 根据场景提示词生成分镜的背景场景图 */
export async function generateSceneImage(
  _scenePrompt: string,
  index: number,
  variant: number,
): Promise<{ imageUrl: string }> {
  await delay(1000, 2000)
  return { imageUrl: makeSceneImage(index, variant) }
}

/** POST /api/shot/generate-video — 根据场景 + 分镜提示词 + 出演角色（可空/可多人）+ 生成参数（清晰度/时长/画幅）生成分镜视频片段 */
export async function generateShotVideo(
  _scenePrompt: string,
  _shotPrompt: string,
  digitalHumanIds: string[],
  index: number,
  variant: number,
  options?: ShotGenOptions,
): Promise<{ coverUrl: string; videoUrl: string; duration: number }> {
  await delay(1500, 3000)
  const dhNames = digitalHumanIds
    .map((id) => mockDigitalHumans.find((d) => d.id === id)?.name)
    .filter(Boolean)
    .join(' / ')
  // 时长按所选参数生效；未指定时随机 3~6s（清晰度/画幅在 mock 阶段仅透传，不影响假素材）
  const duration = options?.duration ?? Math.round((3 + Math.random() * 3) * 10) / 10
  return {
    coverUrl: makeShotCover(index, variant, dhNames),
    videoUrl: `mock://video/shot-${index + 1}-v${variant + 1}.mp4`,
    duration,
  }
}

/** POST /api/video/synthesize — 模拟合成进度，最后返回假视频地址 */
export async function synthesizeVideo(onProgress: (p: number) => void): Promise<{ videoUrl: string }> {
  for (let p = 0; p <= 100; p += 5 + Math.floor(Math.random() * 10)) {
    onProgress(Math.min(p, 100))
    await delay(150, 350)
  }
  onProgress(100)
  return { videoUrl: 'mock://video/final.mp4' }
}
