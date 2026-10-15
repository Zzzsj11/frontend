<script setup lang="ts">
import { computed } from 'vue'
import {
  generationModelLabel,
  PROJECT_VIDEO_MODEL_GROUPS,
  VIDEO_MODEL_OPTIONS,
} from '../generationModels'
import BaseModelSelect from './base/BaseModelSelect.vue'
withDefaults(
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
const groups = computed(() =>
  PROJECT_VIDEO_MODEL_GROUPS.map((group) => ({
    label: group.label,
    items: group.ids.flatMap((id) => {
      const item = VIDEO_MODEL_OPTIONS.find((option) => option.value === id)
      return item ? [{ value: item.value, label: generationModelLabel(item) }] : []
    }),
  })).filter((group) => group.items.length),
)
</script>
<template>
  <BaseModelSelect
    v-bind="$props"
    :groups="groups"
    icon="movie"
    @update:model-value="emit('update:modelValue', $event)"
  />
</template>
