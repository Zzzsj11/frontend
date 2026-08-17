<script setup lang="ts">
import { ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import type { AdminNavGroup } from '../types'

/**
 * 管理后台侧边导航（两级分组，参考主流 Vue3 admin 的分组菜单模式）。
 * 组可折叠，折叠状态存 localStorage；当前激活项所在组强制展开，避免当前页被折进不可见区域。
 */
const props = defineProps<{ groups: AdminNavGroup[]; active: string }>()
const emit = defineEmits<{ select: [key: string] }>()

const STORAGE_KEY = 'admin-nav-collapsed'

const loadCollapsed = (): Record<string, boolean> => {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') as Record<string, boolean>
  } catch {
    return {}
  }
}
const collapsed = ref<Record<string, boolean>>(loadCollapsed())
watch(collapsed, (value) => localStorage.setItem(STORAGE_KEY, JSON.stringify(value)), {
  deep: true,
})

const toggleGroup = (key: string) => {
  collapsed.value[key] = !collapsed.value[key]
}
const isOpen = (group: AdminNavGroup) =>
  !collapsed.value[group.key] || group.items.some((item) => item.key === props.active)
</script>

<template>
  <aside class="side-nav">
    <RouterLink class="brand" to="/projects" aria-label="返回镜序 MV 工作台">
      <span class="brand-mark" aria-hidden="true">↗</span>
      <span class="brand-text">
        <b>镜序 MV</b>
        <small>管理控制台</small>
      </span>
    </RouterLink>
    <nav class="nav-groups" aria-label="管理功能导航">
      <section v-for="group in groups" :key="group.key" class="nav-group">
        <button
          type="button"
          class="group-title"
          :aria-expanded="isOpen(group)"
          @click="toggleGroup(group.key)"
        >
          <span>{{ group.label }}</span>
          <AppIcon name="chevron-right" :size="12" class="chev" :class="{ open: isOpen(group) }" />
        </button>
        <div v-show="isOpen(group)" class="group-items">
          <button
            v-for="item in group.items"
            :key="item.key"
            type="button"
            class="nav-item"
            :class="{ on: active === item.key }"
            @click="emit('select', item.key)"
          >
            {{ item.label }}
          </button>
        </div>
      </section>
    </nav>
    <RouterLink class="back-link" to="/projects">← 返回工作台</RouterLink>
  </aside>
</template>

<style scoped>
.side-nav {
  display: flex;
  flex-direction: column;
  padding: 18px 12px 12px;
  background: var(--surface);
  border-right: 1px solid var(--border);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 8px 16px;
  color: var(--text);
  text-decoration: none;
}
.brand-mark {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 10px;
  background: var(--primary-gradient);
  color: #fff;
  font-size: 18px;
  font-weight: 700;
}
.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.brand-text b {
  font-size: 15px;
  font-weight: 700;
}
.brand-text small {
  font-size: 11px;
  color: var(--text-secondary);
}
.nav-groups {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
}
.nav-group {
  display: flex;
  flex-direction: column;
}
.group-title {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  border: 0;
  border-radius: var(--radius-xs);
  background: transparent;
  padding: 12px 8px 6px;
  color: var(--text-secondary);
  font-size: var(--font-sm);
  font-weight: 600;
  letter-spacing: 0.08em;
  cursor: pointer;
}
.group-title:hover {
  color: var(--text);
}
.chev {
  transition: transform 0.15s;
}
.chev.open {
  transform: rotate(90deg);
}
.group-items {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 2px 0 6px;
}
.nav-item {
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  padding: 8px 10px 8px 14px;
  color: var(--text-regular);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition:
    background 0.12s,
    color 0.12s;
}
.nav-item:hover {
  background: var(--bg);
  color: var(--text);
}
.nav-item.on {
  background: var(--primary-light);
  color: var(--primary);
  font-weight: 600;
}
.back-link {
  margin-top: auto;
  border-radius: var(--radius-sm);
  padding: 10px 8px 2px;
  color: var(--text-secondary);
  font-size: 13px;
  text-decoration: none;
}
.back-link:hover {
  color: var(--primary);
}
</style>
