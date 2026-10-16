import { computed, ref } from 'vue'
import {
  DEFAULT_IMAGE_MODEL,
  DEFAULT_VIDEO_MODEL,
  IMAGE_MODEL_OPTIONS,
  PROJECT_VIDEO_MODEL_IDS,
  VIDEO_MODEL_OPTIONS,
  generationModelLabel,
  imageModelSupportsRatio,
  imageResolutionChoices,
  isH3VideoModel,
  videoDurationChoices,
  videoRatioChoices,
  videoModelCapabilities,
  videoResolutionChoices,
  videoResolutionLabel,
} from '../generationModels'
import {
  DEFAULT_H3_MODE,
  DEFAULT_VIDEO_DURATION,
  VIDEO_DURATION_CHOICES,
} from '../mediaConstraints'
import type { ShotGenOptions } from '../types'

export function useShotGenerationOptions(
  props: Readonly<{ modelValue: ShotGenOptions; mode: 'scene' | 'shot' }>,
  emit: (event: 'update:modelValue', value: ShotGenOptions) => void,
) {
  const open = ref(false)
  const modelChangeError = ref('')
  const resolutionChoices = computed<string[]>(() => {
    return props.mode === 'scene'
      ? imageResolutionChoices(props.modelValue.imageModel)
      : videoResolutionChoices(
          props.modelValue.videoModel,
          ['auto', 'reference'].includes(props.modelValue.h3Mode ?? 'auto'),
        )
  })
  const ratioChoices = computed(() =>
    props.mode === 'shot'
      ? videoRatioChoices(props.modelValue.videoModel)
      : (['16:9', '9:16', '4:3', '1:1'] as ShotGenOptions['ratio'][]),
  )
  const videoCaps = computed(() => videoModelCapabilities(props.modelValue.videoModel))
  const durationChoices = computed(() => {
    const configured = videoDurationChoices(props.modelValue.videoModel)
    return configured.length ? configured : VIDEO_DURATION_CHOICES
  })
  const isH3 = computed(() => props.mode === 'shot' && isH3VideoModel(props.modelValue.videoModel))
  const projectVideoModels = computed(() =>
    VIDEO_MODEL_OPTIONS.filter((model) => PROJECT_VIDEO_MODEL_IDS.has(model.value)),
  )

  const summary = computed(() => {
    const parts = [
      props.modelValue.ratio,
      props.mode === 'scene'
        ? (props.modelValue.imageResolution ?? '1K')
        : videoResolutionLabel(props.modelValue.videoModel, props.modelValue.resolution),
    ]
    if (props.mode === 'shot') parts.push(`${props.modelValue.duration}s`)
    const models = props.mode === 'shot' ? VIDEO_MODEL_OPTIONS : IMAGE_MODEL_OPTIONS
    const modelValue =
      props.mode === 'shot' ? props.modelValue.videoModel : props.modelValue.imageModel
    const model = models.find((item) => item.value === modelValue)
    parts.push(model ? generationModelLabel(model) : modelValue)
    return parts.join(' · ')
  })
  const updateOption = <K extends keyof ShotGenOptions>(key: K, value: ShotGenOptions[K]) => {
    emit('update:modelValue', { ...props.modelValue, [key]: value })
  }
  const updateResolution = (value: string) => {
    if (props.mode === 'scene')
      updateOption('imageResolution', value as NonNullable<ShotGenOptions['imageResolution']>)
    else updateOption('resolution', value as ShotGenOptions['resolution'])
  }
  const updateImageModel = (model: string) => {
    const allowed = imageResolutionChoices(model)
    emit('update:modelValue', {
      ...props.modelValue,
      imageModel: model,
      imageResolution: (allowed.includes(props.modelValue.imageResolution ?? '1K')
        ? props.modelValue.imageResolution
        : (allowed[0] ?? '1K')) as ShotGenOptions['imageResolution'],
    })
  }
  const updateRatio = (ratio: ShotGenOptions['ratio']) => {
    const imageModel = props.modelValue.imageModel
    emit('update:modelValue', {
      ...props.modelValue,
      ratio,
      ...(props.mode === 'scene' && !imageModelSupportsRatio(imageModel, ratio)
        ? { imageModel: DEFAULT_IMAGE_MODEL, imageResolution: '1K' as const }
        : {}),
    })
  }
  const updateVideoModel = (model: string) => {
    modelChangeError.value = ''
    const caps = videoModelCapabilities(model)
    const currentMode = props.modelValue.h3Mode ?? DEFAULT_H3_MODE
    const modes = caps.referenceModes as string[] | undefined
    const unsupportedMode = modes?.length && !modes.includes(currentMode)
    const hasDedicatedFrames = Boolean(
      props.modelValue.h3FirstFrameUrl || props.modelValue.h3LastFrameUrl,
    )
    const refs = [
      ['referenceImageUrls', 'referenceImage'],
      ['referenceVideoUrls', 'referenceVideo'],
      ['referenceAudioUrls', 'referenceAudio'],
    ] as const
    const hasReferences = refs.some(([field]) => props.modelValue[field]?.length)
    const incompatibleReferences = refs.some(([field, capability]) => {
      const max = (caps[capability] as { max?: number } | undefined)?.max
      return typeof max === 'number' && (props.modelValue[field]?.length ?? 0) > max
    })
    if ((unsupportedMode && (hasDedicatedFrames || hasReferences)) || incompatibleReferences) {
      modelChangeError.value =
        '当前模式或参考素材与目标模型不兼容，请先处理参考素材或调整生成模式后再切换。原配置已保留。'
      return
    }
    const nextMode = unsupportedMode ? (modes?.includes('auto') ? 'auto' : modes?.[0]) : currentMode
    const allowed = videoResolutionChoices(
      model,
      ['auto', 'reference'].includes(nextMode ?? 'auto'),
    ) as ShotGenOptions['resolution'][]
    const durations = videoDurationChoices(model)
    emit('update:modelValue', {
      ...props.modelValue,
      videoModel: model,
      h3Mode: nextMode as ShotGenOptions['h3Mode'],
      ratio: videoRatioChoices(model).includes(props.modelValue.ratio)
        ? props.modelValue.ratio
        : (videoRatioChoices(model)[0] ?? '16:9'),
      generateAudio:
        videoModelCapabilities(model).audioToggle === false
          ? false
          : props.modelValue.generateAudio,
      watermark:
        videoModelCapabilities(model).watermarkToggle === false
          ? false
          : props.modelValue.watermark,
      resolution: allowed.includes(props.modelValue.resolution)
        ? props.modelValue.resolution
        : (allowed[0] ?? '720p'),
      duration:
        durations.length && !durations.includes(props.modelValue.duration)
          ? (durations[0] ?? DEFAULT_VIDEO_DURATION)
          : props.modelValue.duration,
    })
  }
  const restoreDefaults = () => {
    modelChangeError.value = ''
    emit('update:modelValue', {
      ...props.modelValue,
      ratio: '16:9',
      ...(props.mode === 'scene'
        ? { imageResolution: '1K' as const }
        : { resolution: '480p' as const }),
      ...(props.mode === 'shot'
        ? {
            duration: DEFAULT_VIDEO_DURATION,
            videoModel: DEFAULT_VIDEO_MODEL,
            generateAudio: false,
            watermark: false,
          }
        : { imageModel: DEFAULT_IMAGE_MODEL }),
      h3Mode: DEFAULT_H3_MODE,
      h3FirstFrameUrl: undefined,
      h3LastFrameUrl: undefined,
      referenceImageUrls: [],
      referenceVideoUrls: [],
      referenceAudioUrls: [],
      h3AudioUsage: 'reference',
    })
  }
  const close = () => {
    open.value = false
  }
  const toggle = () => {
    if (
      !open.value &&
      props.mode === 'shot' &&
      !PROJECT_VIDEO_MODEL_IDS.has(props.modelValue.videoModel)
    ) {
      const firstAvailable = projectVideoModels.value[0]
      if (firstAvailable) updateVideoModel(firstAvailable.value)
    }
    open.value = !open.value
  }

  return {
    open,
    modelChangeError,
    resolutionChoices,
    ratioChoices,
    durationChoices,
    videoCaps,
    isH3,
    summary,
    updateOption,
    updateResolution,
    updateImageModel,
    updateRatio,
    updateVideoModel,
    restoreDefaults,
    close,
    toggle,
  }
}
