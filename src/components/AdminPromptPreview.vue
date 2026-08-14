<script setup lang="ts">
import { ref, watch } from 'vue'
import { previewPrompt, type PromptPreviewResult } from '../api/adminPrompts'

const props = defineProps<{
  promptKey: string
  /** 编辑区当前内容（父组件实时同步，点击试渲染时才发送） */
  content: string
  /** 已声明变量：name → 说明 */
  variables: Record<string, string>
}>()

const previewVars = ref<Record<string, string>>({}),
  result = ref<PromptPreviewResult | null>(null),
  previewing = ref(false),
  error = ref('')

/** 模板占位符展示文本（{{name}} 字面量不能写在模板插值里，会被 Vue 解析器吃掉） */
const varPlaceholder = (name: string | number) => `{{${String(name)}}}`

const runPreview = async () => {
  previewing.value = true
  error.value = ''
  try {
    result.value = await previewPrompt(props.promptKey, props.content, previewVars.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '试渲染失败'
  } finally {
    previewing.value = false
  }
}

// 切换模板时清空上一次的输入与结果
watch(
  () => props.promptKey,
  () => {
    previewVars.value = {}
    result.value = null
    error.value = ''
  },
)
</script>
<template>
  <section class="preview">
    <div class="bar">
      <label v-for="(desc, name) in variables" :key="name">
        <code>{{ varPlaceholder(name) }}</code>
        <input v-model="previewVars[name]" :placeholder="desc" :disabled="previewing" />
      </label>
      <button :disabled="previewing" @click="runPreview">
        {{ previewing ? '渲染中…' : '试渲染' }}
      </button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <template v-if="result">
      <p v-if="result.missingFragments.length" class="warn">
        缺少必含安全片段：{{ result.missingFragments.join('、') }}（发布将被拒绝）
      </p>
      <p v-if="result.undeclaredVariables.length" class="warn">
        未声明变量：{{ result.undeclaredVariables.join('、') }}（发布将被拒绝）
      </p>
      <p v-if="result.jsonError" class="warn">JSON 校验失败：{{ result.jsonError }}</p>
      <pre class="rendered">{{ result.rendered }}</pre>
    </template>
  </section>
</template>
<style scoped>
.preview {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.bar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.bar label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-sm);
}
.bar input {
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  min-width: 160px;
}
button {
  border: 1px solid var(--border-dark);
  background: var(--surface);
  border-radius: var(--radius-sm);
  padding: 7px 12px;
  cursor: pointer;
}
button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.warn {
  color: var(--warning);
  background: var(--warning-light);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  font-size: var(--font-sm);
  margin: 0;
}
.rendered {
  background: var(--surface-muted);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: var(--font-sm);
  max-height: 260px;
  overflow: auto;
  margin: 0;
}
.error {
  color: var(--danger);
  margin: 0;
}
</style>
