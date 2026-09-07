<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { classifyErrorMessage, errorBus } from '../errorBus'
const current = computed(() => errorBus.state.queue[0])
const totalCount = computed(() =>
  errorBus.state.queue.reduce((total, item) => total + (item.repeatCount ?? 1), 0),
)
const isBatch = computed(() => totalCount.value > 1)
const showDetails = ref(false)
const copied = ref(false)
const groups = computed(() => {
  const result = new Map<string, { label: string; count: number }>()
  for (const item of errorBus.state.queue) {
    const kind = classifyErrorMessage(item.message)
    const existing = result.get(kind.category)
    if (existing) existing.count += item.repeatCount ?? 1
    else result.set(kind.category, { label: kind.label, count: item.repeatCount ?? 1 })
  }
  return [...result.values()]
})
const copyText = computed(() =>
  errorBus.state.queue
    .map((item, index) => {
      const count = item.repeatCount ?? 1
      const metadata = [
        item.errorCode && `错误编号：${item.errorCode}`,
        item.status && `HTTP：${item.status}`,
      ]
        .filter(Boolean)
        .join('；')
      return `${index + 1}. ${item.message}${count > 1 ? `（重复 ${count} 次）` : ''}${metadata ? `\n${metadata}` : ''}`
    })
    .join('\n\n'),
)

watch(totalCount, () => {
  showDetails.value = false
  copied.value = false
})

async function copyAllErrors() {
  await navigator.clipboard.writeText(copyText.value)
  copied.value = true
}
</script>
<template>
  <Teleport to="body"
    ><div v-if="current" class="error-mask" @click.self="errorBus.dismiss(current.id)">
      <section
        class="error-dialog"
        role="alertdialog"
        aria-modal="true"
        :aria-labelledby="`error-title-${current.id}`"
      >
        <div class="error-icon">!</div>
        <h2 :id="`error-title-${current.id}`">
          {{ isBatch ? '批量操作部分失败' : current.title }}
        </h2>
        <p v-if="isBatch">本次共有 {{ totalCount }} 条失败，请按类型查看并处理。</p>
        <p v-else>{{ current.message }}</p>
        <ul v-if="isBatch" class="error-summary">
          <li v-for="group in groups" :key="group.label">
            <span>{{ group.label }}</span
            ><strong>{{ group.count }} 条</strong>
          </li>
        </ul>
        <button v-if="isBatch" class="detail-toggle" @click="showDetails = !showDetails">
          {{ showDetails ? '收起失败详情' : '查看失败详情' }}
        </button>
        <div v-if="isBatch && showDetails" class="error-details">
          <article v-for="(item, index) in errorBus.state.queue" :key="item.id">
            <strong>{{ index + 1 }}. {{ classifyErrorMessage(item.message).label }}</strong>
            <p>{{ item.message }}</p>
            <small v-if="item.repeatCount && item.repeatCount > 1"
              >重复 {{ item.repeatCount }} 次</small
            >
            <small v-if="item.errorCode">错误编号：{{ item.errorCode }}</small>
            <small v-if="item.status">HTTP 状态：{{ item.status }}</small>
          </article>
        </div>
        <dl v-if="!isBatch && (current.errorCode || current.status)">
          <template v-if="current.errorCode"
            ><dt>错误编号</dt>
            <dd>{{ current.errorCode }}</dd></template
          ><template v-if="current.status"
            ><dt>HTTP 状态</dt>
            <dd>{{ current.status }}</dd></template
          >
        </dl>
        <div class="error-actions">
          <button v-if="isBatch" class="dismiss-all" @click="copyAllErrors">
            {{ copied ? '已复制' : '复制全部错误' }}
          </button>
          <button
            autofocus
            class="dismiss-one"
            @click="isBatch ? errorBus.dismissAll() : errorBus.dismiss(current.id)"
          >
            {{ isBatch ? `关闭全部（${totalCount} 条）` : '我知道了' }}
          </button>
        </div>
      </section>
    </div></Teleport
  >
</template>
<style scoped>
.error-mask {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(20, 24, 32, 0.58);
  backdrop-filter: blur(3px);
}
.error-dialog {
  width: min(620px, 100%);
  padding: 26px;
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-modal);
  text-align: center;
}
.error-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  margin: 0 auto 12px;
  border-radius: 50%;
  background: var(--danger-light);
  color: var(--danger);
  font-size: 26px;
  font-weight: 700;
}
h2 {
  margin: 0 0 10px;
  font-size: 19px;
}
p {
  margin: 0 0 16px;
  color: var(--text-regular);
  line-height: 1.6;
  overflow-wrap: anywhere;
}
dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 12px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: #f7f7f8;
  text-align: left;
  font-size: var(--font-sm);
}
dt {
  color: var(--text-secondary);
}
dd {
  margin: 0;
  font-family: monospace;
  overflow-wrap: anywhere;
}
.error-summary {
  display: grid;
  gap: 8px;
  margin: 0 0 14px;
  padding: 0;
  list-style: none;
  text-align: left;
}
.error-summary li {
  display: flex;
  justify-content: space-between;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--danger-light);
}
.detail-toggle {
  border: 0;
  background: transparent;
  color: var(--primary);
  cursor: pointer;
}
.error-details {
  max-height: 300px;
  margin-top: 12px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  text-align: left;
}
.error-details article {
  padding: 12px;
  border-bottom: 1px solid var(--border);
}
.error-details article:last-child {
  border-bottom: 0;
}
.error-details p {
  margin: 6px 0;
}
.error-details small {
  display: block;
  color: var(--text-secondary);
}
.error-actions {
  display: flex;
  gap: 8px;
  margin-top: 14px;
}
.error-actions button {
  flex: 1;
  padding: 10px;
  border: 0;
  border-radius: var(--radius-pill);
  cursor: pointer;
  font-size: var(--font-md);
}
.dismiss-one {
  background: var(--primary);
  color: var(--surface);
}
.dismiss-all {
  background: var(--surface-muted);
  color: var(--text-secondary);
  border: 1px solid var(--border) !important;
}
</style>
