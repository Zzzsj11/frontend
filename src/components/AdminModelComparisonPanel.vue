<script setup lang="ts">
import { ref } from 'vue'
import AdminChatComparisonPanel from './AdminChatComparisonPanel.vue'
import AdminGeneralOutlineComparisonPanel from './AdminGeneralOutlineComparisonPanel.vue'

const mode = ref<'general' | 'free'>('general')
</script>

<template>
  <div class="model-comparison">
    <nav aria-label="模型对比模式">
      <button type="button" :class="{ selected: mode === 'general' }" @click="mode = 'general'">
        通用 MV 大纲
      </button>
      <button type="button" :class="{ selected: mode === 'free' }" @click="mode = 'free'">
        自由提示词
      </button>
    </nav>
    <AdminGeneralOutlineComparisonPanel v-if="mode === 'general'" />
    <AdminChatComparisonPanel v-else />
  </div>
</template>

<style scoped>
.model-comparison {
  display: grid;
  gap: 16px;
}
nav {
  display: flex;
  width: fit-content;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 3px;
  background: var(--bg-secondary);
}
nav button {
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  padding: 8px 16px;
  color: var(--text-secondary);
  cursor: pointer;
}
nav button.selected {
  background: var(--bg);
  color: var(--primary);
  box-shadow: var(--shadow-card);
}
</style>
