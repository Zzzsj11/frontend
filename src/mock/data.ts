import type { DigitalHuman, ScriptLine, SongProject } from '../types'
import { buildPortraitPrompt } from '../api/imageGen'

let idSeed = 0
export const nextId = (prefix = 'line') => `${prefix}-${Date.now()}-${idSeed++}`

/** 数字人基础信息（头像由英和生图 API 预生成，本地化存储在 public/digital-humans/） */
const dhSeeds: Array<Omit<DigitalHuman, 'avatar' | 'avatarPrompt'>> = [
  { id: 'dh-luoli', name: '洛璃', style: '国风', description: '汉服古典美人，适合国风、古典意境场景' },
  { id: 'dh-xiner', name: '芯儿', style: '赛博朋克', description: '未来感机能少女，适合夜景霓虹、科幻场景' },
  { id: 'dh-hoshino', name: '星野', style: '二次元', description: '动漫风元气少年，适合校园、热血场景' },
  { id: 'dh-suwan', name: '苏晚', style: '写实', description: '真实系文艺女生，适合都市生活、情感叙事场景' },
  { id: 'dh-mia', name: '米娅', style: '虚拟偶像', description: '舞台系虚拟偶像，适合演出、打歌舞台场景' },
  { id: 'dh-ahao', name: '阿豪', style: '街头潮流', description: '嘻哈潮男，适合街舞、涂鸦街区场景' },
  { id: 'dh-manlu', name: '曼露', style: '复古港风', description: '90年代港风女郎，适合怀旧、霓虹夜色场景' },
  { id: 'dh-linxiao', name: '林霄', style: '商务', description: '干练商务精英，适合都市职场、纪实场景' },
  { id: 'dh-noona', name: '누나', style: '韩系青春', description: '24岁温柔文艺年上女性，黑长直中分披肩，米白针织开衫浅色长裙' },
  { id: 'dh-sonyeon', name: '少年', style: '韩系青春', description: '18岁清瘦敏感少年，深棕短发微乱，白衬衫深色外套' },
]

/** 数字人资产库 */
export const mockDigitalHumans: DigitalHuman[] = dhSeeds.map((s) => ({
  ...s,
  avatar: `/digital-humans/${s.id}.png`,
  avatarPrompt: buildPortraitPrompt(s.description, s.style),
}))

/** 审核 MV「누난 너무 예뻐」前 5 个分镜（真实视频位于 public/review-mv/） */
interface ReviewShot {
  lyrics: string
  /** 歌词中文翻译（歌词非中文时展示） */
  lyricsZh?: string
  scenePrompt: string
  shotPrompt: string
  digitalHumanIds: string[]
  video: string
  duration: number
}

