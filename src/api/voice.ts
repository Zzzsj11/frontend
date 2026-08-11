/**
 * 配音接口 —— 占位实现。
 * 后端配音接口尚未接入，当前返回静音 wav：时长驱动时间轴片段划分，
 * 音频地址接入播放器配音轨，保证配音链路（生成状态机 / 播放同步）可用。
 * 待后端 POST /api/voice/generate 就绪后替换为真实请求。
 */

const delay = (min = 800, max = 2000) =>
  new Promise<void>((resolve) => setTimeout(resolve, min + Math.random() * (max - min)))

/** 生成指定时长的静音 wav 音频（Blob URL） */
const makeSilentWav = (duration: number): string => {
  const sampleRate = 8000
  const dataLength = Math.max(1, Math.floor(sampleRate * duration))
  const buffer = new ArrayBuffer(44 + dataLength)
  const view = new DataView(buffer)
  const write = (offset: number, value: string) =>
    [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)))
  write(0, 'RIFF')
  view.setUint32(4, 36 + dataLength, true)
  write(8, 'WAVEfmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate, true)
  view.setUint16(32, 1, true)
  view.setUint16(34, 8, true)
  write(36, 'data')
  view.setUint32(40, dataLength, true)
  const bytes = new Uint8Array(buffer)
  bytes.fill(128, 44)
  return URL.createObjectURL(new Blob([buffer], { type: 'audio/wav' }))
}

/** POST /api/voice/generate（占位）— 返回当前分镜的演唱/配音音频与时长 */
export async function generateVoice(_lineId: string): Promise<{ url: string; duration: number }> {
  await delay()
  const duration = Math.round((2 + Math.random() * 4) * 10) / 10 // 2~6s
  return { url: makeSilentWav(duration), duration }
}
