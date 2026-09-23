<script setup lang="ts">
import { computed, ref } from 'vue'
import { money, points } from '../utils/financial'
const props = withDefaults(
  defineProps<{ modelValue: string | number | null; kind?: 'points' | 'money' }>(),
  { kind: 'points' },
)
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const focused = ref(false)
const draft = ref('')
const display = computed(() =>
  focused.value
    ? draft.value
    : props.kind === 'money'
      ? money(props.modelValue)
      : points(props.modelValue),
)
function focus(event: FocusEvent) {
  draft.value = (event.target as HTMLInputElement).value
  focused.value = true
}
function input(event: Event) {
  draft.value = (event.target as HTMLInputElement).value
  emit('update:modelValue', draft.value)
}
</script>
<template>
  <input
    :value="display === '—' ? '' : display"
    type="number"
    step="any"
    @focus="focus"
    @blur="focused = false"
    @input="input"
  />
</template>
