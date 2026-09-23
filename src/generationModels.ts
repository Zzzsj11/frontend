import { reactive } from 'vue'
import { apiRequest } from './api/client'

export type ImageModelId = string
export type VideoModelId = string
export interface GenerationModelCapabilities {
  billing?: {
    provider?: string
    unitPricePerSecond?: number
    balanceCheck?: boolean
    billingMode?: string
    currency?: string
  }
  executionConcurrency?: number
  executionPool?: string
  durationOptions?: number[]
  durations?: { min?: number; max?: number }
  nativeAudio?: boolean
  providerCode?: string
  sortOrder?: number
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
export const DEFAULT_VIDEO_RESOLUTIONS = ['480p', '720p', '1080p'] as const
export const IMAGE_MODEL_OPTIONS = reactive<Array<GenerationModelOption>>([
  { value: DEFAULT_IMAGE_MODEL, label: 'Img2' },
])
export const VIDEO_MODEL_OPTIONS = reactive<Array<GenerationModelOption>>([
  { value: DEFAULT_VIDEO_MODEL, label: 'SD2.0' },
])
export const videoModelCapabilities = (modelId?: string): GenerationModelCapabilities =>
  VIDEO_MODEL_OPTIONS.find((item) => item.value === modelId)?.capabilities ?? {}
export const videoResolutionChoices = (modelId?: string): string[] => {
  const configured = videoModelCapabilities(modelId).resolutions
  return Array.isArray(configured) && configured.length
    ? configured.filter((item): item is string => typeof item === 'string')
    : [...DEFAULT_VIDEO_RESOLUTIONS]
}
export const videoDurationChoices = (modelId?: string): number[] => {
  const capabilities = videoModelCapabilities(modelId)
  const configured = capabilities.durationOptions
  return Array.isArray(configured) && configured.length
    ? configured.filter((item): item is number => Number.isInteger(item) && item > 0)
    : Number.isInteger(capabilities.durations?.min) && Number.isInteger(capabilities.durations?.max)
      ? Array.from(
          {
            length: Number(capabilities.durations?.max) - Number(capabilities.durations?.min) + 1,
          },
          (_, index) => Number(capabilities.durations?.min) + index,
        )
      : []
}
export const videoResolutionLabel = (modelId: string | undefined, resolution: string): string => {
  const labels = videoModelCapabilities(modelId).resolutionLabels
  if (labels && typeof labels === 'object' && !Array.isArray(labels)) {
    const label = (labels as Record<string, unknown>)[resolution]
    if (typeof label === 'string' && label.trim()) return label
  }
  return resolution.toUpperCase()
}
export const videoModelConcurrency = (modelId?: string): number => {
  const configured = VIDEO_MODEL_OPTIONS.find((item) => item.value === modelId)?.capabilities
    ?.executionConcurrency
  return Number.isFinite(configured) ? Math.max(1, Number(configured)) : 200
}
export const isH3VideoModel = (modelId?: string): boolean => {
  if (!modelId) return false
  const option = VIDEO_MODEL_OPTIONS.find((item) => item.value === modelId)
  return (
    Boolean(option?.capabilities?.h3Modes?.length) ||
    modelId === 'minimax-h3-runninghub' ||
    modelId === 'minimax-h3'
  )
}
export const generationModelLabel = (option: GenerationModelOption): string => {
  if (option.value === 'minimax-h3-runninghub') {
    return 'H3（RunningHub，2并发，仅测试时用）'
  }
  const concurrency = option.capabilities?.executionConcurrency
  return Number.isFinite(concurrency) && Number(concurrency) < 200
    ? `${option.label}（并发上限 ${Number(concurrency)}）`
    : option.label
}
const VIDEO_PROVIDER_SORT_ORDER: Record<string, number> = {
  yinghe: 0,
  toapis: 1,
  runninghub: 2,
}
const videoProviderSortOrder = (option: GenerationModelOption): number => {
  const provider =
    option.value === 'minimax-h3-runninghub'
      ? 'runninghub'
      : String(option.capabilities?.providerCode ?? '').toLowerCase()
  return VIDEO_PROVIDER_SORT_ORDER[provider] ?? 3
}
export const sortVideoModelOptions = (
  options: Array<GenerationModelOption>,
): Array<GenerationModelOption> =>
  [...options].sort((left, right) => {
    const providerOrder = videoProviderSortOrder(left) - videoProviderSortOrder(right)
    if (providerOrder !== 0) return providerOrder
    return (
      Number(left.capabilities?.sortOrder ?? 100) - Number(right.capabilities?.sortOrder ?? 100)
    )
  })
export function assertGenerationModelAvailable(
  modelId: string | undefined,
  modality: 'image' | 'video',
) {
  const options = modality === 'image' ? IMAGE_MODEL_OPTIONS : VIDEO_MODEL_OPTIONS
  if (!options.some((option) => option.value === modelId)) {
    throw new Error(
      `${modality === 'image' ? '图片' : '视频'}模型「${modelId || '未选择'}」已停用或不可用，请重新选择模型`,
    )
  }
}

let loaded = false
export async function loadGenerationModels(
  force = false,
  { required = false }: { required?: boolean } = {},
): Promise<void> {
  // 展示可复用目录；费用预检和提交必须读取当前启用项，不能靠旧缓存放行。
  if (loaded && !force && !required) return
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
      .sort(
        (left, right) =>
          Number(left.capabilities?.sortOrder ?? 100) -
          Number(right.capabilities?.sortOrder ?? 100),
      )
    const videos = sortVideoModelOptions(
      items
        .filter((x) => x.modality === 'video')
        .map((x) => ({ value: x.id, label: x.name, capabilities: x.capabilities })),
    )
    IMAGE_MODEL_OPTIONS.splice(0, IMAGE_MODEL_OPTIONS.length, ...images)
    VIDEO_MODEL_OPTIONS.splice(0, VIDEO_MODEL_OPTIONS.length, ...videos)
    loaded = true
  } catch {
    loaded = false
    if (required) throw new Error('模型目录加载失败，请稍后重试；本次不会提交生成任务')
    /* 非提交展示保留已有选项，配置中心暂时不可用不影响编辑。 */
  }
}
