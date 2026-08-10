<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useProjectStore } from '../stores/project'
import ScriptLineItem from './ScriptLine.vue'
import ShotDetailModal from './ShotDetailModal.vue'
import MagicScriptModal from './MagicScriptModal.vue'
import GeneralStoryboardModal from './GeneralStoryboardModal.vue'
import AppIcon from './AppIcon.vue'
import StoryboardOutlineModal from './StoryboardOutlineModal.vue'

const store = useProjectStore()
const lineListRef = ref<HTMLDivElement>()

/** 时间线或其他入口选中不可见分镜时，将对应卡片平滑滚动到列表中央 */
watch(
  () => store.selectedLineId,
  async (lineId) => {
    if (!lineId) return
    await nextTick()
    const list = lineListRef.value
    const item = list?.querySelector<HTMLElement>(`[data-line-id="${lineId}"]`)
    if (!list || !item) return
    const listRect = list.getBoundingClientRect()
    const itemRect = item.getBoundingClientRect()
    const outsideView = itemRect.top < listRect.top || itemRect.bottom > listRect.bottom
    if (!outsideView) return
    list.scrollTo({
      top: list.scrollTop + itemRect.top - listRect.top - (list.clientHeight - itemRect.height) / 2,
      behavior: 'smooth',
    })
  },
)

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
        <h2>视频编辑器</h2>
        <span v-if="store.storyboardProgress.total" class="generation-progress">
          已生成 {{ store.storyboardProgress.completed }}/{{ store.storyboardProgress.total }}
          <button v-if="store.storyboardProgress.failed" class="retry-all" @click="store.retryFailedStoryboardLines()">
            {{ store.storyboardProgress.failed }} 条失败，重试
          </button>
        </span>
      </div>
      <div class="header-actions">
        <button class="btn-outline" @click="store.openLibrary()">
          <AppIcon name="users" :size="15" />
          角色阵容
          <span v-if="store.castHumans.length" class="cast-count">{{ store.castHumans.length }}</span>
        </button>
        <button class="btn-outline" :disabled="!store.activeStoryBible" @click="store.openOutline()">
          <AppIcon name="file" :size="13" />
          查看大纲
        </button>
        <button class="btn-primary" :disabled="store.magicLoading || store.songSwitching" @click="store.openMagic()">
          <span v-if="store.magicLoading" class="spinner light" />
          <AppIcon v-else name="sparkles" :size="15" />
          ASS 视频
        </button>
        <button
          class="btn-primary"
          :disabled="store.generalStoryboardLoading || store.songSwitching"
          @click="store.openGeneralStoryboard()"
        >
          <span v-if="store.generalStoryboardLoading" class="spinner light" />
          <AppIcon v-else name="movie" :size="15" />
          通用 MV 视频
        </button>
      </div>
    </header>

    <div ref="lineListRef" class="line-list">
      <div
        v-for="(line, index) in store.lines"
        :key="line.id"
        class="line-wrapper"
        :data-line-id="line.id"
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
        暂无视频，您可以点击下方【单个视频】按钮或顶部「ASS 视频」/【通用 MV 视频】开始创作
      </p>
    </div>

    <footer class="editor-footer">
      <button class="btn-add" @click="store.addLine()">
        <AppIcon name="plus" :size="14" />
        单个视频
      </button>
    </footer>

    <ShotDetailModal />
    <MagicScriptModal />
    <GeneralStoryboardModal />
    <StoryboardOutlineModal />
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
.generation-progress { margin-left: 10px; color: var(--text-muted); font-size: 12px; }
.retry-all { border: 0; background: transparent; color: var(--primary); cursor: pointer; padding: 0 4px; }
.title-group {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.header-actions {
  display: flex;
  gap: 6px;
}
.header-actions button {
  min-height: 30px;
  padding: 5px 11px;
  border-radius: 9px;
  font-size: 12px;
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
  height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 14px;
  padding-right: 4px;
  min-height: 0;
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
  display: inline-flex;
  align-items: center;
  gap: 6px;
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
