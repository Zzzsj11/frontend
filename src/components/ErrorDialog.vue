<script setup lang="ts">
import { computed } from 'vue'
import { errorBus } from '../errorBus'
const current = computed(() => errorBus.state.queue[0])
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
        <h2 :id="`error-title-${current.id}`">{{ current.title }}</h2>
        <p>{{ current.message }}</p>
        <dl v-if="current.errorCode || current.status">
          <template v-if="current.errorCode"
            ><dt>错误编号</dt>
            <dd>{{ current.errorCode }}</dd></template
          ><template v-if="current.status"
            ><dt>HTTP 状态</dt>
            <dd>{{ current.status }}</dd></template
          >
        </dl>
        <p v-if="errorBus.state.queue.length > 1" class="pending">
          还有 {{ errorBus.state.queue.length - 1 }} 条错误待查看
        </p>
        <div class="error-actions">
          <button
            v-if="errorBus.state.queue.length > 1"
            class="dismiss-all"
            @click="errorBus.dismissAll()"
          >
            关闭全部（{{ errorBus.state.queue.length }} 条）
          </button>
          <button autofocus class="dismiss-one" @click="errorBus.dismiss(current.id)">
            我知道了
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
  width: min(440px, 100%);
  padding: 26px;
  border-radius: var(--radius-lg);
  background: #fff;
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
.pending {
  font-size: var(--font-sm);
  color: #a65;
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
  color: #fff;
}
.dismiss-all {
  background: var(--surface-muted);
  color: var(--text-secondary);
  border: 1px solid var(--border) !important;
}
</style>
