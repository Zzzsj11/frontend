let idSeed = 0
export const nextId = (prefix = 'line') => `${prefix}-${Date.now()}-${idSeed++}`

export interface MagicScript {
  title: string
  cast: string[]
  /** 两阶段流程：上传仅完成时间轴拆分（parsed），大纲由独立端点生成 */
  status?: string
  lines: Array<{
    id?: string
    lyrics: string
    scenePrompt: string
    shotPrompt: string
    digitalHumanIds: string[]
    plannedDuration?: number
    shotOptions?: import('../types').ShotGenOptions
    shotType?: 'empty' | 'character'
    generationStatus?: 'pending' | 'running' | 'succeeded' | 'failed'
    /** ASS 时间轴起止时间（秒） */
    start?: number
    end?: number
  }>
}

export const makeSilentWav = (duration: number): string => {
  const sampleRate = 8000
  const dataLength = Math.max(1, Math.floor(sampleRate * duration))
  const buffer = new ArrayBuffer(44 + dataLength)
  const view = new DataView(buffer)
  const write = (offset: number, value: string) => [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)))
  write(0, 'RIFF'); view.setUint32(4, 36 + dataLength, true); write(8, 'WAVEfmt ')
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate, true)
  view.setUint16(32, 1, true); view.setUint16(34, 8, true); write(36, 'data'); view.setUint32(40, dataLength, true)
  const bytes = new Uint8Array(buffer); bytes.fill(128, 44)
  return URL.createObjectURL(new Blob([buffer], { type: 'audio/wav' }))
}
