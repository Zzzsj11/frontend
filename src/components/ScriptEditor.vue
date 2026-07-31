<script setup lang="ts">
import { ref } from 'vue'
import { useProjectStore } from '../stores/project'
import ScriptLineItem from './ScriptLine.vue'
import ShotDetailModal from './ShotDetailModal.vue'

const store = useProjectStore()

// HTML5 拖拽排序
const dragIndex = ref(-1)
const overIndex = ref(-1)

const onDragStart = (index: number, e: DragEvent) => {
  dragIndex.value = index
  e.dataTransfer!.effectAllowed = 'move'
}
const onDragOver = (index: number, e: DragEvent) => {
  e.preventDefault()
  overIndex.value = index
}
const onDrop = (index: number) => {
  if (dragIndex.value >= 0) store.moveLine(dragIndex.value, index)
  dragIndex.value = -1
  overIndex.value = -1
}
</script>

<template>
  <section class="panel script-editor">
    <header class="panel-header">
      <div class="title-group">
        <h2>脚本编辑器</h2>
        <span class="subtitle">每一条为一个分镜，点击编辑歌词、场景与出演角色</span>
      </div>
      <div class="header-actions">
        <button class="btn-outline" @click="store.openLibrary()">
          👥 角色阵容
          <span v-if="store.castHumans.length" class="cast-count">{{ store.castHumans.length }}</span>
        </button>
        <button class="btn-outline" :disabled="store.batchVoicing" @click="store.generateAllVoices()">
          <span v-if="store.batchVoicing" class="spinner" />
          <span v-else>🎙️</span>
          全部配音
        </button>
        <button class="btn-outline" :disabled="store.batchShooting" @click="store.generateAllShots()">
          <span v-if="store.batchShooting" class="spinner" />
          <span v-else>🎬</span>
          全部分镜
        </button>
        <button class="btn-primary" :disabled="store.magicLoading" @click="store.runMagicScript()">
          <span v-if="store.magicLoading" class="spinner light" />
          <span v-else>✨</span>
          AI 魔法脚本
        </button>
      </div>
    </header>

    <div class="line-list">
      <div
        v-for="(line, index) in store.lines"
        :key="line.id"
        class="line-wrapper"
        :class="{ 'drag-over': overIndex === index && dragIndex !== index }"
        draggable="true"
        @dragstart="onDragStart(index, $event)"
        @dragover="onDragOver(index, $event)"
        @drop="onDrop(index)"
        @dragend="dragIndex = -1; overIndex = -1"
      >
        <ScriptLineItem :line="line" :index="index" />
      </div>

      <p v-if="store.lines.length === 0" class="empty-tip">
        暂无分镜，点击下方按钮或「AI 魔法脚本」开始创作
      </p>
    </div>

    <footer class="editor-footer">
      <button class="btn-add" @click="store.addLine()">＋ 单个分镜</button>
    </footer>

    <ShotDetailModal />
  </section>
</template>

<style scoped>
.script-editor {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.title-group {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.subtitle {
  color: var(--text-secondary);
  font-size: 13px;
}
.header-actions {
  display: flex;
  gap: 8px;
}
.cast-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  border-radius: 9px;
  background: var(--primary);
  color: #fff;
  font-size: 11px;
  padding: 0 5px;
}
.line-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 14px;
  padding-right: 4px;
  min-height: 200px;
}
.line-wrapper.drag-over {
  outline: 2px dashed var(--primary);
  outline-offset: 2px;
  border-radius: 12px;
}
.empty-tip {
  color: var(--text-secondary);
  text-align: center;
  margin-top: 60px;
  font-size: 14px;
}
.editor-footer {
  display: flex;
  justify-content: center;
  padding-top: 14px;
}
.btn-add {
  border: 1px dashed var(--border-dark);
  border-radius: 10px;
  background: #fff;
  color: var(--text);
  padding: 8px 28px;
  font-size: 14px;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}
.btn-add:hover {
  border-color: var(--primary);
  color: var(--primary);
}
</style>
