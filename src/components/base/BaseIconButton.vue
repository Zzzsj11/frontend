<script setup lang="ts">
import AppIcon from '../AppIcon.vue'
import type { IconName } from '../AppIcon.vue'

/** 统一图标按钮：承载 hover 动效、active 选中、danger 危险、loading 转圈四种状态 */
withDefaults(
  defineProps<{
    name: IconName
    size?: number
    /** 可访问名称，同时作为 hover 提示（仅图标按钮必填） */
    title: string
    disabled?: boolean
    /** 为 true 时显示转圈并禁用点击 */
    loading?: boolean
    active?: boolean
    danger?: boolean
  }>(),
  { size: 16, disabled: false, loading: false, active: false, danger: false },
)
defineEmits<{ click: [event: MouseEvent] }>()
</script>

<template>
  <button
    class="base-icon-btn"
    :class="{ active, danger }"
    :disabled="disabled || loading"
    :title="title"
    :aria-label="title"
    @click="$emit('click', $event)"
  >
    <span v-if="loading" class="spinner" />
    <AppIcon v-else :name="name" :size="size" />
  </button>
</template>

<style scoped>
.base-icon-btn {
  display: inline-flex;
  width: 32px;
  height: 32px;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: var(--font-md);
  cursor: pointer;
  transition:
    color 0.15s,
    border-color 0.15s,
    background 0.15s,
    transform 0.15s;
}
.base-icon-btn:hover:not(:disabled) {
  border-color: var(--primary);
  background: var(--primary-light);
  color: var(--primary);
  transform: translateY(-2px) scale(1.05);
}
.base-icon-btn:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.base-icon-btn.active {
  border-color: var(--primary);
  background: var(--primary-light);
  color: var(--primary);
}
.base-icon-btn.active:hover:not(:disabled) {
  background: rgba(255, 90, 44, 0.14);
}
.base-icon-btn.danger:hover:not(:disabled) {
  border-color: var(--danger);
  background: rgba(238, 51, 51, 0.06);
  color: var(--danger);
}
</style>
