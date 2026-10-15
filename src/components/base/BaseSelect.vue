<script setup lang="ts">
import { useAttrs, useSlots, type VNode } from 'vue'
import BaseModelSelect from './BaseModelSelect.vue'

const props = defineProps<{
  modelValue?: string | number | null
  value?: string | number | null
  modelModifiers?: { number?: boolean }
  disabled?: boolean
  required?: boolean
  name?: string
  id?: string
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string | number]
  change: [event: Event]
}>()
defineOptions({ inheritAttrs: false })
const attrs = useAttrs()
const slots = useSlots()
interface Choice {
  value: string | number
  label: string
  disabled: boolean
}
const text = (value: unknown): string => {
  if (Array.isArray(value)) return value.map(text).join('')
  if (value && typeof value === 'object' && 'children' in value)
    return text((value as VNode).children)
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}
// 兼容现有 option 插槽与动态选项，所有展示与键盘行为由同一 Reka 组件承担。
let renderedChoices: Choice[] = []
const choices = (): Choice[] => {
  const flatten = (nodes: VNode[]): Choice[] =>
    nodes.flatMap((node) => {
      if (node.type === 'option')
        return [
          {
            value: node.props?.value ?? text(node.children).trim(),
            label: text(node.children).trim(),
            disabled: node.props?.disabled === '' || Boolean(node.props?.disabled),
          },
        ]
      return Array.isArray(node.children) ? flatten(node.children as VNode[]) : []
    })
  renderedChoices = flatten(slots.default?.() ?? [])
  return renderedChoices
}
const groups = () =>
  [
    {
      label: '',
      items: choices().map((item, index) => ({
        value: `choice-${index}`,
        label: item.label,
        disabled: item.disabled,
      })),
    },
  ].filter((group) => group.items.length > 0)
const selected = () => {
  if (
    props.required &&
    ((props.modelValue ?? props.value) == null || (props.modelValue ?? props.value) === '')
  )
    return ''

  const index = choices().findIndex(
    (item) => String(item.value) === String(props.modelValue ?? props.value ?? ''),
  )
  return index >= 0 ? `choice-${index}` : ''
}
const update = (key: string) => {
  const choice = renderedChoices[Number(key.replace('choice-', ''))]
  if (!choice || choice.disabled) return
  const value = props.modelModifiers?.number ? Number(choice.value) : choice.value
  emit('update:modelValue', value)
  // 保留既有 change 处理函数的标准 select 事件契约。
  const target = document.createElement('select')
  target.add(new Option(choice.label, String(choice.value)))
  const event = new Event('change', { bubbles: true })
  Object.defineProperty(event, 'target', { value: target })
  emit('change', event)
}
</script>
<template>
  <BaseModelSelect
    class="app-select"
    :model-value="selected()"
    :groups="groups()"
    :icon="null"
    :disabled="disabled"
    :id="id"
    :required="required"
    :name="undefined"
    :aria-label="String(attrs['aria-label'] || '')"
    :trigger-attrs="{ ...attrs, 'data-value': String(modelValue ?? value ?? '') }"
    @update:model-value="update"
  >
    <template #after>
      <input v-if="name" type="hidden" :name="name" :value="modelValue ?? value ?? ''" />
    </template>
  </BaseModelSelect>
</template>
