<script setup lang="ts">
import type { ChatComparisonResult } from '../api/adminChatComparison'

defineProps<{ results: ChatComparisonResult[] }>()

const copyResult = async (result: ChatComparisonResult) => {
  await navigator.clipboard.writeText(result.text)
}
</script>

<template>
  <section class="results-section">
    <h3>对比结果</h3>
    <div class="result-grid">
      <article v-for="result in results" :key="result.model" class="result-card">
        <header>
          <div>
            <b>{{ result.name }}</b
            ><small>{{ result.model }}</small>
          </div>
          <span class="result-status" :class="result.status">{{
            result.status === 'ok' ? '成功' : '失败'
          }}</span>
        </header>
        <div class="metrics">
          <span>{{ (result.durationMs / 1000).toFixed(2) }}s</span>
          <span>输入 {{ result.usage.inputTokens }}</span>
          <span>输出 {{ result.usage.outputTokens }}</span>
        </div>
        <pre v-if="result.status === 'ok'">{{ result.text }}</pre>
        <p v-else class="result-error">{{ result.error }}</p>
        <footer>
          <span>{{ result.protocol }}</span>
          <button v-if="result.text" type="button" @click="copyResult(result)">复制结果</button>
        </footer>
      </article>
    </div>
  </section>
</template>

<style scoped>
.results-section {
  display: grid;
  gap: 10px;
}
h3,
p {
  margin: 0;
}
.result-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 12px;
  align-items: start;
}
.result-card {
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg);
  box-shadow: var(--shadow-card);
}
.result-card header,
.result-card footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
}
.result-card header div {
  display: grid;
  gap: 2px;
}
small,
.result-card footer {
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.result-status {
  border-radius: var(--radius-pill);
  padding: 5px 10px;
  font-size: var(--font-sm);
}
.result-status.ok {
  background: var(--success-light);
  color: var(--success);
}
.result-status.error {
  background: var(--danger-light);
  color: var(--danger);
}
.metrics {
  display: flex;
  gap: 14px;
  border-block: 1px solid var(--border);
  padding: 8px 14px;
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
pre {
  min-height: 180px;
  max-height: 460px;
  overflow: auto;
  margin: 0;
  padding: 14px;
  white-space: pre-wrap;
  word-break: break-word;
  font: inherit;
  line-height: 1.65;
}
.result-error {
  padding: 14px;
  color: var(--danger);
}
.result-card footer button {
  border: 0;
  background: transparent;
  color: var(--primary);
  cursor: pointer;
}
@media (max-width: 720px) {
  .result-grid {
    grid-template-columns: 1fr;
  }
}
</style>
