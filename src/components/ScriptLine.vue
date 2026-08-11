<script setup lang="ts">
import { computed } from 'vue'
import type { ScriptLine } from '../types'
import { formatTime, useProjectStore } from '../stores/project'
import AppIcon from './AppIcon.vue'
import BaseIconButton from './base/BaseIconButton.vue'
import CharacterPortrait from './CharacterPortrait.vue'
import ImageZoom from './ImageZoom.vue'
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
/** 歌词非中文时的中文翻译 */
const translation = computed(() => store.translationOf(props.line))
const isGeneral = computed(() => props.line.source === 'general')

/** ASS 大纲状态：pending=待生成 / failed=所在场景段生成失败 */
const outlineStatus = computed(() => props.line.shotOptions?.outlineStatus)
const outlining = computed(() => store.outlinePhase === 'outlining')
/** 结构段（前奏/间奏/尾奏）徽章文案，歌词句不展示 */
const segmentBadge = computed(() => {
  const type = props.line.shotOptions?.segmentType
  return type && type !== 'lyric' ? props.line.shotOptions?.timelineLabel || '' : ''
})
/** ASS 时间轴起止时间（mm:ss–mm:ss） */
const timeRange = computed(() =>
  props.line.start != null && props.line.end != null
    ? `${formatTime(props.line.start)}–${formatTime(props.line.end)}`
    : '',
)

// 点击不同文字内容时，直接展开对应的编辑选项
const openShotDetail = () => store.openEditor(props.line.id, 'shot')
const openSceneDetail = () => store.openEditor(props.line.id, 'scene')

/** 场景图/视频生成失败摘要（缩略图角标与按钮的 hover 提示共用） */
const mediaError = computed(() => {
  const errors: string[] = []
  if (props.line.scene.status === 'failed')
    errors.push(`场景图生成失败：${props.line.scene.error || '未知原因'}`)
  if (props.line.shot.status === 'failed')
    errors.push(`视频生成失败：${props.line.shot.error || '未知原因'}`)
  return errors.join('\n')
})

/** 缩略图可能来自场景图，也可能是在无场景图时由视频首帧/封面占位；失败时直达对应编辑页重试 */
const openThumbnailEditor = () => {
  const tab =
    props.line.shot.status === 'failed'
      ? 'shot'
      : props.line.scene.status === 'failed'
        ? 'scene'
        : !props.line.scene.imageUrl && props.line.shot.assets.length
          ? 'shot'
          : 'scene'
  store.openEditor(props.line.id, tab)
}

