<script setup lang="ts">
defineProps<{ categories: { id: string; label: string }[] }>()
const category = defineModel<string>('category', { required: true })
const search = defineModel<string>('search', { required: true })
</script>
<template>
  <div class="model-search" role="search" aria-label="模型搜索">
    <div class="category-tabs" role="group" aria-label="模型类型">
      <button
        v-for="item in categories"
        :key="item.id"
        :class="{ active: category === item.id }"
        :aria-pressed="category === item.id"
        @click="category = item.id"
      >
        {{ item.label }}
      </button>
    </div>
    <label class="search-field">
      <svg
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        aria-hidden="true"
      >
        <circle cx="10.5" cy="10.5" r="6.5" />
        <path d="m16 16 4.5 4.5" />
      </svg>
      <input
        v-model="search"
        aria-label="搜索模型或公司"
        placeholder="搜索模型或公司"
        type="search"
      />
    </label>
  </div>
</template>
<style scoped>
.model-search {
  display: flex;
  align-items: center;
  width: min(100%, 680px);
  margin: 0 auto;
  padding: 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel);
  gap: 8px;
}
.model-search:focus-within {
  border-color: var(--primary);
}
.category-tabs {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.category-tabs button {
  background: transparent;
  color: var(--muted);
}
.category-tabs button.active {
  background: var(--primary-light);
  color: var(--primary);
}
.search-field {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  margin: 0;
  padding-left: 16px;
  border-left: 1px solid var(--border);
  color: var(--muted);
}
.search-field svg {
  flex-shrink: 0;
}
.search-field input {
  width: 100%;
  min-width: 0;
  margin: 0;
  border: 0;
  background: transparent;
  padding: 12px 8px;
}
@media (max-width: 600px) {
  .model-search {
    flex-direction: column;
  }
  .search-field {
    width: 100%;
    border-left: 0;
    border-top: 1px solid var(--border);
    padding: 4px 8px 0;
  }
  .category-tabs {
    width: 100%;
  }
  .category-tabs button {
    flex: 1;
  }
}
</style>
