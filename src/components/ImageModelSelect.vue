<script setup lang="ts">
import { computed } from 'vue'
import { IMAGE_MODEL_OPTIONS, imageModelSupportsRatio } from '../generationModels'
import GenerationModelSelect from './GenerationModelSelect.vue'
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
          item.value.endsWith('-all-in-one') &&
          (!props.ratio || imageModelSupportsRatio(item.value, props.ratio)),
      ),
    },
  ].filter((group) => group.items.length),
)
</script>
<template>
  <GenerationModelSelect
    v-bind="$props"
    :groups="groups"
    modality="image"
    @update:model-value="emit('update:modelValue', $event)"
  />
</template>