// 生成 / 重新生成分镜视频片段：已有片段时二次确认，避免误触
const onGenerateShot = async () => {
  if (
    props.line.shot.status === 'done' &&
    !(await confirmDialog({
      title: '重新生成视频',
      message: '确定重新生成该视频片段？将新增一个视频版本。',
      confirmText: '重新生成',
    }))
  )
    return
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
      :title="!line.scene.imageUrl && line.shot.assets.length ? '编辑视频' : '编辑场景'"
      @click.stop="openThumbnailEditor"
    >
      <video v-if="video" :src="video" preload="metadata" muted />
      <img v-else-if="cover" :src="cover" alt="视频缩略图" />
      <span v-else class="thumb-placeholder"><AppIcon name="image" :size="18" /></span>
      <div
        v-if="line.shot.status === 'generating' || line.scene.status === 'generating'"
        class="thumb-loading"
      >
        <span class="spinner light" />
      </div>
      <span
        v-else-if="mediaError"
        class="thumb-failed"
        :title="`${mediaError}\n点击查看原因并重新生成`"
        ><AppIcon name="alert" :size="11"
      /></span>
      <ImageZoom :src="originalCover" alt="视频封面原图预览" />
    </div>

    <!-- 出演角色（叠放展示，空 = 空镜头） -->
    <div
      v-if="humans.length"
      class="dh-chips"
      :title="`编辑人物 · 出演：${humans.map((h) => h.name).join(' / ')}`"
      @click.stop="store.openEditor(line.id, 'cast')"
    >
      <CharacterPortrait
        v-for="dh in humans"
        :key="dh.id"
        class="dh-chip"
        :src="dh.avatar"
        :alt="dh.name"
      />
    </div>

    <!-- 歌词 + 提示词摘要 -->
    <div class="line-info">
      <div v-if="outlineStatus === 'pending'" class="prompt-generation-state">
        <span v-if="outlining" class="spinner" />{{ outlining ? '正在生成大纲' : '待生成大纲' }}
      </div>
      <div v-else-if="outlineStatus === 'failed'" class="prompt-generation-state failed">
        所在场景段大纲未生成，可在上方横幅中重试
      </div>
      <div
        v-else-if="line.generationStatus === 'pending' || line.generationStatus === 'running'"
        class="prompt-generation-state"
      >
        <span class="spinner" />
        {{ line.generationStatus === 'pending' ? '等待生成提示词' : '正在生成提示词' }}
      </div>
      <div v-else-if="line.generationStatus === 'failed'" class="prompt-generation-state failed">
        <span class="error-text" :title="line.generationError"
          >生成失败{{ line.generationError ? `：${line.generationError}` : '' }}</span
        >
        <button @click.stop="store.retryStoryboardLine(line.id)">重新生成</button>
      </div>
      <div v-if="isGeneral" class="general-meta">
        <span class="shot-type" :class="line.shotType">{{
          line.shotType === 'empty' ? '空镜' : '人物镜'
        }}</span>
        <span v-if="line.plannedDuration" class="planned-duration"
          >预计 {{ line.plannedDuration }} 秒</span
        >
      </div>
      <template v-else>
        <div v-if="segmentBadge || timeRange" class="ass-meta">
          <span v-if="segmentBadge" class="segment-tag">{{ segmentBadge }}</span>
          <span v-if="timeRange" class="time-range">{{ timeRange }}</span>
          <span v-if="line.plannedDuration" class="planned-duration"
            >预计 {{ line.plannedDuration }} 秒</span
          >
        </div>
        <p class="lyrics editable-text" @click.stop="openShotDetail">
          {{ line.lyrics || line.shotOptions?.timelineLabel || '（未填写歌词）' }}
        </p>
      </template>
      <p
        v-if="!isGeneral && translation"
        class="lyrics-zh editable-text"
        @click.stop="openShotDetail"
      >
        <span class="zh-tag">译</span>{{ translation }}
      </p>
      <p v-if="isGeneral" class="scene-summary editable-text" @click.stop="openSceneDetail">
        {{ line.scenePrompt || '暂无场景提示词' }}
      </p>
      <p class="prompt editable-text" @click.stop="openShotDetail">
        {{ line.shotPrompt || line.scenePrompt || '暂无提示词，点击编辑场景与视频' }}
      </p>
    </div>

    <div class="line-actions" @click.stop>
      <!-- 生成分镜视频片段 -->
      <BaseIconButton
        name="movie"
        :size="15"
        :class="{ 'gen-failed': line.shot.status === 'failed' }"
        :active="line.shot.status === 'done'"
        :loading="line.shot.status === 'generating'"
        :title="
          line.shot.status === 'failed'
            ? `视频生成失败：${line.shot.error || '未知原因'}，点击重新生成`
            : line.shot.status === 'done'
              ? '重新生成视频片段'
              : '生成视频片段（场景 × 视频提示词 × 角色）'
        "
        @click="onGenerateShot"
      />
      <!-- 删除（仅手动添加的分镜可删，脚本生成的分镜不显示） -->
      <BaseIconButton
        v-if="line.manual"
        name="trash"
        :size="15"
        danger
        title="删除"
        @click="store.removeLine(line.id)"
      />
    </div>
  </div>
</template>

<style scoped>
.script-line {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: #fff;
  cursor: default;
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}
.prompt-generation-state {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
  font-size: var(--font-sm);
  margin-bottom: 4px;
}
.prompt-generation-state.failed {
  color: var(--danger-active);
}
.prompt-generation-state button {
  border: 0;
  background: transparent;
  color: var(--primary);
  cursor: pointer;
  padding: 0;
}
.script-line.selected {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(255, 90, 44, 0.12);
}
.drag-handle {
  color: #bbb;
  cursor: grab;
  font-size: var(--font-md);
  user-select: none;
}
.line-index {
  min-width: 18px;
  text-align: center;
  color: var(--text-secondary);
  font-size: var(--font-md);
}
.shot-thumb {
  position: relative;
  width: 72px;
  height: 42px;
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: #f0f0f0;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid transparent;
  transition:
    transform 0.15s,
    border-color 0.15s,
    box-shadow 0.15s;
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
.thumb-failed {
  position: absolute;
  top: 3px;
  right: 3px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--danger-active);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.35);
}
.line-actions .gen-failed {
  border-color: var(--danger);
  color: var(--danger);
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
  border-radius: var(--radius-sm);
  object-fit: contain;
  border: 1px solid var(--border);
  box-shadow: 0 0 0 2px #fff;
  transition:
    transform 0.15s,
    border-color 0.15s,
    box-shadow 0.15s;
}
.dh-chip:hover {
  position: relative;
  z-index: 2;
  transform: translateY(-3px) scale(1.06);
  border-color: var(--primary);
  box-shadow:
    0 0 0 2px #fff,
    0 5px 12px rgba(255, 90, 44, 0.22);
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
  font-size: var(--font-md);
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
  border-radius: var(--radius-xs);
  background: var(--info-light);
  color: var(--info);
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
.prompt-generation-state .error-text {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.ass-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 3px;
}
.segment-tag {
  padding: 2px 7px;
  border-radius: var(--radius-xs);
  background: #f4ecff;
  color: #7b5ac8;
  font-size: 11px;
  font-weight: 600;
}
.time-range {
  color: var(--text-secondary);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
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
  font-size: var(--font-sm);
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
  border-radius: var(--radius-xs);
  color: var(--primary);
  background: var(--primary-light);
  border: 1px solid rgba(255, 90, 44, 0.35);
  vertical-align: 1px;
}
.prompt {
  margin: 3px 0 0;
  font-size: var(--font-sm);
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
</style>
