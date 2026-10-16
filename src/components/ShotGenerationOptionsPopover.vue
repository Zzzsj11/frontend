<script setup lang="ts">
import type { ShotGenOptions } from '../types'
import { videoResolutionLabel } from '../generationModels'
import { useShotGenerationOptions } from '../composables/useShotGenerationOptions'
import H3GenerationModeFields from './H3GenerationModeFields.vue'
import VideoModelSelect from './VideoModelSelect.vue'
import ImageModelSelect from './ImageModelSelect.vue'
import BaseModal from './base/BaseModal.vue'

const props = defineProps<{ modelValue: ShotGenOptions; mode: 'scene' | 'shot' }>()
const emit = defineEmits<{ 'update:modelValue': [value: ShotGenOptions] }>()
const {
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
} = useShotGenerationOptions(props, emit)
</script>

<template>
  <div class="options-root">
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

    <BaseModal
      :open="open"
      :title="mode === 'shot' ? '视频生成参数' : '图片生成参数'"
      level="nested"
      width="620px"
      @close="close"
    >
      <div id="shot-generation-options" class="options-content">
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
          <p v-if="modelChangeError" class="model-change-error" role="alert">
            {{ modelChangeError }}
          </p>
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
    </BaseModal>
  </div>
</template>

<style scoped src="./ShotGenerationOptionsPopover.css"></style>
