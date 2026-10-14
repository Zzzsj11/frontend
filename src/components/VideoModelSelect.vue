<script setup lang="ts">
import { computed, useId } from 'vue'
import {
  SelectContent,
  SelectGroup,
  SelectIcon,
  SelectItem,
  SelectItemIndicator,
  SelectItemText,
  SelectLabel,
  SelectPortal,
  SelectRoot,
  SelectTrigger,
  SelectValue,
  SelectViewport,
} from 'reka-ui'
import {
  generationModelLabel,
  PROJECT_VIDEO_MODEL_GROUPS,
  VIDEO_MODEL_OPTIONS,
} from '../generationModels'
import AppIcon from './AppIcon.vue'

const props = withDefaults(
  defineProps<{
    modelValue: string
    label?: string
    ariaLabel?: string
    disabled?: boolean
    id?: string
    compact?: boolean
  }>(),
  { label: '', ariaLabel: '视频模型', disabled: false, id: '', compact: false },
)
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const generatedId = useId()
const selectId = computed(() => props.id || generatedId)
const groups = computed(() =>
  PROJECT_VIDEO_MODEL_GROUPS.map((group) => ({
    label: group.label,
    items: group.ids
      .map((id) => VIDEO_MODEL_OPTIONS.find((option) => option.value === id))
      .filter((option) => option !== undefined),
  })).filter((group) => group.items.length),
)
const selectedLabel = computed(() => {
  const option = VIDEO_MODEL_OPTIONS.find((item) => item.value === props.modelValue)
  return option ? generationModelLabel(option) : '请选择视频模型'
})
const updateModel = (value: unknown) => {
  if (typeof value === 'string') emit('update:modelValue', value)
}
</script>

<template>
  <div class="video-model-field" :class="{ compact }" @click.stop>
    <label v-if="label" class="video-model-label" :for="selectId">{{ label }}</label>
    <SelectRoot
      :model-value="modelValue"
      :disabled="disabled || !groups.length"
      @update:model-value="updateModel"
    >
      <SelectTrigger :id="selectId" class="video-model-trigger" :aria-label="ariaLabel">
        <AppIcon name="movie" :size="compact ? 14 : 16" />
        <SelectValue class="video-model-value">{{ selectedLabel }}</SelectValue>
        <SelectIcon class="video-model-chevron">⌄</SelectIcon>
      </SelectTrigger>
      <SelectPortal>
        <SelectContent
          class="video-model-menu"
          position="popper"
          :side-offset="6"
          align="start"
          @click.stop
        >
          <SelectViewport class="video-model-viewport">
            <SelectGroup v-for="group in groups" :key="group.label" class="video-model-group">
              <SelectLabel class="video-model-group-label">{{ group.label }}</SelectLabel>
              <SelectItem
                v-for="item in group.items"
                :key="item.value"
                class="video-model-item"
                :value="item.value"
              >
                <SelectItemIndicator class="video-model-check">✓</SelectItemIndicator>
                <SelectItemText>{{ generationModelLabel(item) }}</SelectItemText>
              </SelectItem>
            </SelectGroup>
          </SelectViewport>
        </SelectContent>
      </SelectPortal>
    </SelectRoot>
  </div>
</template>

<style scoped>
.video-model-field {
  min-width: 0;
  width: 100%;
}
.video-model-label {
  display: block;
  margin-bottom: 7px;
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.video-model-trigger {
  display: flex;
  width: 100%;
  min-height: 44px;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.16s,
    box-shadow 0.16s,
    background 0.16s;
}
.video-model-trigger:hover,
.video-model-trigger[data-state='open'] {
  border-color: var(--primary);
  background: var(--primary-light);
}
.video-model-trigger:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px var(--primary-light);
  border-color: var(--primary);
}
.video-model-trigger[data-disabled] {
  opacity: 0.55;
  cursor: not-allowed;
}
.video-model-trigger .app-icon {
  flex: none;
  color: var(--primary);
}
.video-model-value {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.video-model-chevron {
  flex: none;
  color: var(--text-secondary);
  font-size: 20px;
  line-height: 1;
}
.compact .video-model-trigger {
  min-height: 42px;
  padding: 7px 10px;
  font-size: var(--font-sm);
}
</style>
