<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
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
import H3GenerationModeFields from './H3GenerationModeFields.vue'
import VideoModelSelect from './VideoModelSelect.vue'
import ImageModelSelect from './ImageModelSelect.vue'

const props = defineProps<{
  modelValue: ShotGenOptions
  mode: 'scene' | 'shot'
}>()
const emit = defineEmits<{ 'update:modelValue': [value: ShotGenOptions] }>()

const root = ref<HTMLElement | null>(null)
const popover = ref<HTMLElement | null>(null)
const open = ref(false)
const popoverStyle = ref<Record<string, string>>({})
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
  const allowed = videoResolutionChoices(model, true) as ShotGenOptions['resolution'][]
  const durations = videoDurationChoices(model)
  emit('update:modelValue', {
    ...props.modelValue,
    videoModel: model,
    ratio: videoRatioChoices(model).includes(props.modelValue.ratio)
      ? props.modelValue.ratio
      : (videoRatioChoices(model)[0] ?? '16:9'),
    generateAudio:
      videoModelCapabilities(model).audioToggle === false ? false : props.modelValue.generateAudio,
    watermark:
      videoModelCapabilities(model).watermarkToggle === false ? false : props.modelValue.watermark,
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
  document.removeEventListener('click', onDocumentClick)
  window.removeEventListener('resize', updatePopoverPosition)
  window.removeEventListener('scroll', updatePopoverPosition, true)
}
const onDocumentClick = (event: MouseEvent) => {
  const target = event.target as Node
  // Reka 的 Portal 打开时会向 document 派发一次以 html 为目标的 click。
  if (document.querySelector('.generation-model-menu')) return
  if (root.value && !root.value.contains(target) && !popover.value?.contains(target)) close()
}
const updatePopoverPosition = () => {
  if (!root.value || !popover.value) return
  const trigger = root.value.getBoundingClientRect()
  const panel = popover.value.getBoundingClientRect()
  const gutter = 16
  const gap = 8
  const left = Math.min(
    Math.max(gutter, trigger.left),
    Math.max(gutter, window.innerWidth - panel.width - gutter),
  )
  const spaceAbove = trigger.top - gutter - gap
  const spaceBelow = window.innerHeight - trigger.bottom - gutter - gap
  const placeAbove = spaceAbove >= Math.min(panel.height, 480) || spaceAbove > spaceBelow
  const maxHeight = Math.max(220, (placeAbove ? spaceAbove : spaceBelow) - gap)
  popoverStyle.value = {
    left: `${left}px`,
    top: placeAbove ? 'auto' : `${trigger.bottom + gap}px`,
    bottom: placeAbove ? `${window.innerHeight - trigger.top + gap}px` : 'auto',
    maxHeight: `${maxHeight}px`,
  }
}
const toggle = () => {
  open.value = !open.value
  if (open.value) {
    if (props.mode === 'shot' && !PROJECT_VIDEO_MODEL_IDS.has(props.modelValue.videoModel)) {
      const firstAvailable = projectVideoModels.value[0]
      if (firstAvailable) updateVideoModel(firstAvailable.value)
    }
    document.addEventListener('click', onDocumentClick)
    window.addEventListener('resize', updatePopoverPosition)
    window.addEventListener('scroll', updatePopoverPosition, true)
    void nextTick(updatePopoverPosition)
  } else close()
}
onBeforeUnmount(close)
</script>

<template>
  <div ref="root" class="options-root">
    <button
      type="button"
      class="options-trigger"
      aria-label="调整生成参数"
      :aria-expanded="open"
      aria-controls="shot-generation-options"
      @click.stop="toggle"
    >
      <span class="ratio-icon" />
      {{ summary }}
    </button>

    <Teleport to="body">
      <div v-if="open" class="options-overlay" @click.self="close">
        <div
          id="shot-generation-options"
          ref="popover"
          class="options-popover"
          :style="popoverStyle"
          role="dialog"
          aria-modal="true"
          :aria-label="mode === 'shot' ? '视频生成参数' : '图片生成参数'"
        >
          <fieldset class="option-group">
            <legend>{{ mode === 'shot' ? '选择视频模型' : '选择图片模型' }}</legend>
            <VideoModelSelect
              v-if="mode === 'shot'"
              :model-value="modelValue.videoModel"
              compact
              @update:model-value="updateVideoModel"
            />
            <ImageModelSelect
              v-else
              :model-value="modelValue.imageModel"
              :ratio="modelValue.ratio"
              compact
              @update:model-value="updateImageModel"
            />
          </fieldset>

          <fieldset class="option-group">
            <legend>选择画幅</legend>
            <div class="segment-grid ratio-grid">
              <button
                v-for="ratio in ratioChoices"
                :key="ratio"
                type="button"
                class="segment-option"
                :class="{ active: modelValue.ratio === ratio }"
                :aria-pressed="modelValue.ratio === ratio"
                @click="updateRatio(ratio)"
              >
                <span class="ratio-shape" :class="`ratio-${ratio.replace(':', '-')}`" />
                {{ ratio }}
              </button>
            </div>
          </fieldset>

          <fieldset class="option-group">
            <legend>选择清晰度</legend>
            <div class="segment-grid">
              <button
                v-for="resolution in resolutionChoices"
                :key="resolution"
                type="button"
                class="segment-option text-only"
                :class="{
                  active:
                    (mode === 'scene'
                      ? (modelValue.imageResolution ?? '1K')
                      : modelValue.resolution) === resolution,
                }"
                :aria-pressed="
                  (mode === 'scene'
                    ? (modelValue.imageResolution ?? '1K')
                    : modelValue.resolution) === resolution
                "
                @click="updateResolution(resolution)"
              >
                {{
                  mode === 'scene'
                    ? resolution
                    : videoResolutionLabel(modelValue.videoModel, resolution)
                }}
              </button>
            </div>
          </fieldset>

          <fieldset v-if="mode === 'shot'" class="option-group">
            <legend>选择时长</legend>
            <div class="segment-grid duration-grid">
              <button
                v-for="duration in durationChoices"
                :key="duration"
                type="button"
                class="segment-option text-only"
                :class="{ active: modelValue.duration === duration }"
                :aria-pressed="modelValue.duration === duration"
                @click="updateOption('duration', duration)"
              >
                {{ duration }}s
              </button>
            </div>
          </fieldset>

          <fieldset v-if="mode === 'shot'" class="option-group switch-group">
            <legend>视频附加选项</legend>
            <button
              v-if="videoCaps.audioToggle !== false"
              type="button"
              class="switch-option"
              :class="{ active: modelValue.generateAudio }"
              :aria-pressed="!!modelValue.generateAudio"
              @click="updateOption('generateAudio', !modelValue.generateAudio)"
            >
              <span class="switch-control"><span /></span>
              <span><strong>生成背景音</strong><small>为视频生成环境音或配乐</small></span>
            </button>
            <button
              v-if="videoCaps.watermarkToggle !== false"
              type="button"
              class="switch-option"
              :class="{ active: modelValue.watermark }"
              :aria-pressed="!!modelValue.watermark"
              @click="updateOption('watermark', !modelValue.watermark)"
            >
              <span class="switch-control"><span /></span>
              <span><strong>添加水印</strong><small>使用模型供应商提供的水印</small></span>
            </button>
          </fieldset>
          <H3GenerationModeFields
            v-if="isH3"
            :model-value="modelValue"
            @update:model-value="emit('update:modelValue', $event)"
          />
          <div class="popover-actions">
            <button type="button" class="restore-button" @click="restoreDefaults">恢复默认</button>
            <button type="button" class="confirm-button" @click="close">确定</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.options-root {
  position: relative;
  min-width: 0;
}
.options-trigger {
  display: inline-flex;
  min-height: 34px;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-regular);
  padding: 6px 10px;
  font: inherit;
  font-size: var(--font-sm);
  cursor: pointer;
}
.options-trigger:hover,
.options-trigger[aria-expanded='true'] {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-light);
}
.ratio-icon,
.ratio-shape {
  display: block;
  border: 2px solid currentColor;
  border-radius: var(--radius-xs);
}
.ratio-icon {
  width: 17px;
  height: 11px;
}
.options-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal-nested);
  background: rgba(0, 0, 0, 0.48);
}
.options-popover {
  position: fixed;
  width: min(420px, calc(100vw - 80px));
  overflow-y: auto;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-dropdown);
}
.model-select-wrap {
  position: relative;
  display: block;
}
.model-select {
  width: 100%;
  min-height: 42px;
  appearance: none;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  padding: 8px 36px 8px 12px;
  font: inherit;
  cursor: pointer;
  outline: none;
}
.model-select:hover,
.model-select:focus {
  border-color: var(--primary);
  background: var(--primary-light);
  box-shadow: 0 0 0 2px var(--primary-light);
}
.select-caret {
  position: absolute;
  top: 50%;
  right: 13px;
  color: var(--primary);
  pointer-events: none;
  transform: translateY(-55%);
}
.option-group {
  min-width: 0;
  margin: 0 0 14px;
  padding: 0;
  border: 0;
}
.option-group legend {
  margin-bottom: 7px;
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.segment-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  overflow: hidden;
  padding: 3px;
  border-radius: var(--radius-sm);
  background: var(--bg);
}
.ratio-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}
.duration-grid {
  grid-template-columns: repeat(6, minmax(0, 1fr));
}
.segment-option {
  display: flex;
  min-width: 0;
  min-height: 48px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-regular);
  font: inherit;
  font-size: var(--font-sm);
  cursor: pointer;
}
.segment-option.text-only {
  min-height: 38px;
}
.segment-option:hover {
  color: var(--primary);
}
.segment-option.active {
  background: var(--surface);
  color: var(--primary);
  box-shadow: var(--shadow-card);
}
.ratio-shape {
  width: 19px;
  height: 12px;
}
.ratio-9-16 {
  width: 9px;
  height: 16px;
}
.ratio-4-3 {
  width: 16px;
  height: 12px;
}
.ratio-1-1 {
  width: 13px;
  height: 13px;
}
.switch-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
.switch-option {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  padding: 8px 10px;
  text-align: left;
  cursor: pointer;
}
.switch-option:hover,
.switch-option.active {
  border-color: var(--primary-border);
  background: var(--primary-light);
}
.switch-option strong,
.switch-option small {
  display: block;
}
.switch-option strong {
  font-size: var(--font-sm);
}
.switch-option small {
  margin-top: 2px;
  color: var(--text-secondary);
  font-size: 11px;
}
.switch-control {
  width: 32px;
  height: 18px;
  flex: 0 0 auto;
  padding: 2px;
  border-radius: var(--radius-pill);
  background: var(--border-dark);
  transition: background 0.15s;
}
.switch-control span {
  display: block;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--surface);
  box-shadow: var(--shadow-card);
  transition: transform 0.15s;
}
.switch-option.active .switch-control {
  background: var(--primary);
}
.switch-option.active .switch-control span {
  transform: translateX(14px);
}
.h3-reference-group {
  display: grid;
  gap: 10px;
}
.reference-field {
  display: grid;
  gap: 5px;
  color: var(--text-regular);
  font-size: var(--font-sm);
}
.reference-field textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  padding: 8px 10px;
  font: inherit;
}
.reference-field textarea {
  resize: vertical;
}
.reference-hint {
  margin: 0;
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.5;
}
.popover-actions {
  position: sticky;
  bottom: -16px;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin: 4px -16px -16px;
  padding: 14px 16px 16px;
  border-top: 1px solid var(--border);
  background: var(--surface);
}
.restore-button,
.confirm-button {
  min-width: 92px;
  min-height: 38px;
  border-radius: var(--radius-sm);
  padding: 7px 16px;
  font: inherit;
  font-size: var(--font-sm);
  cursor: pointer;
}
.restore-button {
  border: 1px solid var(--border-dark);
  background: var(--surface);
  color: var(--text-regular);
}
.restore-button:hover {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-light);
}
.confirm-button {
  border: 1px solid var(--primary);
  background: var(--primary);
  color: #fff;
}
.confirm-button:hover {
  filter: brightness(0.96);
}
@media (max-width: 640px) {
  .options-popover {
    width: min(360px, calc(100vw - 48px));
  }
  .duration-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
