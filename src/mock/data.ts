import type { DigitalHuman, ScriptLine } from '../types'

let idSeed = 0
export const nextId = (prefix = 'line') => `${prefix}-${Date.now()}-${idSeed++}`

/** 数字人头像占位（3:4 竖版 SVG，按风格配色） */
const makePortrait = (color: string, accent: string, label: string, style: string) => {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="320"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}"/><stop offset="1" stop-color="${accent}"/></linearGradient></defs><rect width="240" height="320" fill="url(#g)"/><circle cx="120" cy="118" r="52" fill="rgba(255,255,255,0.85)"/><circle cx="120" cy="102" r="22" fill="${color}"/><path d="M78 168 a42 42 0 0 1 84 0 v6 h-84 z" fill="${color}"/><text x="120" y="248" font-size="30" text-anchor="middle" fill="#fff" font-family="sans-serif" font-weight="bold">${label}</text><text x="120" y="286" font-size="16" text-anchor="middle" fill="rgba(255,255,255,0.85)" font-family="sans-serif">${style}</text></svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

/** 数字人资产库 */
export const mockDigitalHumans: DigitalHuman[] = [
  { id: 'dh-luoli', name: '洛璃', style: '国风', avatar: makePortrait('#b03a48', '#5c1f2e', '洛璃', '国风'), description: '汉服古典美人，适合国风、古典意境场景' },
  { id: 'dh-xiner', name: '芯儿', style: '赛博朋克', avatar: makePortrait('#7b2ff7', '#1a1040', '芯儿', '赛博朋克'), description: '未来感机能少女，适合夜景霓虹、科幻场景' },
  { id: 'dh-hoshino', name: '星野', style: '二次元', avatar: makePortrait('#4aa3f0', '#1e3a6e', '星野', '二次元'), description: '动漫风元气少年，适合校园、热血场景' },
  { id: 'dh-suwan', name: '苏晚', style: '写实', avatar: makePortrait('#8a9a80', '#3d4a38', '苏晚', '写实'), description: '真实系文艺女生，适合都市生活、情感叙事场景' },
  { id: 'dh-mia', name: '米娅', style: '虚拟偶像', avatar: makePortrait('#f06292', '#8e2456', '米娅', '虚拟偶像'), description: '舞台系虚拟偶像，适合演出、打歌舞台场景' },
  { id: 'dh-ahao', name: '阿豪', style: '街头潮流', avatar: makePortrait('#f39c12', '#7d4e00', '阿豪', '街头潮流'), description: '嘻哈潮男，适合街舞、涂鸦街区场景' },
  { id: 'dh-manlu', name: '曼露', style: '复古港风', avatar: makePortrait('#c0687a', '#4e2430', '曼露', '复古港风'), description: '90年代港风女郎，适合怀旧、霓虹夜色场景' },
  { id: 'dh-linxiao', name: '林霄', style: '商务', avatar: makePortrait('#5c7a99', '#26384c', '林霄', '商务'), description: '干练商务精英，适合都市职场、纪实场景' },
]

/** 初始脚本（一条 = 一个分镜） */
export const initialLines: ScriptLine[] = [
  {
    id: nextId(),
    lyrics: '夜色滑过城市的天际线',
    scenePrompt: '航拍城市夜景，霓虹灯光划过天际线，赛博朋克色调',
    shotPrompt: '电影感镜头缓慢推进，角色站在天台边缘眺望城市，发丝随风飘动',
    digitalHumanIds: ['dh-xiner'],
    voice: { status: 'none' },
    scene: { status: 'none' },
    shot: { status: 'none', assets: [] },
  },
]

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
