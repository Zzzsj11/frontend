<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
const props = defineProps<{ code: string }>()
const copied = ref(false)
const copying = ref(false)
const error = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
function reset() {
  clearTimeout(timer)
  copied.value = false
  error.value = ''
}
async function copy() {
  reset()
  copying.value = true
  const text = props.code
  try {
    await navigator.clipboard.writeText(text)
    if (props.code !== text) return
    copied.value = true
    timer = setTimeout(reset, 2000)
  } catch {
    if (props.code === text) error.value = '复制失败，请选中代码手动复制。'
  } finally {
    copying.value = false
  }
}
watch(() => props.code, reset)
onBeforeUnmount(() => clearTimeout(timer))
</script>
<template>
  <div class="code-example">
    <div class="code-toolbar">
      <span>cURL · Shell</span>
      <button class="copy-button" :class="{ copied }" :disabled="copying" @click="copy">
        <svg
          v-if="copied"
          class="copy-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <path d="m5 12 4 4L19 6" />
        </svg>
        <svg
          v-else
          class="copy-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          aria-hidden="true"
        >
          <rect x="8" y="8" width="12" height="13" rx="2" />
          <path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h3" />
        </svg>
        <span aria-live="polite">{{ copied ? '复制成功' : copying ? '复制中…' : '复制代码' }}</span>
      </button>
    </div>
    <pre tabindex="0" aria-label="请求示例代码"><code>{{ code }}</code></pre>
  </div>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
</template>
<style scoped>
.code-example {
  overflow: hidden;
  background: var(--code-bg);
  color: var(--code-text);
  border: 1px solid var(--code-border);
  border-radius: var(--radius-lg);
}
.code-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 12px 18px;
  background: var(--code-header);
  border-bottom: 1px solid var(--code-border);
  font-size: 13px;
}
.copy-button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  min-width: 114px;
  justify-content: center;
  color: var(--code-text);
  background: var(--code-header);
  border-color: var(--code-border);
  transition:
    transform 120ms ease,
    color 180ms ease,
    border-color 180ms ease;
}
.copy-button:hover {
  border-color: var(--code-text);
}
.copy-button:active {
  transform: scale(0.95);
}
.copy-button.copied {
  color: var(--code-success);
  border-color: var(--code-success);
}
.copy-icon {
  width: 16px;
  height: 16px;
}
.copied .copy-icon {
  animation: copy-pop 220ms ease-out;
}
pre {
  margin: 0;
  padding: 22px;
  white-space: pre;
  overflow-wrap: normal;
  overflow: auto;
  max-height: 560px;
  line-height: 1.7;
  tab-size: 2;
}
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
}
@keyframes copy-pop {
  from {
    transform: scale(0.6);
    opacity: 0.4;
  }
  to {
    transform: scale(1);
    opacity: 1;
  }
}
@media (prefers-reduced-motion: reduce) {
  .copy-button {
    transition: none;
  }
  .copy-button:active {
    transform: none;
  }
  .copied .copy-icon {
    animation: none;
  }
}
</style>
