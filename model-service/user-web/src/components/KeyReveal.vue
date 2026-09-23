<script setup lang="ts">
import CodeExample from './CodeExample.vue'
defineProps<{ apiKey: string }>()
const emit = defineEmits<{ dismiss: [] }>()
</script>
<template>
  <section class="key-reveal" aria-label="新 Key 已创建">
    <div class="key-heading">
      <span class="key-symbol" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
          <circle cx="8" cy="9" r="4" />
          <path d="m11 12 8 8m-3-3 3-3m-6 0 3-3" />
        </svg>
      </span>
      <div>
        <h3>API Key 已创建</h3>
      </div>
      <span class="one-time">仅展示一次</span>
    </div>
    <CodeExample
      :code="apiKey"
      title="API KEY"
      copy-label="复制 Key"
      code-label="新创建的 API Key"
    />
    <div class="key-footer">
      <p>复制并妥善保存，关闭后无法再次查看完整 Key。请勿放入前端代码。</p>
      <button class="secondary" @click="emit('dismiss')">
        已保存，隐藏 Key <span aria-hidden="true">↗</span>
      </button>
    </div>
  </section>
</template>
<style scoped>
.key-reveal {
  margin-top: 24px;
  padding: 24px;
  border: 1px solid var(--border);
  border-top: 3px solid var(--primary);
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, var(--primary-light), var(--panel) 65%);
}
.key-heading {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 20px;
}
.key-symbol {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  flex: 0 0 auto;
  border-radius: var(--radius-sm);
  background: var(--primary);
  color: var(--panel);
}
.key-symbol svg {
  width: 26px;
  height: 26px;
}
h3 {
  margin: 0 0 6px;
  font-size: 18px;
}
p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.7;
}
.one-time {
  margin-left: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 5px 10px;
  font-size: 12px;
  color: var(--primary);
  white-space: nowrap;
  background: var(--panel);
}
.key-footer {
  display: flex;
  gap: 20px;
  align-items: center;
  justify-content: space-between;
  margin-top: 18px;
}
.key-footer button {
  flex-shrink: 0;
  font-size: 13px;
}
.key-footer span {
  margin-left: 8px;
}
@media (max-width: 600px) {
  .key-reveal {
    padding: 18px;
  }
  .key-heading {
    flex-wrap: wrap;
  }
  .one-time {
    margin-left: 58px;
  }
  .key-footer {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
