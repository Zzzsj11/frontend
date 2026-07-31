<script setup lang="ts">
import ScriptEditor from './components/ScriptEditor.vue'
import PlayerPanel from './components/PlayerPanel.vue'
import TimelinePanel from './components/TimelinePanel.vue'
import AssetLibrary from './components/AssetLibrary.vue'
</script>

<template>
  <div class="app-layout">
    <ScriptEditor class="area-editor" />
    <PlayerPanel class="area-player" />
    <TimelinePanel class="area-timeline" />
    <AssetLibrary />
  </div>
</template>

<style scoped>
.app-layout {
  display: grid;
  grid-template-columns: 55fr 45fr;
  grid-template-rows: minmax(420px, 1fr) auto;
  grid-template-areas:
    'editor player'
    'timeline timeline';
  gap: 14px;
  padding: 14px;
  min-height: 100vh;
  box-sizing: border-box;
}
.area-editor {
  grid-area: editor;
}
.area-player {
  grid-area: player;
}
.area-timeline {
  grid-area: timeline;
}
</style>
