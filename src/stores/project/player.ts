import * as api from '../../api/domain'
import type { ProjectContext } from './contracts'

let rafId = 0

let lastTick = 0

/** 当前播放中的视频元素（PlayerPanel 登记）；播放中主时钟以其 currentTime 回写，保证画面/游标一致 */
let activeVideoEl: HTMLVideoElement | null = null
export const playerActions = {
  // ---------- 播放控制 ----------
  play() {
    if (this.isPlaying || this.totalDuration <= 0) return
    const { start, end } = this.playRange
    if (this.currentTime < start || this.currentTime >= end - 0.01) {
      this.currentTime = start
    }
    this.isPlaying = true
    lastTick = performance.now()
    const tick = (now: number) => {
      if (!this.isPlaying) return
      const dt = (now - lastTick) / 1000
      lastTick = now
      let t = this.currentTime + dt
      // 主时钟：当前片段有在播视频时以其真实进度为准，消除估算漂移；拖动中不回写（以用户拖动位置为准）
      const clip = this.currentClip
      if (
        !this.scrubbing &&
        clip &&
        activeVideoEl &&
        activeVideoEl.readyState >= 2 &&
        !activeVideoEl.paused
      ) {
        t = clip.start + activeVideoEl.currentTime
      }
      const range = this.playRange
      if (t >= range.end) {
        if (this.playMode.loop) {
          t = range.start
        } else {
          this.currentTime = range.end
          this.pause()
          return
        }
      }
      this.currentTime = t
      rafId = requestAnimationFrame(tick)
    }
    rafId = requestAnimationFrame(tick)
  },

  pause() {
    this.isPlaying = false
    cancelAnimationFrame(rafId)
  },

  togglePlay() {
    this.isPlaying ? this.pause() : this.play()
  },

  stop() {
    this.pause()
    this.currentTime = 0
  },

  seek(time: number) {
    this.currentTime = Math.min(Math.max(time, 0), this.totalDuration)
  },

  /** PlayerPanel 挂载/卸载视频元素时登记：播放中主时钟以视频真实进度为准 */
  registerVideoEl(el: HTMLVideoElement | null) {
    activeVideoEl = el
  },

  setAudioTrackVisible(visible: boolean) {
    this.audioTrackVisible = visible
    void this.persistAudioTrackConfig()
  },

  setAudioOffset(seconds: number) {
    const duration = this.projectAudio?.duration ?? 0
    const minimum = duration > 0 ? -duration + 0.5 : 0
    const maximum = this.totalDuration > 0 ? this.totalDuration - 0.5 : 0
    this.audioOffsetSeconds = Math.round(Math.min(Math.max(seconds, minimum), maximum) * 10) / 10
  },

  async persistAudioTrackConfig() {
    if (!this.activeTaskId) return
    this.activeStoryboardConfig = {
      ...this.activeStoryboardConfig,
      audioTrackVisible: this.audioTrackVisible,
      audioOffsetSeconds: this.audioOffsetSeconds,
    }
    await api.updateTask(this.activeTaskId, {
      storyboard_config: this.activeStoryboardConfig,
    })
  },

  clampCurrentTime() {
    if (this.currentTime > this.totalDuration) this.currentTime = this.totalDuration
  },

  setPlayMode(key: 'single' | 'loop', value: boolean) {
    this.playMode[key] = value
  },
} satisfies ThisType<ProjectContext>
