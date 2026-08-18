<script setup lang="ts">
import type { GeneralOutlineComparisonResult } from '../api/adminChatComparison'

defineProps<{ results: GeneralOutlineComparisonResult[] }>()
</script>

<template>
  <section class="summary">
    <article v-for="result in results" :key="result.model" class="result-card">
      <header>
        <div>
          <b>{{ result.name }}</b
          ><small>{{ result.model }}</small>
        </div>
        <span :class="result.status">{{ result.status === 'ok' ? '校验通过' : '失败' }}</span>
      </header>
      <div class="metrics">
        <span>首个完整响应 {{ ((result.callMetrics[0]?.durationMs || 0) / 1000).toFixed(2) }}s</span
        ><span>总耗时 {{ (result.totalDurationMs / 1000).toFixed(2) }}s</span
        ><span>调用 {{ result.attempts }} 次</span><span>输入 {{ result.usage.inputTokens }}</span
        ><span>输出 {{ result.usage.outputTokens }}</span>
      </div>
      <p v-if="result.error" class="error">{{ result.error }}</p>
      <div v-else class="shots">
        <details v-for="shot in result.shots" :key="shot.index">
          <summary>
            镜头 {{ shot.index + 1 }} · {{ shot.shotType === 'empty' ? '空镜' : '人物' }} ·
            {{ shot.intent }}
          </summary>
          <dl>
            <dt>场景</dt>
            <dd>{{ shot.outlineScene }}</dd>
            <dt>镜头</dt>
            <dd>{{ shot.outlineShot }}</dd>
            <dt>动作</dt>
            <dd>{{ shot.characterAction }}</dd>
            <dt>情绪</dt>
            <dd>{{ shot.emotionalFocus }}</dd>
          </dl>
        </details>
      </div>
    </article>
  </section>
</template>

<style scoped>
.summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 16px;
  align-items: start;
}
.result-card {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg);
  padding: 18px;
  box-shadow: var(--shadow-card);
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
header div {
  display: grid;
}
small {
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
header > span {
  border-radius: var(--radius-pill);
  background: var(--primary-light);
  color: var(--primary);
  padding: 5px 10px;
  font-size: var(--font-sm);
}
header span.ok {
  background: var(--success-light);
  color: var(--success);
}
header span.error {
  background: var(--danger-light);
  color: var(--danger);
}
.metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 12px 0;
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.error {
  margin: 0;
  color: var(--danger);
}
.shots {
  display: grid;
  gap: 7px;
  max-height: 720px;
  overflow: auto;
}
details {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 9px;
}
summary {
  cursor: pointer;
  font-weight: 600;
}
dl {
  display: grid;
  grid-template-columns: 42px 1fr;
  gap: 6px;
  margin: 9px 0 0;
  line-height: 1.55;
}
dd {
  margin: 0;
}
dt {
  color: var(--text-secondary);
}
@media (max-width: 760px) {
  .summary {
    grid-template-columns: 1fr;
  }
}
</style>
