<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ page: number; limit: number; total: number; loading: boolean }>()
const emit = defineEmits<{ page: [value: number]; limit: [value: number] }>()
const pages = computed(() => Math.max(1, Math.ceil(props.total / props.limit)))
function jump(event: Event) {
  const input = event.target as HTMLInputElement
  const value = Math.max(1, Math.min(pages.value, Math.trunc(Number(input.value) || 1)))
  input.value = String(value)
  emit('page', value)
}
</script>
<template>
  <div class="pagination">
    <span>共 {{ total }} 条 · 第 {{ page }} / {{ pages }} 页</span>
    <div class="controls">
      <button class="secondary" :disabled="loading || page <= 1" @click="emit('page', page - 1)">
        上一页
      </button>
      <label
        >页码<input
          aria-label="明细页码"
          type="number"
          min="1"
          :max="pages"
          :value="page"
          :disabled="loading"
          @change="jump"
      /></label>
      <button
        class="secondary"
        :disabled="loading || page >= pages"
        @click="emit('page', page + 1)"
      >
        下一页
      </button>
      <label
        >每页<select
          aria-label="每页条数"
          :value="limit"
          :disabled="loading"
          @change="emit('limit', Number(($event.target as HTMLSelectElement).value))"
        >
          <option :value="10">10 条</option>
          <option :value="20">20 条</option>
          <option :value="50">50 条</option>
        </select></label
      >
    </div>
  </div>
</template>
<style scoped>
.pagination,
.controls,
label {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.pagination {
  justify-content: space-between;
  margin: 24px 0 16px;
  color: var(--muted);
  font-size: 13px;
}
input,
select {
  margin: 0;
}
input {
  width: 70px;
}
select {
  width: 100px;
  flex-shrink: 0;
}
button {
  font-size: 13px;
  padding: 8px 12px;
}
@media (max-width: 600px) {
  .controls {
    gap: 8px;
  }
  label {
    gap: 5px;
  }
}
</style>
