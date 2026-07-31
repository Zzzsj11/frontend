<script setup lang="ts">
import SongSidebar from './components/SongSidebar.vue'
import ScriptEditor from './components/ScriptEditor.vue'
import PlayerPanel from './components/PlayerPanel.vue'
import TimelinePanel from './components/TimelinePanel.vue'
import AssetLibrary from './components/AssetLibrary.vue'
</script>

<template>
  <div class="app-layout">
    <SongSidebar class="area-sidebar" />
    <ScriptEditor class="area-editor" />
    <PlayerPanel class="area-player" />
    <TimelinePanel class="area-timeline" />
    <AssetLibrary />
  </div>
</template>

<style scoped>
.app-layout {
  display: grid;
  grid-template-columns: 232px minmax(0, 55fr) minmax(0, 45fr);
  grid-template-rows: minmax(420px, 1fr) auto;
  grid-template-areas:
    'sidebar editor player'
    'sidebar timeline timeline';
  gap: 14px;
  padding: 14px;
  min-height: 100vh;
  max-width: 100vw;
  overflow-x: clip;
  box-sizing: border-box;
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
  }
}
</style>
