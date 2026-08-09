<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ScriptLine } from '../types'
import { useProjectStore } from '../stores/project'
import AppIcon from './AppIcon.vue'
import { confirmDialog } from '../composables/useConfirmDialog'

const props = defineProps<{
  line: ScriptLine
  index: number
}>()

const store = useProjectStore()
const selected = computed(() => store.selectedLineId === props.line.id)
/** 出演角色（可空/可多个） */
const humans = computed(() => store.lineHumans(props.line))
/** 缩略图：真实视频 > 视频封面 > 场景底图 */
const video = computed(() => store.videoOf(props.line))
const cover = computed(() => store.coverOf(props.line))
const originalCover = computed(() => {
  const asset = props.line.shot.assets.find((item) => item.id === props.line.shot.currentAssetId)
  return asset?.originalCoverUrl || props.line.scene.originalImageUrl || cover.value
})
const hoveringPreview = ref(false)
/** 歌词非中文时的中文翻译 */
const translation = computed(() => store.translationOf(props.line))
const isGeneral = computed(() => props.line.source === 'general')

// 点击不同文字内容时，直接展开对应的编辑选项
const openShotDetail = () => store.openEditor(props.line.id, 'shot')
const openSceneDetail = () => store.openEditor(props.line.id, 'scene')

/** 缩略图可能来自场景图，也可能是在无场景图时由视频首帧/封面占位 */
const openThumbnailEditor = () => {
  const tab = !props.line.scene.imageUrl && props.line.shot.assets.length ? 'shot' : 'scene'
  store.openEditor(props.line.id, tab)
}

// 生成 / 重新生成分镜视频片段：已有片段时二次确认，避免误触
const onGenerateShot = async () => {
  if (props.line.shot.status === 'done' && !await confirmDialog({
    title: '重新生成分镜',
    message: '确定重新生成该分镜视频片段？将新增一个视频版本。',
    confirmText: '重新生成',
  })) return
  store.generateShotFor(props.line.id)
}
</script>

