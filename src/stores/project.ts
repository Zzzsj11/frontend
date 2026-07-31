import { defineStore } from 'pinia'
import type { DigitalHuman, ScriptLine, ShotAsset, SynthesisState, TimelineClip } from '../types'
import * as api from '../mock/api'
import { initialLines, mockDigitalHumans, nextId } from '../mock/data'

/** 无配音时的占位时长（秒） */
export const DEFAULT_CLIP_DURATION = 5

let rafId = 0
let lastTick = 0
/** 每行场景图重新生成次数（仅用于 mock 占位图换款） */
const sceneVariants: Record<string, number> = {}

export const useProjectStore = defineStore('project', {
  state: () => ({
    lines: initialLines as ScriptLine[],
    digitalHumans: mockDigitalHumans,
    /** 全局角色阵容：本 MV 选定的数字人（全片统一），分镜只能从阵容中挑选出演角色 */
    castIds: ['dh-xiner'] as string[],
    selectedLineId: initialLines[0]?.id ?? null as string | null,
    /** 当前在弹窗中编辑的分镜行 */
    editingLineId: null as string | null,
    /** 资产库（角色阵容管理）弹窗开关 */
    libraryOpen: false,
    currentTime: 0,
    isPlaying: false,
    playMode: { single: true, loop: false },
    volume: 1,
    muted: false,
    batchVoicing: false,
    batchShooting: false,
    magicLoading: false,
    synthesis: { status: 'idle', progress: 0 } as SynthesisState,
  }),

  getters: {
    /** 每行的时长：配音 > 分镜视频片段 > 占位时长 */
    lineDuration: () => (line: ScriptLine) => {
      const asset = line.shot.assets.find((a) => a.id === line.shot.currentAssetId)
      return line.voice.duration ?? asset?.duration ?? DEFAULT_CLIP_DURATION
    },

    /** 时间轴片段（分镜/配音两轨共用同一时间划分） */
    timelineClips(state): TimelineClip[] {
      let start = 0
      return state.lines.map((line, index) => {
        const asset = line.shot.assets.find((a) => a.id === line.shot.currentAssetId)
        const duration = line.voice.duration ?? asset?.duration ?? DEFAULT_CLIP_DURATION
        const clip: TimelineClip = { lineId: line.id, index, start, duration }
        start += duration
        return clip
      })
    },

    totalDuration(): number {
      return this.timelineClips.reduce((sum: number, c: TimelineClip) => sum + c.duration, 0)
    },

    selectedLine(state): ScriptLine | undefined {
      return state.lines.find((l) => l.id === state.selectedLineId)
    },

    selectedClip(): TimelineClip | undefined {
      return this.timelineClips.find((c: TimelineClip) => c.lineId === this.selectedLineId)
    },

    /** 当前播放时间对应的片段 */
    currentClip(state): TimelineClip | undefined {
      const clips: TimelineClip[] = this.timelineClips
      return (
        clips.find((c) => state.currentTime >= c.start && state.currentTime < c.start + c.duration) ??
        clips[clips.length - 1]
      )
    },

    currentLine(): ScriptLine | undefined {
      const clip: TimelineClip | undefined = this.currentClip
      return clip ? this.lines.find((l) => l.id === clip.lineId) : undefined
    },

    editingLine(state): ScriptLine | undefined {
      return state.lines.find((l) => l.id === state.editingLineId)
    },

    digitalHumanOf: (state) => (id?: string) =>
      state.digitalHumans.find((d) => d.id === id),

    /** 全局角色阵容对应的数字人列表 */
    castHumans(state): DigitalHuman[] {
      return state.castIds
        .map((id) => state.digitalHumans.find((d) => d.id === id))
        .filter((d): d is DigitalHuman => !!d)
    },

    /** 某分镜的出演角色列表 */
    lineHumans: (state) => (line: ScriptLine): DigitalHuman[] =>
      line.digitalHumanIds
        .map((id) => state.digitalHumans.find((d) => d.id === id))
        .filter((d): d is DigitalHuman => !!d),

    /** 分镜展示图：优先视频片段封面，其次场景底图 */
    coverOf: () => (line: ScriptLine): string | undefined =>
      line.shot.imageUrl ?? line.scene.imageUrl,

    /** 是否有任何配音或分镜素材（决定合成按钮可用性） */
    hasAssets(state): boolean {
      return state.lines.some((l) => l.voice.status === 'done' || l.shot.status === 'done')
    },

    /** 播放范围（单个分镜模式只播选中片段） */
    playRange(): { start: number; end: number } {
      if (this.playMode.single && this.selectedClip) {
        const c: TimelineClip = this.selectedClip
        return { start: c.start, end: c.start + c.duration }
      }
      return { start: 0, end: this.totalDuration }
    },
  },

  actions: {
    // ---------- 分镜行编辑 ----------
    addLine() {
      const line: ScriptLine = {
        id: nextId(),
        lyrics: '',
        scenePrompt: '',
        shotPrompt: '',
        digitalHumanIds: [],
        voice: { status: 'none' },
        scene: { status: 'none' },
        shot: { status: 'none', assets: [] },
      }
      this.lines.push(line)
      this.selectedLineId = line.id
    },

    removeLine(lineId: string) {
      const idx = this.lines.findIndex((l) => l.id === lineId)
      if (idx < 0) return
      this.lines.splice(idx, 1)
      if (this.selectedLineId === lineId) {
        this.selectedLineId = this.lines[Math.min(idx, this.lines.length - 1)]?.id ?? null
      }
      this.clampCurrentTime()
    },

    updateLyrics(lineId: string, lyrics: string) {
      const line = this.lines.find((l) => l.id === lineId)
      if (line) line.lyrics = lyrics
    },

    updateScenePrompt(lineId: string, scenePrompt: string) {
      const line = this.lines.find((l) => l.id === lineId)
      if (line) line.scenePrompt = scenePrompt
    },

    updateShotPrompt(lineId: string, shotPrompt: string) {
      const line = this.lines.find((l) => l.id === lineId)
      if (line) line.shotPrompt = shotPrompt
    },

    /** 切换某分镜的出演角色（只能选全局阵容内的数字人，可多选/可全不选） */
    toggleLineHuman(lineId: string, digitalHumanId: string) {
      const line = this.lines.find((l) => l.id === lineId)
      if (!line || !this.castIds.includes(digitalHumanId)) return
      const idx = line.digitalHumanIds.indexOf(digitalHumanId)
      idx >= 0 ? line.digitalHumanIds.splice(idx, 1) : line.digitalHumanIds.push(digitalHumanId)
    },

    moveLine(fromIndex: number, toIndex: number) {
      if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) return
      const [moved] = this.lines.splice(fromIndex, 1)
      this.lines.splice(toIndex, 0, moved)
    },

    selectLine(lineId: string) {
      this.selectedLineId = lineId
      // 单个分镜模式下，选中后把指针移到片段起点
      const clip = this.timelineClips.find((c) => c.lineId === lineId)
      if (clip && this.playMode.single) this.seek(clip.start)
    },

    openEditor(lineId: string) {
      this.selectLine(lineId)
      this.editingLineId = lineId
    },

    closeEditor() {
      this.editingLineId = null
    },

    // ---------- 资产库 / 全局角色阵容 ----------
    openLibrary() {
      this.libraryOpen = true
    },

    closeLibrary() {
      this.libraryOpen = false
    },

    /** 加入/移出全局角色阵容；移出时同步从所有分镜的出演角色中移除，保证全局统一 */
    toggleCast(digitalHumanId: string) {
      const idx = this.castIds.indexOf(digitalHumanId)
      if (idx >= 0) {
        this.castIds.splice(idx, 1)
        this.lines.forEach((l) => {
          const i = l.digitalHumanIds.indexOf(digitalHumanId)
          if (i >= 0) l.digitalHumanIds.splice(i, 1)
        })
      } else {
        this.castIds.push(digitalHumanId)
      }
    },

    // ---------- Mock API 联动 ----------
    async runMagicScript() {
      if (this.magicLoading) return
      this.magicLoading = true
      try {
        const script = await api.generateMagicScript()
        this.stop()
        // 脚本自带统一的角色阵容，整体替换当前阵容
        this.castIds = [...script.cast]
        this.lines = script.lines.map((item) => ({
          id: nextId(),
          lyrics: item.lyrics,
          scenePrompt: item.scenePrompt,
          shotPrompt: item.shotPrompt,
          digitalHumanIds: [...item.digitalHumanIds],
          voice: { status: 'none' },
          scene: { status: 'none' },
          shot: { status: 'none', assets: [] },
        }))
        this.selectedLineId = this.lines[0]?.id ?? null
        this.currentTime = 0
      } finally {
        this.magicLoading = false
      }
    },

    async generateVoiceFor(lineId: string) {
      const line = this.lines.find((l) => l.id === lineId)
      if (!line || line.voice.status === 'generating') return
      line.voice.status = 'generating'
      const { url, duration } = await api.generateVoice(lineId)
      // 生成期间行可能被删除
      const still = this.lines.find((l) => l.id === lineId)
      if (still) still.voice = { status: 'done', url, duration }
    },

    /** 生成/重新生成场景底图（仅由场景提示词决定） */
    async generateSceneFor(lineId: string, scenePrompt?: string) {
      const idx = this.lines.findIndex((l) => l.id === lineId)
      if (idx < 0 || this.lines[idx].scene.status === 'generating') return
      const line = this.lines[idx]
      if (scenePrompt !== undefined) line.scenePrompt = scenePrompt
      line.scene.status = 'generating'
      const variant = sceneVariants[lineId] ?? 0
      sceneVariants[lineId] = variant + 1
      const { imageUrl } = await api.generateSceneImage(line.scenePrompt, idx, variant)
      const still = this.lines.find((l) => l.id === lineId)
      if (still) still.scene = { status: 'done', imageUrl }
    },

    /** 生成/重新生成分镜视频片段（场景 × 分镜提示词 × 出演角色）；新片段作为资产追加并选中 */
    async generateShotFor(lineId: string, shotPrompt?: string) {
      const idx = this.lines.findIndex((l) => l.id === lineId)
      if (idx < 0 || this.lines[idx].shot.status === 'generating') return
      const line = this.lines[idx]
      if (shotPrompt !== undefined) line.shotPrompt = shotPrompt
      line.shot.status = 'generating'
      const variant = line.shot.assets.length
      const { coverUrl, videoUrl, duration } = await api.generateShotVideo(
        line.scenePrompt,
        line.shotPrompt,
        line.digitalHumanIds,
        idx,
        variant,
      )
      const still = this.lines.find((l) => l.id === lineId)
      if (still) {
        const asset: ShotAsset = {
          id: nextId('asset'),
          coverUrl,
          videoUrl,
          duration,
          digitalHumanIds: [...line.digitalHumanIds],
        }
        still.shot.assets.push(asset)
        still.shot.currentAssetId = asset.id
        still.shot.imageUrl = coverUrl
        still.shot.status = 'done'
      }
    },

    /** 从资产历史中选用某个视频片段 */
    selectShotAsset(lineId: string, assetId: string) {
      const line = this.lines.find((l) => l.id === lineId)
      const asset = line?.shot.assets.find((a) => a.id === assetId)
      if (line && asset) {
        line.shot.currentAssetId = asset.id
        line.shot.imageUrl = asset.coverUrl
      }
    },

    async generateAllVoices() {
      if (this.batchVoicing) return
      this.batchVoicing = true
      try {
        for (const line of [...this.lines]) {
          if (line.voice.status !== 'done') await this.generateVoiceFor(line.id)
        }
      } finally {
        this.batchVoicing = false
      }
    },

    async generateAllShots() {
      if (this.batchShooting) return
      this.batchShooting = true
      try {
        for (const line of [...this.lines]) {
          if (line.shot.status !== 'done') await this.generateShotFor(line.id)
        }
      } finally {
        this.batchShooting = false
      }
    },

    async runSynthesize() {
      if (this.synthesis.status === 'running' || !this.hasAssets) return
      this.synthesis = { status: 'running', progress: 0 }
      const { videoUrl } = await api.synthesizeVideo((p) => {
        this.synthesis.progress = p
      })
      this.synthesis = { status: 'done', progress: 100, videoUrl }
    },

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

    clampCurrentTime() {
      if (this.currentTime > this.totalDuration) this.currentTime = this.totalDuration
    },

    setPlayMode(key: 'single' | 'loop', value: boolean) {
      this.playMode[key] = value
    },
  },
})

/** mm:ss 格式化 */
export const formatTime = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds))
  const mm = String(Math.floor(s / 60)).padStart(2, '0')
  const ss = String(s % 60).padStart(2, '0')
  return `${mm}:${ss}`
}
