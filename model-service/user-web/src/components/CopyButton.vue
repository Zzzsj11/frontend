<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
const props = defineProps<{ text: string; label: string }>()
const copied = ref(false)
const error = ref('')
let timer: ReturnType<typeof setTimeout>
async function copy() {
  error.value = ''
  const text = props.text
  try {
    await navigator.clipboard.writeText(text)
    if (text !== props.text) return
    copied.value = true
    clearTimeout(timer)
    timer = setTimeout(() => (copied.value = false), 2000)
  } catch {
    error.value = '复制失败，请重试或手动选择文本。'
  }
}
watch(
  () => props.text,
  () => {
    copied.value = false
    error.value = ''
    clearTimeout(timer)
  },
)
onBeforeUnmount(() => clearTimeout(timer))
</script>
<template>
  <div>
    <button class="secondary" @click="copy">{{ copied ? '已复制' : label }}</button
    ><span v-if="error" role="alert" class="error">{{ error }}</span>
  </div>
</template>
<style scoped>
span {
  display: block;
  font-size: 12px;
  margin-top: 8px;
}
</style>