const reviewShots: ReviewShot[] = [
  {
    lyrics: '(前奏)',
    scenePrompt: '清晨空无一人的房间，白色窗帘在微风中轻轻飘动，阳光透过窗帘洒在木质地板上形成温暖的光斑。桌上放着一杯凉了的咖啡，旁边是一本翻开的笔记本。空气中浮动着细小的尘埃，在阳光下闪烁。',
    shotPrompt: '韩式青春电影风格，静谧抒情氛围。清晨空房间，白色亚麻窗帘在微风中轻摆，阳光从窗户洒入在木地板上形成温暖光斑。桌上放着一杯凉咖啡和一本翻开的手写笔记本，纸上隐约可见韩文字迹。大远景，平视角度，缓慢横摇运镜，从左至右缓缓扫过房间，带出空间感与故事感。暖金色调，柔和晨光，空气中微尘在光柱中浮动，静谧而温柔。高清电影质感，画面稳定无变形，保持无字幕，不要生成水印，不要生成Logo。',
    digitalHumanIds: [],
    video: '/review-mv/shot_01.mp4',
    duration: 7,
  },
  {
    lyrics: '(前奏)',
    scenePrompt: '少年独自坐在窗边木椅上，晨光在他身上勾勒出柔和的轮廓。他侧脸对着镜头，目光凝视远方，嘴角带着一丝苦涩的微笑。窗外是城市清晨的轮廓。',
    shotPrompt: '韩式青春电影风格，静谧抒情氛围。一位18岁韩系少年坐在窗边木椅上，深棕色短发微乱，穿白色宽松衬衫，清瘦身形，晨光勾勒出他的侧脸轮廓，微微侧头望向窗外远方，嘴角带着苦涩微笑。近景，平视角度，缓慢推进运镜，镜头缓缓靠近捕捉面部微表情。金色暖色调，逆光勾勒发丝轮廓，柔和晨光从窗户洒入。高清电影质感，人物面部稳定不变形、五官清晰、动作连贯自然，保持无字幕，不要生成水印，不要生成Logo。',
    digitalHumanIds: ['dh-sonyeon'],
    video: '/review-mv/shot_02.mp4',
    duration: 7,
  },
  {
    lyrics: '누난 너무 예뻐서 남자들이 가만 안 둬',
    lyricsZh: '姐姐太漂亮了，男生们都不会放过她',
    scenePrompt: '秋日校园林荫道，金色落叶铺满小路，阳光透过树叶缝隙洒下斑驳光影。一位长发女子走在路上，裙摆随风轻扬，所有路过的男生都忍不住回头看她。少年站在人群后远远望着她。',
    shotPrompt: '韩式青春MV风格，温暖回忆氛围。秋日校园林荫道，满地金黄落叶，阳光透过树叶缝隙洒下斑驳光影。一位24岁韩系长发女子，黑色长发中分披肩，穿米白色长款针织开衫和浅色长裙，在金色阳光下缓步行走，裙摆随风轻轻摆动。周圍男生纷纷回头注目。少年站在远处树下默默注视。全景，平视角度，慢动作跟拍运镜。暖金色秋日色调，逆光勾勒人物轮廓，斑驳树影洒落一地。高清电影质感，人物面部稳定不变形、五官清晰、动作连贯自然，保持无字幕，不要生成水印，不要生成Logo，视频全程禁止出现外形、着装、配饰完全一致的人物，禁止生成同款分身、双胞胎效果。',
    digitalHumanIds: ['dh-noona', 'dh-sonyeon'],
    video: '/review-mv/shot_03.mp4',
    duration: 9,
  },
  {
    lyrics: '흔들리는 그녀의 맘 사실 알고 있어',
    lyricsZh: '其实我知道她那颤动的心',
    scenePrompt: '学校天台，傍晚时分天空泛着蓝紫色。少年独自靠在围栏边，低头轻声自语。城市天际线在远方展开。风吹动他的头发和衣角。',
    shotPrompt: '韩式青春电影风格，忧伤氛围。学校天台傍晚，蓝紫色天空泛着暮色余晖，城市天际线在远方展开。18岁少年靠在铁网围栏边，双手撑在栏杆上微微低头，风吹动他的深棕色碎发和白色衬衫衣角，他抬眼望向远方，轻轻叹了口气。中景，微微仰视角度，固定镜头，沉稳构图。蓝紫暮色调，天空自然光，微风吹拂的静谧感。高清电影质感，人物面部稳定不变形、五官清晰、动作连贯自然，保持无字幕，不要生成水印，不要生成Logo。',
    digitalHumanIds: ['dh-sonyeon'],
    video: '/review-mv/shot_04.mp4',
    duration: 9,
  },
  {
    lyrics: '아마 그녀는 어린 내가 부담스러운가봐 날 바라보는 눈빛이 말해주잖아',
    lyricsZh: '也许她觉得年少的我是种负担，她看我的眼神已经说明了一切',
    scenePrompt: '温馨的小咖啡馆，阳光透过玻璃窗，窗外街景模糊。两人面对面坐着，女子低头搅动咖啡杯，眼神闪烁躲闪，笑得勉强。少年直视着她，眼中有不安和心酸。',
    shotPrompt: '韩式青春电影风格，微妙的紧张氛围。温馨小咖啡馆，午后阳光透过玻璃窗洒在木桌面上，空气中飘浮着细微的咖啡香气。24岁长发女子和18岁少年面对面坐着，女子低头搅动咖啡，目光闪躲不愿直视，嘴角挂着勉强的礼貌微笑。少年直直望着她，眼神中有不安和心酸，放在桌上的手指微微攥紧。近景，平视角度，缓慢推近运镜，镜头缓缓靠近捕捉两人微妙的表情互动。暖黄色室内调，窗外自然侧光，咖啡蒸汽在光线下袅袅升腾。高清电影质感，人物面部稳定不变形、五官清晰、动作连贯自然，保持无字幕，不要生成水印，不要生成Logo，视频全程禁止出现外形、着装、配饰完全一致的人物，禁止生成同款分身、双胞胎效果。',
    digitalHumanIds: ['dh-noona', 'dh-sonyeon'],
    video: '/review-mv/shot_05.mp4',
    duration: 12,
  },
]

