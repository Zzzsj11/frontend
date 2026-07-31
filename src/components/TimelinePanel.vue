<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { formatTime, useProjectStore } from '../stores/project'
import AppIcon from './AppIcon.vue'

const store = useProjectStore()

/** 最大 像素/秒 缩放比例；实际比例自适应容器宽度，保证全部片段无需横向滚动 */
const PX_MAX = 60
const trackAreaRef = ref<HTMLDivElement>()
const areaWidth = ref(0)

let resizeObserver: ResizeObserver | undefined
onMounted(() => {
  const el = trackAreaRef.value
  if (!el) return
  areaWidth.value = el.clientWidth
  resizeObserver = new ResizeObserver(() => {
    areaWidth.value = el.clientWidth
  })
  resizeObserver.observe(el)
})
onBeforeUnmount(() => resizeObserver?.disconnect())

/** 自适应 像素/秒：总时长超出可视宽度时整体缩小铺满 */
const pxPerSec = computed(() => {
  if (store.totalDuration <= 0 || areaWidth.value <= 0) return PX_MAX
  return Math.min(PX_MAX, (areaWidth.value - 2) / store.totalDuration)
})

const playheadX = computed(() => store.currentTime * pxPerSec.value)
const totalWidth = computed(() => Math.max(store.totalDuration * pxPerSec.value, 200))

/** 时间刻度（每 5 秒一格） */
const ticks = computed(() => {
  const list: Array<{ time: number; x: number }> = []
  for (let t = 5; t <= store.totalDuration + 0.001; t += 5) {
    list.push({ time: t, x: t * pxPerSec.value })
  }
  // 总时长刻度（非 5 的倍数时）
  if (store.totalDuration > 0 && store.totalDuration % 5 !== 0) {
    list.push({ time: store.totalDuration, x: store.totalDuration * pxPerSec.value })
  }
  return list
})

const seekByEvent = (e: MouseEvent) => {
  const el = trackAreaRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const x = e.clientX - rect.left + el.scrollLeft
  store.seek(x / pxPerSec.value)
}

const onAreaDown = (e: MouseEvent) => {
  seekByEvent(e)
  const onMove = (ev: MouseEvent) => seekByEvent(ev)
  const onUp = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

const onClipClick = (lineId: string, e: MouseEvent) => {
  e.stopPropagation()
  store.selectLine(lineId)
}

const lineOf = (lineId: string) => store.lines.find((l) => l.id === lineId)
</script>

<template>
  <section class="panel timeline-panel">
    <header class="panel-header">
      <div class="title-group">
        <h2>分镜时间轴</h2>
        <span class="badge-success">已同步</span>
      </div>
    </header>

    <div class="timeline-body">
      <!-- 左侧轨道标签 -->
      <div class="track-labels">
        <div class="track-label-spacer" />
        <div class="track-label">
          <span class="track-icon"><AppIcon name="movie" :size="15" /></span>
          <span>分镜轨道</span>
        </div>
      </div>

      <!-- 右侧轨道区域 -->
      <div ref="trackAreaRef" class="track-area" @mousedown="onAreaDown">
        <div class="track-content" :style="{ width: totalWidth + 'px' }">
          <!-- 时间刻度 -->
          <div class="ruler">
            <span
              v-for="tick in ticks"
              :key="tick.time"
              class="tick"
              :class="{ 'tick-end': tick.x > totalWidth - 20 }"
              :style="{ left: tick.x + 'px' }"
            >
              {{ formatTime(tick.time) }}
            </span>
          </div>

          <!-- 分镜轨道 -->
          <div class="track">
            <div
              v-for="clip in store.timelineClips"
              :key="'shot-' + clip.lineId"
              class="clip shot-clip"
              :class="{ selected: clip.lineId === store.selectedLineId }"
              :style="{ left: clip.start * pxPerSec + 'px', width: clip.duration * pxPerSec - 4 + 'px' }"
              @mousedown.stop
              @click="onClipClick(clip.lineId, $event)"
            >
              <video
                v-if="lineOf(clip.lineId) && store.videoOf(lineOf(clip.lineId)!)"
                :src="store.videoOf(lineOf(clip.lineId)!)"
                class="clip-thumb"
                preload="metadata"
                muted
              />
              <img
                v-else-if="lineOf(clip.lineId) && store.coverOf(lineOf(clip.lineId)!)"
                :src="store.coverOf(lineOf(clip.lineId)!)"
                class="clip-thumb"
                alt=""
              />
              <span v-else class="clip-icon"><AppIcon name="image" :size="16" /></span>
              <span class="clip-index">{{ String(clip.index + 1).padStart(2, '0') }}</span>
            </div>
          </div>

          <!-- 播放指针 -->
          <div class="playhead" :style="{ left: playheadX + 'px' }">
            <span class="playhead-label">{{ formatTime(store.currentTime) }}</span>
            <div class="playhead-line" />
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.timeline-panel {
  min-height: 0;
}
.panel-header {
  margin-bottom: 12px;
}
.title-group {
  display: flex;
  align-items: center;
  gap: 10px;
}
.timeline-body {
  display: flex;
  gap: 10px;
}
.track-labels {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}
.track-label-spacer {
  height: 28px;
}
.track-label {
  width: 110px;
  height: 68px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text);
}
.track-icon {
  display: inline-flex;
  color: var(--primary);
}
.track-area {
  flex: 1;
  overflow-x: auto;
  overflow-y: hidden;
  cursor: pointer;
  user-select: none;
}
.track-content {
  position: relative;
  min-width: 100%;
}
.ruler {
  position: relative;
  height: 28px;
}
.tick {
  position: absolute;
  top: 6px;
  transform: translateX(-50%);
  font-size: 11px;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}
/* 末尾刻度左对齐，避免标签文字撑出容器导致横向滚动 */
.tick-end {
  transform: translateX(-100%);
}
.track {
  position: relative;
  height: 68px;
  margin-bottom: 8px;
}
.clip {
  position: absolute;
  top: 0;
  height: 100%;
  border: 1px solid var(--border-dark);
  border-radius: 10px;
  background: #fafafa;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.clip.selected {
  border-color: var(--primary);
  box-shadow: 0 0 0 1px var(--primary);
}
.clip-thumb {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  opacity: 0.85;
}
.clip-icon {
  display: inline-flex;
  color: var(--text-secondary);
  z-index: 1;
}
.clip-index {
  font-size: 11px;
  color: var(--text-secondary);
  z-index: 1;
}
.shot-clip .clip-thumb + .clip-index,
.shot-clip .clip-thumb ~ .clip-index {
  color: #fff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
}
.playhead {
  position: absolute;
  top: 0;
  bottom: 0;
  z-index: 5;
  pointer-events: none;
  transform: translateX(-50%);
}
.playhead-label {
  position: absolute;
  top: 0;
  left: 50%;
  transform: translateX(-50%);
  background: var(--primary);
  color: #fff;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.playhead-line {
  position: absolute;
  top: 22px;
  bottom: 0;
  left: 50%;
  width: 2px;
  transform: translateX(-50%);
  background: var(--primary);
}
</style>