<template>
  <div class="script-line" :class="{ selected }" @click="store.selectLine(line.id)">
    <span class="drag-handle" title="拖拽排序">⠿</span>
    <span class="line-index">{{ index + 1 }}</span>

    <!-- 分镜缩略图 -->
    <div
      class="shot-thumb"
      :title="!line.scene.imageUrl && line.shot.assets.length ? '编辑分镜' : '编辑场景'"
      @click.stop="openThumbnailEditor"
      @mouseenter="hoveringPreview = true"
      @mouseleave="hoveringPreview = false"
    >
      <video v-if="video" :src="video" preload="metadata" muted />
      <img v-else-if="cover" :src="cover" alt="分镜缩略图" />
      <span v-else class="thumb-placeholder"><AppIcon name="image" :size="18" /></span>
      <div v-if="line.shot.status === 'generating' || line.scene.status === 'generating'" class="thumb-loading">
        <span class="spinner light" />
      </div>
    </div>

    <Teleport to="body">
      <div v-if="hoveringPreview && originalCover" class="media-original-preview" aria-hidden="true">
        <img :src="originalCover" alt="分镜原图预览" />
        <span>原图预览</span>
      </div>
    </Teleport>

    <!-- 出演角色（叠放展示，空 = 空镜头） -->
    <div
      v-if="humans.length"
      class="dh-chips"
      :title="`编辑人物 · 出演：${humans.map((h) => h.name).join(' / ')}`"
      @click.stop="store.openEditor(line.id, 'cast')"
    >
      <img v-for="dh in humans" :key="dh.id" class="dh-chip" :src="dh.avatar" :alt="dh.name" />
    </div>

    <!-- 歌词 + 提示词摘要 -->
    <div class="line-info">
      <div v-if="line.generationStatus === 'pending' || line.generationStatus === 'running'" class="prompt-generation-state">
        <span class="spinner" /> {{ line.generationStatus === 'pending' ? '等待生成提示词' : '正在生成提示词' }}
      </div>
      <div v-else-if="line.generationStatus === 'failed'" class="prompt-generation-state failed">
        生成失败
        <button @click.stop="store.retryStoryboardLine(line.id)">重新生成</button>
      </div>
      <div v-if="isGeneral" class="general-meta">
        <span class="shot-type" :class="line.shotType">{{ line.shotType === 'empty' ? '空镜' : '人物镜' }}</span>
        <span v-if="line.plannedDuration" class="planned-duration">预计 {{ line.plannedDuration }} 秒</span>
      </div>
      <p v-else class="lyrics editable-text" @click.stop="openShotDetail">{{ line.lyrics || '（未填写歌词）' }}</p>
      <p v-if="!isGeneral && translation" class="lyrics-zh editable-text" @click.stop="openShotDetail"><span class="zh-tag">译</span>{{ translation }}</p>
      <p v-if="isGeneral" class="scene-summary editable-text" @click.stop="openSceneDetail">{{ line.scenePrompt || '暂无场景提示词' }}</p>
      <p class="prompt editable-text" @click.stop="openShotDetail">{{ line.shotPrompt || line.scenePrompt || '暂无提示词，点击编辑场景与分镜' }}</p>
    </div>

    <div class="line-actions" @click.stop>
      <!-- 生成分镜视频片段 -->
      <button
        class="icon-btn"
        :class="{ active: line.shot.status === 'done' }"
        :disabled="line.shot.status === 'generating'"
        :title="line.shot.status === 'done' ? '重新生成视频片段' : '生成视频片段（场景 × 分镜 × 角色）'"
        @click="onGenerateShot"
      >
        <span v-if="line.shot.status === 'generating'" class="spinner" />
        <AppIcon v-else name="movie" :size="15" />
      </button>
      <!-- 删除（仅手动添加的分镜可删，脚本生成的分镜不显示） -->
      <button v-if="line.manual" class="icon-btn danger" title="删除" @click="store.removeLine(line.id)">
        <AppIcon name="trash" :size="15" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.media-original-preview {
  position: fixed;
  z-index: 1500;
  inset: 50% auto auto 50%;
  transform: translate(-50%, -50%);
  max-width: min(80vw, 1100px);
  max-height: 82vh;
  padding: 10px;
  border-radius: 12px;
  background: rgba(15, 15, 18, 0.94);
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.42);
  pointer-events: none;
}
.media-original-preview img { display: block; max-width: 100%; max-height: calc(82vh - 38px); object-fit: contain; border-radius: 8px; }
.media-original-preview span { display: block; margin-top: 7px; color: #fff; text-align: center; font-size: 12px; }
.script-line {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: #fff;
  cursor: default;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.prompt-generation-state { display: flex; align-items: center; gap: 6px; color: var(--text-muted); font-size: 12px; margin-bottom: 4px; }
.prompt-generation-state.failed { color: #c0392b; }
.prompt-generation-state button { border: 0; background: transparent; color: var(--primary); cursor: pointer; padding: 0; }
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
  border: 1px solid transparent;
  transition: transform 0.15s, border-color 0.15s, box-shadow 0.15s;
  cursor: pointer;
}
.shot-thumb:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: var(--primary);
  box-shadow: 0 5px 14px rgba(255, 90, 44, 0.18);
}
.shot-thumb img,
.shot-thumb video {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.thumb-placeholder {
  display: inline-flex;
  color: var(--text-secondary);
  opacity: 0.6;
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
  cursor: pointer;
}
.dh-chips .dh-chip:not(:first-child) {
  margin-left: -12px;
}
.dh-chip {
  width: 48px;
  height: 27px;
  border-radius: 6px;
  object-fit: contain;
  border: 1px solid var(--border);
  box-shadow: 0 0 0 2px #fff;
  transition: transform 0.15s, border-color 0.15s, box-shadow 0.15s;
}
.dh-chip:hover {
  position: relative;
  z-index: 2;
  transform: translateY(-3px) scale(1.06);
  border-color: var(--primary);
  box-shadow: 0 0 0 2px #fff, 0 5px 12px rgba(255, 90, 44, 0.22);
}
.line-info {
  flex: 1;
  min-width: 0;
}
.editable-text {
  cursor: pointer;
  transition: color 0.15s;
}
.editable-text:hover {
  color: var(--primary);
}
.lyrics {
  margin: 0;
  font-size: 14px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.general-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 3px;
}
.shot-type {
  padding: 2px 7px;
  border-radius: 5px;
  background: #eef3ff;
  color: #4776c8;
  font-size: 11px;
  font-weight: 600;
}
.shot-type.character {
  color: var(--primary);
  background: var(--primary-light);
}
.planned-duration {
  color: var(--text-secondary);
  font-size: 11px;
}
.scene-summary {
  margin: 0;
  font-size: 13px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* 非中文歌词的中文翻译 */
.lyrics-zh {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--text);
  opacity: 0.65;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* 翻译行左侧「译」标识 */
.zh-tag {
  display: inline-block;
  margin-right: 5px;
  padding: 0 4px;
  font-size: 10px;
  line-height: 15px;
  border-radius: 4px;
  color: var(--primary);
  background: var(--primary-light);
  border: 1px solid rgba(255, 90, 44, 0.35);
  vertical-align: 1px;
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
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 14px;
  transition: border-color 0.15s, background 0.15s, color 0.15s, transform 0.15s, box-shadow 0.15s;
}
.icon-btn:hover:not(:disabled) {
  border-color: var(--primary);
  background: var(--primary-light);
  color: var(--primary);
  transform: translateY(-2px) scale(1.05);
  box-shadow: 0 5px 12px rgba(255, 90, 44, 0.18);
}
.icon-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.icon-btn.active {
  border-color: var(--primary);
  background: rgba(255, 90, 44, 0.08);
  color: var(--primary);
}
.icon-btn.active:hover:not(:disabled) {
  background: rgba(255, 90, 44, 0.14);
}
.icon-btn.danger:hover {
  border-color: #e33;
  background: rgba(238, 51, 51, 0.06);
  color: #e33;
}
</style>
