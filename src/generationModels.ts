import { reactive } from 'vue'
import { apiRequest } from './api/client'

export type ImageModelId = string
export type VideoModelId = string
export interface GenerationModelCapabilities {
  executionConcurrency?: number
  executionPool?: string
  nativeAudio?: boolean
  referenceImage?: { min?: number; max?: number }
  h3Modes?: Array<'auto' | 'text' | 'first_frame' | 'first_last' | 'reference'>
  [key: string]: unknown
}
interface GenerationModelOption {
  value: string
  label: string
  capabilities?: GenerationModelCapabilities
}
export const DEFAULT_IMAGE_MODEL: ImageModelId = 'gpt-image-2'
export const DEFAULT_VIDEO_MODEL: VideoModelId = 'doubao-seedance-2.0'
export const IMAGE_MODEL_OPTIONS = reactive<Array<GenerationModelOption>>([
  { value: DEFAULT_IMAGE_MODEL, label: 'Img2' },
])
export const VIDEO_MODEL_OPTIONS = reactive<Array<GenerationModelOption>>([
  { value: DEFAULT_VIDEO_MODEL, label: 'SD2.0' },
])
export const videoModelConcurrency = (modelId?: string): number => {
  const configured = VIDEO_MODEL_OPTIONS.find((item) => item.value === modelId)?.capabilities
    ?.executionConcurrency
  return Number.isFinite(configured) ? Math.max(1, Number(configured)) : 200
}
export const generationModelLabel = (option: GenerationModelOption): string => {
  const concurrency = option.capabilities?.executionConcurrency
  return Number.isFinite(concurrency) && Number(concurrency) < 200
    ? `${option.label}（并发上限 ${Number(concurrency)}）`
    : option.label
}
let loaded = false
export async function loadGenerationModels(force = false): Promise<void> {
  if (loaded && !force) return
  try {
    const items = await apiRequest<
      Array<{
        id: string
        name: string
        modality: string
        capabilities?: GenerationModelCapabilities
      }>
    >('/model-options')
    const images = items
      .filter((x) => x.modality === 'image')
      .map((x) => ({ value: x.id, label: x.name, capabilities: x.capabilities }))
    const videos = items
      .filter((x) => x.modality === 'video')
      .map((x) => ({ value: x.id, label: x.name, capabilities: x.capabilities }))
    if (images.length) IMAGE_MODEL_OPTIONS.splice(0, IMAGE_MODEL_OPTIONS.length, ...images)
    if (videos.length) VIDEO_MODEL_OPTIONS.splice(0, VIDEO_MODEL_OPTIONS.length, ...videos)
    loaded = true
  } catch {
    /* 保留内置默认模型，避免配置中心暂时不可用时阻断创作 */
  }
}
