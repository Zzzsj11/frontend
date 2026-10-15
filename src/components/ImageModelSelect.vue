<script setup lang="ts">
import { computed } from 'vue'
import { IMAGE_MODEL_OPTIONS, imageModelSupportsRatio } from '../generationModels'
import BaseModelSelect from './base/BaseModelSelect.vue'
const props = withDefaults(
  defineProps<{
    modelValue: string
    ratio?: string
    label?: string
    ariaLabel?: string
    disabled?: boolean
    id?: string
    compact?: boolean
  }>(),
  { ratio: '', label: '', ariaLabel: '图片模型', disabled: false, id: '', compact: false },
)
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const groups = computed(() =>
  [
    {
      label: '图片生成',
      items: IMAGE_MODEL_OPTIONS.filter(
        (item) =>
          ['nano-banana-2.1-all-in-one', 'seedream-5.0-pro-all-in-one'].includes(item.value) &&
          (!props.ratio || imageModelSupportsRatio(item.value, props.ratio)),
      ).map((item) => ({
        value: item.value,
        label: item.value === 'nano-banana-2.1-all-in-one' ? 'Nano Banana 2.1' : 'Seedream Pro',
      })),
    },
  ].filter((group) => group.items.length),
)
</script>
<template>
  <BaseModelSelect
    v-bind="$props"
    :groups="groups"
    icon="image"
    @update:model-value="emit('update:modelValue', $event)"
  />
</template>
