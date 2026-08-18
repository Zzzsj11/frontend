<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { IMAGE_MODEL_OPTIONS, VIDEO_MODEL_OPTIONS } from '../generationModels'
import { VIDEO_DURATION_CHOICES } from '../mediaConstraints'
import type { ShotGenOptions } from '../types'

const props = defineProps<{
  modelValue: ShotGenOptions
  mode: 'scene' | 'shot'
}>()
const emit = defineEmits<{ 'update:modelValue': [value: ShotGenOptions] }>()

const root = ref<HTMLElement | null>(null)
const popover = ref<HTMLElement | null>(null)
const open = ref(false)
const popoverStyle = ref<Record<string, string>>({})
const resolutionChoices: ShotGenOptions['resolution'][] = ['480p', '720p', '1080p']
const ratioChoices: ShotGenOptions['ratio'][] = ['16:9', '9:16', '4:3', '1:1']
const durationChoices = VIDEO_DURATION_CHOICES

const summary = computed(() => {
  const parts = [props.modelValue.ratio, props.modelValue.resolution.toUpperCase()]
  if (props.mode === 'shot') parts.push(`${props.modelValue.duration}s`)
  const models = props.mode === 'shot' ? VIDEO_MODEL_OPTIONS : IMAGE_MODEL_OPTIONS
  const modelValue =
    props.mode === 'shot' ? props.modelValue.videoModel : props.modelValue.imageModel
  parts.push(models.find((item) => item.value === modelValue)?.label || modelValue)
  return parts.join(' · ')
})
const updateOption = <K extends keyof ShotGenOptions>(key: K, value: ShotGenOptions[K]) => {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
const close = () => {
  open.value = false
  document.removeEventListener('click', onDocumentClick)
  window.removeEventListener('resize', updatePopoverPosition)
  window.removeEventListener('scroll', updatePopoverPosition, true)
}
const onDocumentClick = (event: MouseEvent) => {
  const target = event.target as Node
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
      <div
        v-if="open"
        id="shot-generation-options"
        ref="popover"
        class="options-popover"
        :style="popoverStyle"
      >
        <fieldset class="option-group">
          <legend>{{ mode === 'shot' ? '选择视频模型' : '选择图片模型' }}</legend>
          <label class="model-select-wrap">
            <select
              v-if="mode === 'shot'"
              class="model-select"
              :value="modelValue.videoModel"
              aria-label="视频模型"
              @change="updateOption('videoModel', ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="item in VIDEO_MODEL_OPTIONS" :key="item.value" :value="item.value">
                {{ item.label }}
              </option>
            </select>
            <select
              v-else
              class="model-select"
              :value="modelValue.imageModel"
              aria-label="图片模型"
              @change="updateOption('imageModel', ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="item in IMAGE_MODEL_OPTIONS" :key="item.value" :value="item.value">
                {{ item.label }}
              </option>
            </select>
            <span class="select-caret">⌄</span>
          </label>
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
              @click="updateOption('ratio', ratio)"
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
              :class="{ active: modelValue.resolution === resolution }"
              :aria-pressed="modelValue.resolution === resolution"
              @click="updateOption('resolution', resolution)"
            >
              {{ resolution.toUpperCase() }}
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
.options-popover {
  position: fixed;
  z-index: var(--z-modal-nested);
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
@media (max-width: 640px) {
  .options-popover {
    width: min(360px, calc(100vw - 48px));
  }
  .duration-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