/** 初始脚本（一条 = 一个分镜）：直接载入审核 MV 的前 5 个真实分镜 */
export const makeReviewLines = (): ScriptLine[] =>
  reviewShots.map((s): ScriptLine => {
    const assetId = nextId('asset')
    return {
      id: nextId(),
      lyrics: s.lyrics,
      lyricsZh: s.lyricsZh,
      scenePrompt: s.scenePrompt,
      shotPrompt: s.shotPrompt,
      digitalHumanIds: [...s.digitalHumanIds],
      voice: { status: 'none' },
      scene: { status: 'none' },
      shot: {
        status: 'done',
        currentAssetId: assetId,
        assets: [
          {
            id: assetId,
            coverUrl: '',
            videoUrl: s.video,
            duration: s.duration,
            digitalHumanIds: [...s.digitalHumanIds],
          },
        ],
      },
    }
  })

export const initialLines: ScriptLine[] = makeReviewLines()

/** 审核 MV 的全局角色阵容（女主 누나 + 男主 少年） */
export const initialCastIds = ['dh-noona', 'dh-sonyeon']

/** 歌曲项目列表（侧边栏目录：一个目录处理一首歌曲，目录下是处理任务） */
export const mockSongProjects: SongProject[] = [
  {
    id: 'song-nunan',
    name: '누난 너무 예뻐 (Replay)',
    artist: 'SHINee',
    tasks: [{ id: 'task-nunan-1', title: 'MV 分镜制作', updatedAt: '刚刚' }],
  },
  {
    id: 'song-night',
    name: '夜色搁浅',
    artist: '原创 demo',
    tasks: [{ id: 'task-night-1', title: '歌词分镜草稿', updatedAt: '3天' }],
  },
  {
    id: 'song-station',
    name: '旧车站',
    artist: '原创 demo',
    tasks: [{ id: 'task-station-1', title: '场景概念设计', updatedAt: '5天' }],
  },
  { id: 'song-new', name: '未命名新歌', tasks: [] },
]

/** 按歌曲 id 生成对应的分镜脚本与角色阵容（未知歌曲返回空脚本） */
export function makeSongScript(songId: string): { cast: string[]; lines: ScriptLine[] } {
  if (songId === 'song-nunan') return { cast: [...initialCastIds], lines: makeReviewLines() }
  const magic =
    songId === 'song-night' ? magicScripts[0] : songId === 'song-station' ? magicScripts[1] : undefined
  if (!magic) return { cast: [], lines: [] }
  return {
    cast: [...magic.cast],
    lines: magic.lines.map(
      (item): ScriptLine => ({
        id: nextId(),
        lyrics: item.lyrics,
        scenePrompt: item.scenePrompt,
        shotPrompt: item.shotPrompt,
        digitalHumanIds: [...item.digitalHumanIds],
        voice: { status: 'none' },
        scene: { status: 'none' },
        shot: { status: 'none', assets: [] },
      }),
    ),
  }
}

/** AI 魔法脚本预置假数据：每套脚本带一个统一的角色阵容（cast），
 *  每个分镜只从阵容中挑选出演角色（可为空 = 空镜头，也可多人同框） */
export interface MagicScript {
  cast: string[]
  lines: Array<{ lyrics: string; scenePrompt: string; shotPrompt: string; digitalHumanIds: string[] }>
}

