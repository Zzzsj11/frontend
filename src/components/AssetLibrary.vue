<script setup lang="ts">
import { computed, ref } from 'vue'
import { useProjectStore } from '../stores/project'

const store = useProjectStore()

const activeStyle = ref('全部')
const styles = computed(() => ['全部', ...new Set(store.digitalHumans.map((d) => d.style))])
const filtered = computed(() =>
  activeStyle.value === '全部'
    ? store.digitalHumans
    : store.digitalHumans.filter((d) => d.style === activeStyle.value),
)
</script>

<template>
  <Teleport to="body">
    <div v-if="store.libraryOpen" class="lib-mask" @click.self="store.closeLibrary()">
      <div class="lib-modal">
        <header class="lib-header">
          <div>
            <h3>数字人资产库 · 角色阵容</h3>
            <p class="lib-hint">点击卡片加入/移出本 MV 的角色阵容，全片统一使用同一批角色；每个分镜再从阵容中挑选出演角色（可空镜头 / 可多人）</p>
          </div>
          <button class="close-btn" title="关闭" @click="store.closeLibrary()">✕</button>
        </header>

        <!-- 当前阵容 -->
        <div class="cast-bar">
          <span class="cast-label">当前阵容（{{ store.castHumans.length }}）：</span>
          <template v-if="store.castHumans.length">
            <span v-for="dh in store.castHumans" :key="dh.id" class="cast-chip">
              <img :src="dh.avatar" :alt="dh.name" />
              {{ dh.name }}
              <button class="cast-remove" title="移出阵容" @click="store.toggleCast(dh.id)">✕</button>
            </span>
          </template>
          <span v-else class="cast-empty">暂无角色，所有分镜将以空镜头生成</span>
        </div>

        <!-- 风格筛选 -->
        <div class="style-tabs">
          <button
            v-for="s in styles"
            :key="s"
            class="style-tab"
            :class="{ active: activeStyle === s }"
            @click="activeStyle = s"
          >
            {{ s }}
          </button>
        </div>

        <!-- 数字人卡片 -->
        <div class="dh-grid">
          <div
            v-for="dh in filtered"
            :key="dh.id"
            class="dh-card"
            :class="{ active: store.castIds.includes(dh.id) }"
            @click="store.toggleCast(dh.id)"
          >
            <div class="dh-portrait">
              <img :src="dh.avatar" :alt="dh.name" />
              <span v-if="store.castIds.includes(dh.id)" class="dh-check">✓ 已入阵容</span>
            </div>
            <div class="dh-info">
              <div class="dh-name-row">
                <strong>{{ dh.name }}</strong>
                <span class="dh-style">{{ dh.style }}</span>
              </div>
              <p class="dh-desc">{{ dh.description }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.lib-mask {
  position: fixed;
  inset: 0;
  z-index: 120;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.lib-modal {
  width: 860px;
  max-width: 100%;
  max-height: 90vh;
  background: #fff;
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.25);
}
.lib-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 18px 22px 12px;
  border-bottom: 1px solid var(--border);
}
.lib-header h3 {
  margin: 0;
  font-size: 17px;
}
.lib-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.close-btn {
  border: none;
  background: transparent;
  font-size: 16px;
  color: var(--text-secondary);
  cursor: pointer;
}
.close-btn:hover {
  color: var(--text);
}

/* 当前阵容 */
.cast-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 12px 22px 0;
}
.cast-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
}
.cast-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--primary);
  background: var(--primary-light);
  color: var(--primary);
  border-radius: 16px;
  padding: 3px 8px 3px 4px;
  font-size: 13px;
}
.cast-chip img {
  width: 22px;
  height: 28px;
  border-radius: 6px;
  object-fit: cover;
}
.cast-remove {
  border: none;
  background: transparent;
  color: var(--primary);
  font-size: 11px;
  cursor: pointer;
  padding: 0 2px;
}
.cast-empty {
  font-size: 13px;
  color: var(--text-secondary);
}

/* 风格筛选 */
.style-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  padding: 12px 22px 0;
}
.style-tab {
  border: 1px solid var(--border-dark);
  border-radius: 16px;
  background: #fff;
  color: var(--text);
  font-size: 13px;
  padding: 5px 14px;
  cursor: pointer;
  transition: all 0.15s;
}
.style-tab:hover {
  border-color: var(--primary);
  color: var(--primary);
}
.style-tab.active {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

/* 数字人卡片 */
.dh-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  padding: 16px 22px 22px;
  overflow-y: auto;
}
.dh-card {
  border: 2px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.15s, transform 0.1s, box-shadow 0.15s;
  background: #fff;
}
.dh-card:hover {
  border-color: rgba(255, 90, 44, 0.5);
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.08);
}
.dh-card.active {
  border-color: var(--primary);
}
.dh-portrait {
  position: relative;
  aspect-ratio: 3 / 4;
  background: #f5f5f5;
}
.dh-portrait img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.dh-check {
  position: absolute;
  top: 8px;
  right: 8px;
  background: var(--primary);
  color: #fff;
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 10px;
}
.dh-info {
  padding: 8px 10px 10px;
}
.dh-name-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.dh-name-row strong {
  font-size: 14px;
}
.dh-style {
  font-size: 11px;
  color: var(--primary);
  background: var(--primary-light);
  padding: 2px 8px;
  border-radius: 8px;
  white-space: nowrap;
}
.dh-desc {
  margin: 5px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
