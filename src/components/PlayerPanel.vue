<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { formatTime, useProjectStore } from '../stores/project'
import AppIcon from './AppIcon.vue'

const store = useProjectStore()

const previewRef = ref<HTMLDivElement>()
const audioRef = ref<HTMLAudioElement>()
const videoRef = ref<HTMLVideoElement>()

const progressPercent = computed(() =>
  store.totalDuration > 0 ? (store.currentTime / store.totalDuration) * 100 : 0,
)

/** 当前分镜的真实视频（有则直接播视频） */
const currentVideoUrl = computed(() => {
  const line = store.currentLine
  return line ? store.videoOf(line) : undefined
})

/** 当前应展示的分镜图（视频封面 > 场景底图） */
const currentImage = computed(() => {
  const line = store.currentLine
  return line ? store.coverOf(line) : undefined
})

/** 同步视频元素：播放状态/切片时对齐片段内偏移并播放或暂停 */
const syncVideo = () => {
  const video = videoRef.value
  if (!video) return
  const clip = store.currentClip
  if (clip) {
    const offset = Math.max(0, store.currentTime - clip.start)
    if (Math.abs(video.currentTime - offset) > 0.5) video.currentTime = offset
  }
  video.muted = store.muted
  video.volume = store.volume
  if (store.isPlaying) {
    video.play().catch(() => {})
  } else {
    video.pause()
  }
}

watch(
  () => [store.isPlaying, currentVideoUrl.value] as const,
  () => syncVideo(),
  { flush: 'post' },
)

// 暂停状态下拖动进度/时间轴时，同步视频画面帧
watch(
  () => store.currentTime,
  () => {
    if (!store.isPlaying) syncVideo()
  },
)

/** 当前应播放的配音 —— 行切换/播放状态变化时同步 audio 元素 */
const currentVoiceUrl = computed(() => {
  const line = store.currentLine
  return line?.voice.status === 'done' ? line.voice.url : undefined
})

watch(
  () => [store.isPlaying, currentVoiceUrl.value] as const,
  async ([playing, url]) => {
    const audio = audioRef.value
    if (!audio) return
    if (playing && url) {
      if (audio.src !== url) audio.src = url
      // 对齐到片段内偏移
      const clip = store.currentClip
      if (clip) audio.currentTime = Math.max(0, store.currentTime - clip.start)
      audio.volume = store.muted ? 0 : store.volume
      audio.play().catch(() => {})
    } else {
      audio.pause()
    }
  },
)

watch(
  () => [store.volume, store.muted] as const,
  ([v, m]) => {
    if (audioRef.value) audioRef.value.volume = m ? 0 : v
    if (videoRef.value) {
      videoRef.value.muted = m
      videoRef.value.volume = v
    }
  },
)

