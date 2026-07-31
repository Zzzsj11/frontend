<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { formatTime, useProjectStore } from '../stores/project'

const store = useProjectStore()

const previewRef = ref<HTMLDivElement>()
const audioRef = ref<HTMLAudioElement>()
const progressRef = ref<HTMLDivElement>()

const progressPercent = computed(() =>
  store.totalDuration > 0 ? (store.currentTime / store.totalDuration) * 100 : 0,
)

/** 当前应展示的分镜图（视频封面 > 场景底图） */
const currentImage = computed(() => {
  const line = store.currentLine
  return line ? store.coverOf(line) : undefined
})

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
  },
)

// 进度条 seek（点击 + 拖动）
const seekByEvent = (e: MouseEvent) => {
  const el = progressRef.value
  if (!el || store.totalDuration <= 0) return
  const rect = el.getBoundingClientRect()
  const ratio = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1)
  store.seek(ratio * store.totalDuration)
}
const onProgressDown = (e: MouseEvent) => {
  seekByEvent(e)
  const onMove = (ev: MouseEvent) => seekByEvent(ev)
  const onUp = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

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
      <img v-if="currentImage" :src="currentImage" alt="分镜预览" class="preview-img" />
      <p v-else class="preview-placeholder">生成配音和图片后在此查看预览</p>
      <!-- MV 歌词字幕 -->
      <p v-if="store.currentLine?.lyrics" class="preview-lyrics">{{ store.currentLine.lyrics }}</p>
      <audio ref="audioRef" />
    </div>

    <div class="controls">
      <button class="play-btn" :title="store.isPlaying ? '暂停' : '播放'" @click="store.togglePlay()">
        {{ store.isPlaying ? '⏸' : '▶' }}
      </button>
      <span class="time-label">
        {{ formatTime(store.currentTime) }} / {{ formatTime(store.totalDuration) }}
      </span>
      <div ref="progressRef" class="progress-bar" @mousedown="onProgressDown">
        <div class="progress-fill" :style="{ width: progressPercent + '%' }" />
        <div class="progress-thumb" :style="{ left: progressPercent + '%' }" />
      </div>
      <button class="ctrl-icon" :title="store.muted ? '取消静音' : '静音'" @click="store.muted = !store.muted">
        {{ store.muted ? '🔇' : '🔊' }}
      </button>
      <button class="ctrl-icon" title="全屏" @click="toggleFullscreen">⛶</button>
    </div>

    <footer class="player-footer">
      <label class="check-item">
        <input
          type="checkbox"
          :checked="store.playMode.single"
          @change="store.setPlayMode('single', ($event.target as HTMLInputElement).checked)"
        />
        <span class="check-text">
          <strong>单个分镜</strong>
          <small>仅播放当前选中的分镜</small>
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
      <button
        class="btn-outline synth-btn"
        :disabled="!store.hasAssets || store.synthesis.status === 'running'"
        @click="store.runSynthesize()"
      >
        <template v-if="store.synthesis.status === 'running'">
          合成中 {{ store.synthesis.progress }}%
        </template>
        <template v-else-if="store.synthesis.status === 'done'">🎬 合成完成</template>
        <template v-else>🎬 合成视频</template>
      </button>
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
  background: #111;
  border-radius: 10px;
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
  color: #555;
  font-size: 14px;
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
  font-size: 20px;
  cursor: pointer;
  color: var(--text);
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
  border-radius: 2px;
  position: relative;
  cursor: pointer;
}
.progress-fill {
  height: 100%;
  background: var(--primary);
  border-radius: 2px;
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
  font-size: 16px;
  cursor: pointer;
  color: var(--text-secondary);
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
  font-size: 14px;
  color: var(--text);
}
.check-text small {
  font-size: 12px;
  color: var(--text-secondary);
}
.synth-btn {
  margin-left: auto;
}
</style>