export const magicScripts: MagicScript[] = [
  {
    cast: ['dh-suwan', 'dh-manlu'],
    lines: [
      { lyrics: '夜色滑过城市的天际线', scenePrompt: '航拍城市夜景，霓虹灯光划过天际线，赛博朋克色调', shotPrompt: '空镜头，电影感镜头缓慢推进，俯瞰城市车流光轨', digitalHumanIds: [] },
      { lyrics: '你的影子在人潮里搁浅', scenePrompt: '拥挤的十字路口，人潮虚化流动，霓虹招牌闪烁', shotPrompt: '曼露逆光静止站立，人潮从身旁匆匆流过，浅景深特写', digitalHumanIds: ['dh-manlu'] },
      { lyrics: '我数着路灯一盏一盏熄灭', scenePrompt: '空旷街道路灯依次熄灭，暖黄光晕渐暗，孤独氛围', shotPrompt: '苏晚独自漫步，低角度慢镜头跟随，回头望向熄灭的路灯', digitalHumanIds: ['dh-suwan'] },
      { lyrics: '把心事折进未寄出的信件', scenePrompt: '木桌上手写信纸与信封，柔和台灯光，怀旧胶片质感', shotPrompt: '空镜头，钢笔落笔特写，镜头缓慢上移到窗外夜色', digitalHumanIds: [] },
      { lyrics: '风把回忆吹成漫天的雪', scenePrompt: '雪夜街头，雪花在灯光中飞舞旋转，冷蓝色调', shotPrompt: '苏晚与曼露雪中相遇对望，唯美慢动作环绕镜头', digitalHumanIds: ['dh-suwan', 'dh-manlu'] },
    ],
  },
  {
    cast: ['dh-hoshino', 'dh-ahao'],
    lines: [
      { lyrics: '清晨的光落在旧车站', scenePrompt: '清晨老式火车站台，金色阳光穿过玻璃顶棚，蒸汽弥漫，日系清新色调', shotPrompt: '空镜头，光束中尘埃浮动，镜头横移扫过空无一人的站台', digitalHumanIds: [] },
      { lyrics: '你背着吉他走向远方', scenePrompt: '延伸向远方的铁轨，广角构图，青春公路片风格', shotPrompt: '星野背吉他沿铁轨远走的背影，逆光剪影，镜头缓慢拉远', digitalHumanIds: ['dh-hoshino'] },
      { lyrics: '车窗外的麦田一晃而过', scenePrompt: '车窗视角金色麦田飞速掠过，运动模糊，暖阳高饱和，夏日气息', shotPrompt: '空镜头，贴着车窗的飞速横移镜头，麦浪起伏', digitalHumanIds: [] },
      { lyrics: '梦想在口袋里叮当作响', scenePrompt: '涂鸦街区街角，午后阳光斜射，暖色胶片', shotPrompt: '阿豪掏出口袋里的吉他拨片抛接，微距浅景深特写切全景', digitalHumanIds: ['dh-ahao'] },
      { lyrics: '我们终将在山顶再见', scenePrompt: '山顶云海日出，大远景，史诗感暖金色光', shotPrompt: '星野与阿豪山顶并肩眺望云海，航拍环绕镜头拉升', digitalHumanIds: ['dh-hoshino', 'dh-ahao'] },
    ],
  },
]

/** 场景底图占位（SVG data-uri，16:9，无播放标识，代表静态场景图） */
const sceneColors = ['#34495e', '#6c5b7b', '#355c4a', '#7d5a3c', '#3a5f7d', '#5b4a6e']
export const makeSceneImage = (index: number, variant = 0) => {
  const color = sceneColors[(index + variant) % sceneColors.length]
  const label = `场景 ${String(index + 1).padStart(2, '0')} · v${variant + 1}`
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><defs><linearGradient id="s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}"/><stop offset="1" stop-color="#15181d"/></linearGradient></defs><rect width="640" height="360" fill="url(#s)"/><circle cx="500" cy="90" r="36" fill="rgba(255,255,255,0.25)"/><path d="M0 300 L140 210 L260 280 L400 190 L640 290 L640 360 L0 360 Z" fill="rgba(0,0,0,0.35)"/><text x="320" y="330" font-size="22" text-anchor="middle" fill="rgba(255,255,255,0.85)" font-family="sans-serif">${label}</text></svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

/** 分镜视频封面占位图（SVG data-uri，含播放标识与出演角色名） */
const shotColors = ['#2c3e50', '#8e44ad', '#c0392b', '#16a085', '#d35400', '#2980b9']
export const makeShotCover = (index: number, variant = 0, dhNames?: string) => {
  const color = shotColors[(index + variant) % shotColors.length]
  const label = `分镜 ${String(index + 1).padStart(2, '0')} · v${variant + 1} · ${dhNames || '空镜头'}`
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="${color}"/><circle cx="320" cy="160" r="52" fill="rgba(255,255,255,0.22)"/><path d="M305 135 L350 160 L305 185 Z" fill="rgba(255,255,255,0.85)"/><rect x="200" y="250" width="240" height="14" rx="7" fill="rgba(255,255,255,0.35)"/><text x="320" y="330" font-size="22" text-anchor="middle" fill="rgba(255,255,255,0.85)" font-family="sans-serif">${label}</text></svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

/** 生成一段静音 wav 的 data-uri，时长 duration 秒（8kHz 单声道 8bit） */
export const makeSilentWav = (duration: number) => {
  const sampleRate = 8000
  const numSamples = Math.floor(sampleRate * duration)
  const dataSize = numSamples
  const buffer = new ArrayBuffer(44 + dataSize)
  const view = new DataView(buffer)
  const writeStr = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i))
  }
  writeStr(0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true)
  writeStr(8, 'WAVE')
  writeStr(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate, true)
  view.setUint16(32, 1, true)
  view.setUint16(34, 8, true)
  writeStr(36, 'data')
  view.setUint32(40, dataSize, true)
  // 填充 128（8bit PCM 的静音值）
  new Uint8Array(buffer, 44).fill(128)
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
  return `data:audio/wav;base64,${btoa(binary)}`
}
