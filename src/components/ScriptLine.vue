<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ScriptLine } from '../types'
import { useProjectStore } from '../stores/project'

const props = defineProps<{
  line: ScriptLine
  index: number
}>()

const store = useProjectStore()
const selected = computed(() => store.selectedLineId === props.line.id)
/** 出演角色（可空/可多个） */
const humans = computed(() => store.lineHumans(props.line))
/** 缩略图：视频封面 > 场景底图 */
const cover = computed(() => store.coverOf(props.line))

const audioRef = ref<HTMLAudioElement>()

const playVoice = () => {
  if (!props.line.voice.url) return
  audioRef.value?.play()
}

// 点开分镜行 → 选中并打开编辑弹窗
const openDetail = () => store.openEditor(props.line.id)
</script>

<template>
  <div class="script-line" :class="{ selected }" @click="openDetail">
    <span class="drag-handle" title="拖拽排序">⠿</span>
    <span class="line-index">{{ index + 1 }}</span>

    <!-- 分镜缩略图 -->
    <div class="shot-thumb">
      <img v-if="cover" :src="cover" alt="分镜缩略图" />
      <span v-else class="thumb-placeholder">🖼️</span>
      <div v-if="line.shot.status === 'generating' || line.scene.status === 'generating'" class="thumb-loading">
        <span class="spinner light" />
      </div>
    </div>

    <!-- 出演角色（叠放展示，空 = 空镜头） -->
    <div v-if="humans.length" class="dh-chips" :title="`出演：${humans.map((h) => h.name).join(' / ')}`">
      <img v-for="dh in humans" :key="dh.id" class="dh-chip" :src="dh.avatar" :alt="dh.name" />
    </div>

    <!-- 歌词 + 提示词摘要 -->
    <div class="line-info">
      <p class="lyrics">{{ line.lyrics || '（未填写歌词）' }}</p>
      <p class="prompt">{{ line.shotPrompt || line.scenePrompt || '暂无提示词，点击编辑场景与分镜' }}</p>
    </div>

    <div class="line-actions" @click.stop>
      <!-- 生成配音 -->
      <button
        class="icon-btn"
        :class="{ active: line.voice.status === 'done' }"
        :disabled="line.voice.status === 'generating'"
        :title="line.voice.status === 'done' ? '重新生成配音' : '生成配音'"
        @click="store.generateVoiceFor(line.id)"
      >
        <span v-if="line.voice.status === 'generating'" class="spinner" />
        <span v-else>🎙️</span>
      </button>
      <!-- 生成分镜视频片段 -->
      <button
        class="icon-btn"
        :class="{ active: line.shot.status === 'done' }"
        :disabled="line.shot.status === 'generating'"
        :title="line.shot.status === 'done' ? '重新生成视频片段' : '生成视频片段（场景 × 分镜 × 角色）'"
        @click="store.generateShotFor(line.id)"
      >
        <span v-if="line.shot.status === 'generating'" class="spinner" />
        <span v-else>🎬</span>
      </button>
      <!-- 试听配音 -->
      <button class="icon-btn" :disabled="line.voice.status !== 'done'" title="试听配音" @click="playVoice">
        🔊
      </button>
      <!-- 删除 -->
      <button class="icon-btn danger" title="删除" @click="store.removeLine(line.id)">🗑️</button>
    </div>

    <audio v-if="line.voice.url" ref="audioRef" :src="line.voice.url" preload="none" />
  </div>
</template>

<style scoped>
.script-line {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.script-line.selected {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(255, 90, 44, 0.12);
}
.drag-handle {
  color: #bbb;
  cursor: grab;
  font-size: 14px;
  user-select: none;
}
.line-index {
  min-width: 18px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 14px;
}
.shot-thumb {
  position: relative;
  width: 72px;
  height: 42px;
  border-radius: 8px;
  overflow: hidden;
  background: #f0f0f0;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.shot-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.thumb-placeholder {
  font-size: 16px;
  opacity: 0.5;
}
.thumb-loading {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
}
.dh-chips {
  display: flex;
  flex-shrink: 0;
}
.dh-chips .dh-chip:not(:first-child) {
  margin-left: -12px;
}
.dh-chip {
  width: 30px;
  height: 40px;
  border-radius: 6px;
  object-fit: cover;
  border: 1px solid var(--border);
  box-shadow: 0 0 0 2px #fff;
}
.line-info {
  flex: 1;
  min-width: 0;
}
.lyrics {
  margin: 0;
  font-size: 14px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.prompt {
  margin: 3px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.line-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.icon-btn {
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  font-size: 14px;
  transition: border-color 0.15s, background 0.15s;
}
.icon-btn:hover:not(:disabled) {
  border-color: var(--primary);
}
.icon-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.icon-btn.active {
  border-color: var(--primary);
  background: rgba(255, 90, 44, 0.08);
}
.icon-btn.danger:hover {
  border-color: #e33;
  background: rgba(238, 51, 51, 0.06);
}
</style>
