<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import SongSidebar from './components/SongSidebar.vue'
import ScriptEditor from './components/ScriptEditor.vue'
import PlayerPanel from './components/PlayerPanel.vue'
import TimelinePanel from './components/TimelinePanel.vue'
import AssetLibrary from './components/AssetLibrary.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'

const DEFAULT_SIDEBAR_WIDTH = 232
const MAX_SIDEBAR_WIDTH = Math.round(DEFAULT_SIDEBAR_WIDTH * 1.69)
const sidebarWidth = ref(DEFAULT_SIDEBAR_WIDTH)
const resizingSidebar = ref(false)

const clampSidebarWidth = (width: number) =>
  Math.min(Math.max(width, DEFAULT_SIDEBAR_WIDTH), MAX_SIDEBAR_WIDTH)

const stopSidebarResize = () => {
  resizingSidebar.value = false
  window.removeEventListener('mousemove', onSidebarResize)
  window.removeEventListener('mouseup', stopSidebarResize)
}

const onSidebarResize = (event: MouseEvent) => {
  sidebarWidth.value = clampSidebarWidth(event.clientX - 14)
}

const startSidebarResize = (event: MouseEvent) => {
  event.preventDefault()
  resizingSidebar.value = true
  window.addEventListener('mousemove', onSidebarResize)
  window.addEventListener('mouseup', stopSidebarResize)
}

const resizeSidebarByKeyboard = (event: KeyboardEvent) => {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  sidebarWidth.value = clampSidebarWidth(
    sidebarWidth.value + (event.key === 'ArrowRight' ? 10 : -10),
  )
}

onBeforeUnmount(stopSidebarResize)
</script>

<template>
  <div
    class="app-layout"
    :class="{ 'sidebar-resizing': resizingSidebar }"
    :style="{ '--sidebar-width': sidebarWidth + 'px' }"
  >
    <SongSidebar class="area-sidebar" />
    <div
      class="sidebar-resizer"
      role="separator"
      aria-label="调整侧边栏宽度"
      aria-orientation="vertical"
      :aria-valuemin="DEFAULT_SIDEBAR_WIDTH"
      :aria-valuemax="MAX_SIDEBAR_WIDTH"
      :aria-valuenow="sidebarWidth"
      tabindex="0"
      title="拖动调整侧边栏宽度，双击恢复默认"
      @mousedown="startSidebarResize"
      @dblclick="sidebarWidth = DEFAULT_SIDEBAR_WIDTH"
      @keydown="resizeSidebarByKeyboard"
    />
    <ScriptEditor class="area-editor" />
    <PlayerPanel class="area-player" />
    <TimelinePanel class="area-timeline" />
    <AssetLibrary />
    <ConfirmDialog />
  </div>
</template>

<style scoped>
.app-layout {
  display: grid;
  grid-template-columns: var(--sidebar-width, 232px) minmax(0, 55fr) minmax(0, 45fr);
  grid-template-rows: minmax(0, 1fr) auto;
  grid-template-areas:
    'sidebar editor player'
    'sidebar timeline timeline';
  gap: 14px;
  padding: 14px;
  height: 100%;
  max-width: 100vw;
  overflow: hidden;
  box-sizing: border-box;
  position: relative;
}
.sidebar-resizer {
  position: absolute;
  z-index: 20;
  top: 14px;
  bottom: 14px;
  left: calc(14px + var(--sidebar-width, 232px));
  width: 10px;
  transform: translateX(-5px);
  cursor: col-resize;
  outline: none;
}
.sidebar-resizer::after {
  content: '';
  position: absolute;
  top: 10px;
  bottom: 10px;
  left: 4px;
  width: 2px;
  border-radius: var(--radius-xs);
  background: transparent;
  transition:
    background 0.15s,
    width 0.15s,
    left 0.15s;
}
.sidebar-resizer:hover::after,
.sidebar-resizer:focus-visible::after,
.sidebar-resizing .sidebar-resizer::after {
  left: 3px;
  width: 4px;
  background: var(--primary);
}
.sidebar-resizing {
  cursor: col-resize;
  user-select: none;
}
.area-sidebar {
  grid-area: sidebar;
  min-width: 0;
}
.area-editor {
  grid-area: editor;
  min-width: 0;
}
.area-player {
  grid-area: player;
  min-width: 0;
}
.area-timeline {
  grid-area: timeline;
  min-width: 0;
}

/* 窄屏适配：侧边栏与各面板上下堆叠，避免横向拥挤 */
@media (max-width: 900px) {
  .app-layout {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto auto auto auto;
    grid-template-areas:
      'sidebar'
      'editor'
      'player'
      'timeline';
    height: auto;
    min-height: 100vh;
    min-height: 100dvh;
    overflow: visible;
  }
  .sidebar-resizer {
    display: none;
  }
}
</style>