// 进度条 seek（点击 + 拖动，普通 / 全屏两条进度条共用，按触发元素自身定位）
const seekByEvent = (e: MouseEvent, el: HTMLElement) => {
  if (store.totalDuration <= 0) return
  const rect = el.getBoundingClientRect()
  const ratio = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1)
  store.seek(ratio * store.totalDuration)
}
const onProgressDown = (e: MouseEvent) => {
  const el = e.currentTarget as HTMLElement
  seekByEvent(e, el)
  const onMove = (ev: MouseEvent) => seekByEvent(ev, el)
  const onUp = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

// 全屏时进度条只对应“当前选中分镜”的局部时间（相对片段 0..duration），且只播放该分镜
const fsClip = computed(() => store.currentClip)
const fsElapsed = computed(() => {
  const clip = fsClip.value
  if (!clip) return 0
  return Math.min(Math.max(store.currentTime - clip.start, 0), clip.duration)
})
const fsProgressPercent = computed(() => {
  const clip = fsClip.value
  return clip && clip.duration > 0 ? (fsElapsed.value / clip.duration) * 100 : 0
})
// 全屏进度条 seek：映射到选中片段内的局部时间
const seekFsByEvent = (e: MouseEvent, el: HTMLElement) => {
  const clip = fsClip.value
  if (!clip) return
  const rect = el.getBoundingClientRect()
  const ratio = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1)
  store.seek(clip.start + ratio * clip.duration)
}
const onFsProgressDown = (e: MouseEvent) => {
  const el = e.currentTarget as HTMLElement
  seekFsByEvent(e, el)
  const onMove = (ev: MouseEvent) => seekFsByEvent(ev, el)
  const onUp = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

// 全屏状态：全屏元素是 .preview，外部控制条不可见，需在画面内叠加悬浮控制条
const isFullscreen = ref(false)
// 记录进入全屏前的“单个分镜”模式，退出时还原
let prevSingle = store.playMode.single
const onFsChange = () => {
  const nowFs = !!document.fullscreenElement
  if (nowFs && !isFullscreen.value) {
    // 进入全屏：强制只播当前选中分镜，并把指针对齐到该片段起点
    prevSingle = store.playMode.single
    if (!store.playMode.single) store.setPlayMode('single', true)
    const clip = store.selectedClip
    if (clip) store.seek(clip.start)
  } else if (!nowFs && isFullscreen.value) {
    // 退出全屏：还原原播放模式
    store.setPlayMode('single', prevSingle)
  }
  isFullscreen.value = nowFs
}
onMounted(() => document.addEventListener('fullscreenchange', onFsChange))
onBeforeUnmount(() => {
  document.removeEventListener('fullscreenchange', onFsChange)
  // 若卸载时仍在全屏，恢复播放模式，避免残留强制单分镜
  if (isFullscreen.value) store.setPlayMode('single', prevSingle)
})

const toggleFullscreen = () => {
  if (document.fullscreenElement) {
    document.exitFullscreen()
  } else {
    previewRef.value?.requestFullscreen()
  }
}
</script>

<template>
  <section class="panel player-panel">
    <header class="panel-header">
      <div class="title-group">
        <h2>播放器</h2>
        <span class="badge-success">已同步</span>
      </div>
    </header>

    <div ref="previewRef" class="preview">
      <video
        v-if="currentVideoUrl"
        ref="videoRef"
        :src="currentVideoUrl"
        class="preview-img"
        playsinline
        @loadeddata="syncVideo"
      />
      <img v-else-if="currentImage" :src="currentImage" alt="视频预览" class="preview-img" />
      <p v-else class="preview-placeholder">生成视频后在此查看预览</p>
      <!-- MV 歌词字幕（非中文歌词附中文翻译） -->
      <div
        v-if="store.currentLine?.lyrics"
        class="preview-lyrics"
        :class="{ 'fs-lift': isFullscreen }"
      >
        <p class="lyric-line">{{ store.currentLine.lyrics }}</p>
        <p v-if="store.translationOf(store.currentLine)" class="lyric-zh">
          {{ store.translationOf(store.currentLine) }}
        </p>
      </div>
      <!-- 全屏时的悬浮控制条 -->
      <div v-if="isFullscreen" class="fs-controls">
        <button
          class="fs-btn"
          :title="store.isPlaying ? '暂停' : '播放'"
          @click="store.togglePlay()"
        >
          <AppIcon :name="store.isPlaying ? 'pause' : 'play'" :size="20" />
        </button>
        <span class="fs-time">
          {{ formatTime(fsElapsed) }} / {{ formatTime(fsClip?.duration ?? 0) }}
        </span>
        <div class="progress-bar fs-progress" @mousedown="onFsProgressDown">
          <div class="progress-fill" :style="{ width: fsProgressPercent + '%' }" />
          <div class="progress-thumb" :style="{ left: fsProgressPercent + '%' }" />
        </div>
        <button
          class="fs-btn"
          :title="store.muted ? '取消静音' : '静音'"
          @click="store.muted = !store.muted"
        >
          <AppIcon :name="store.muted ? 'volume-off' : 'volume-on'" :size="17" />
        </button>
        <button class="fs-btn" title="退出全屏" @click="toggleFullscreen">
          <AppIcon name="fullscreen" :size="17" />
        </button>
      </div>
      <audio ref="audioRef" />
    </div>

    <div class="controls">
      <button
        class="play-btn"
        :title="store.isPlaying ? '暂停' : '播放'"
        @click="store.togglePlay()"
      >
        <AppIcon :name="store.isPlaying ? 'pause' : 'play'" :size="20" />
      </button>
      <span class="time-label">
        {{ formatTime(store.currentTime) }} / {{ formatTime(store.totalDuration) }}
      </span>
      <div class="progress-bar" @mousedown="onProgressDown">
        <div class="progress-fill" :style="{ width: progressPercent + '%' }" />
        <div class="progress-thumb" :style="{ left: progressPercent + '%' }" />
      </div>
      <button
        class="ctrl-icon"
        :title="store.muted ? '取消静音' : '静音'"
        @click="store.muted = !store.muted"
      >
        <AppIcon :name="store.muted ? 'volume-off' : 'volume-on'" :size="17" />
      </button>
      <button class="ctrl-icon" title="全屏" @click="toggleFullscreen">
        <AppIcon name="fullscreen" :size="17" />
      </button>
    </div>

    <footer class="player-footer">
      <label class="check-item">
        <input
          type="checkbox"
          :checked="store.playMode.single"
          @change="store.setPlayMode('single', ($event.target as HTMLInputElement).checked)"
        />
        <span class="check-text">
          <strong>单个视频</strong>
          <small>仅播放当前选中的视频</small>
        </span>
      </label>
      <label class="check-item">
        <input
          type="checkbox"
          :checked="store.playMode.loop"
          @change="store.setPlayMode('loop', ($event.target as HTMLInputElement).checked)"
        />
        <span class="check-text">
          <strong>循环播放</strong>
          <small>到达末尾后自动重新开始</small>
        </span>
      </label>
      <div class="export-group">
        <button
          v-if="['queued', 'running'].includes(store.synthesis.status)"
          class="btn-outline synth-btn"
          disabled
        >
          {{ store.synthesis.stage || '正在导出' }} {{ store.synthesis.progress }}%
        </button>
        <button
          v-else-if="store.synthesis.status === 'failed'"
          class="btn-outline synth-btn"
          @click="store.runSynthesize()"
        >
          <AppIcon name="movie" :size="15" />
          导出失败，重试
        </button>
        <button
          v-else
          class="btn-outline synth-btn"
          :disabled="!store.hasVideoAssets"
          @click="store.runSynthesize()"
        >
          <AppIcon name="movie" :size="15" />
          导出素材
        </button>
        <a
          v-if="store.synthesis.status === 'ready' && store.synthesis.videoUrl"
          class="btn-outline synth-dl"
          :href="store.synthesis.videoUrl"
          download
          title="下载最新导出"
        >
          <AppIcon name="download" :size="15" />
          下载
        </a>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.player-panel {
  display: flex;
  flex-direction: column;
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
.preview {
  flex: 1;
  min-height: 220px;
  background: var(--surface-dark);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  position: relative;
}
.preview-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.preview-placeholder {
  color: var(--text-regular);
  font-size: var(--font-md);
}
.preview-lyrics {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 8px;
  margin: 0;
  padding: 20px 16px 8px;
  text-align: center;
  color: #fff;
  font-size: 15px;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.85);
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.45));
  pointer-events: none;
}
.preview-lyrics .lyric-line {
  margin: 0;
}
/* 非中文歌词的中文翻译 */
.preview-lyrics .lyric-zh {
  margin: 4px 0 0;
  font-size: 13px;
  opacity: 0.85;
}
/* 全屏时字幕上移，避免被底部悬浮控制条遮挡 */
.preview-lyrics.fs-lift {
  bottom: 76px;
}
/* 全屏悬浮控制条 */
.fs-controls {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 24px 20px 16px;
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.7));
  z-index: 2;
}
.fs-btn {
  border: none;
  background: transparent;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: #fff;
  padding: 4px;
}
.fs-btn:hover {
  color: var(--primary);
}
.fs-time {
  font-size: 13px;
  color: #fff;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.fs-progress {
  background: rgba(255, 255, 255, 0.3);
}
.controls {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 2px 12px;
}
.play-btn {
  width: 36px;
  height: 36px;
  border: none;
  background: transparent;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--text);
}
.play-btn:hover {
  color: var(--primary);
}
.time-label {
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.progress-bar {
  flex: 1;
  height: 4px;
  background: #e5e5e5;
  border-radius: var(--radius-xs);
  position: relative;
  cursor: pointer;
}
.progress-fill {
  height: 100%;
  background: var(--primary);
  border-radius: var(--radius-xs);
}
.progress-thumb {
  position: absolute;
  top: 50%;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--primary);
  transform: translate(-50%, -50%);
}
.ctrl-icon {
  border: none;
  background: transparent;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--text-secondary);
}
.ctrl-icon:hover {
  color: var(--text);
}
.player-footer {
  display: flex;
  align-items: center;
  gap: 24px;
  border-top: 1px solid var(--border);
  padding-top: 12px;
}
.check-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  cursor: pointer;
}
.check-item input {
  margin-top: 3px;
  accent-color: var(--primary);
  width: 16px;
  height: 16px;
}
.check-text {
  display: flex;
  flex-direction: column;
}
.check-text strong {
  font-size: var(--font-md);
  color: var(--text);
}
.check-text small {
  font-size: var(--font-sm);
  color: var(--text-secondary);
}
.synth-btn {
  margin-left: auto;
}
.export-group {
  display: flex;
  gap: 8px;
  margin-left: auto;
}
.synth-dl {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 13px;
  border: 1px solid var(--primary);
  border-radius: var(--radius-sm);
  background: var(--primary-light);
  color: var(--primary);
  font-size: var(--font-sm);
  font-weight: 600;
  cursor: pointer;
  text-decoration: none;
  font-family: inherit;
}
.synth-dl:hover {
  background: rgba(255, 90, 44, 0.14);
}
</style>
