<script setup lang="ts">
import { computed, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    page: number
    total: number
    pageSize: number
    position?: '顶部' | '底部'
  }>(),
  { position: '底部' },
)
const emit = defineEmits<{ change: [page: number] }>()
const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
const pageDraft = ref(props.page)

watch(
  () => props.page,
  (value) => (pageDraft.value = value),
)

const go = (page: number) => {
  const nextPage = Math.max(1, Math.min(totalPages.value, Math.trunc(Number(page) || 1)))
  pageDraft.value = nextPage
  if (nextPage !== props.page) emit('change', nextPage)
}
</script>

<template>
  <nav class="admin-pagination" :aria-label="`${position}列表分页`">
    <span>共 {{ total }} 条</span>
    <button type="button" :disabled="page <= 1" aria-label="上一页" @click="go(page - 1)">
      上一页
    </button>
    <label>
      第
      <input
        v-model.number="pageDraft"
        type="number"
        min="1"
        :max="totalPages"
        :aria-label="`${position}输入页码`"
        @change="go(pageDraft)"
        @keyup.enter="go(pageDraft)"
      />
      / {{ totalPages }} 页
    </label>
    <span class="current" aria-current="page" aria-live="polite">当前第 {{ page }} 页</span>
    <button type="button" :disabled="page >= totalPages" aria-label="下一页" @click="go(page + 1)">
      下一页
    </button>
  </nav>
</template>

<style scoped>
.admin-pagination {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
button,
input {
  height: 32px;
  box-sizing: border-box;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
}
button {
  padding: 0 11px;
  cursor: pointer;
}
button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
input {
  width: 62px;
  padding: 4px 6px;
  text-align: center;
}
.current {
  color: var(--text);
}
@media (max-width: 640px) {
  .current {
    display: none;
  }
}
</style>
