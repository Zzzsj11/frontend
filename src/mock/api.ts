import type { DigitalHuman } from '../types'
import { magicScripts, makeSceneImage, makeShotCover, makeSilentWav, mockDigitalHumans } from './data'
import type { MagicScript } from './data'

/**
 * Mock API 层 —— 模拟后端接口，每个函数对应一个规划中的 HTTP 接口：
 *  GET  /api/assets/digital-humans -> fetchDigitalHumans
 *  POST /api/script/magic          -> generateMagicScript
 *  POST /api/voice/generate        -> generateVoice
 *  POST /api/scene/generate        -> generateSceneImage
 *  POST /api/shot/generate-video   -> generateShotVideo
 *  POST /api/video/synthesize      -> synthesizeVideo
 */

const delay = (min = 800, max = 2000) =>
  new Promise<void>((resolve) => setTimeout(resolve, min + Math.random() * (max - min)))

/** GET /api/assets/digital-humans — 数字人资产列表 */
export async function fetchDigitalHumans(): Promise<DigitalHuman[]> {
  await delay(100, 300)
  return mockDigitalHumans
}

let magicIndex = 0
/** POST /api/script/magic — 返回一套 AI 生成的 MV 脚本（统一角色阵容 + 每分镜的歌词/场景/分镜提示词/出演角色） */
export async function generateMagicScript(): Promise<MagicScript> {
  await delay(1200, 2000)
  const script = magicScripts[magicIndex % magicScripts.length]
  magicIndex++
  return script
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

/** POST /api/shot/generate-video — 根据场景 + 分镜提示词 + 出演角色（可空/可多人）生成分镜视频片段 */
export async function generateShotVideo(
  _scenePrompt: string,
  _shotPrompt: string,
  digitalHumanIds: string[],
  index: number,
  variant: number,
): Promise<{ coverUrl: string; videoUrl: string; duration: number }> {
  await delay(1500, 3000)
  const dhNames = digitalHumanIds
    .map((id) => mockDigitalHumans.find((d) => d.id === id)?.name)
    .filter(Boolean)
    .join(' / ')
  const duration = Math.round((3 + Math.random() * 3) * 10) / 10 // 3~6s
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
