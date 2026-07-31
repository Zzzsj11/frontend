import { defineStore } from 'pinia'
import type { DigitalHuman, ScriptLine, ShotAsset, ShotGenOptions, SongProject, SynthesisState, TimelineClip } from '../types'
import * as api from '../mock/api'
import * as imageGen from '../api/imageGen'
import { initialCastIds, initialLines, mockDigitalHumans, nextId } from '../mock/data'

/** 无配音时的占位时长（秒） */
export const DEFAULT_CLIP_DURATION = 5

/** 分镜视频生成参数默认值（清晰度 / 时长 / 画幅） */
export const DEFAULT_SHOT_OPTIONS: ShotGenOptions = { resolution: '1080p', duration: 5, ratio: '16:9' }

let rafId = 0
let lastTick = 0
/** 每行场景图重新生成次数（仅用于 mock 占位图换款） */
const sceneVariants: Record<string, number> = {}

/** 数字人资产库本地持久化 key */
const DH_STORAGE_KEY = 'mv-digital-humans'

/** 从 localStorage 恢复数字人资产库（新增/编辑/删除刷新后不丢），无存档时用初始数据 */
function loadDigitalHumans(): DigitalHuman[] {
  try {
    const raw = localStorage.getItem(DH_STORAGE_KEY)
    if (raw) {
      const list = JSON.parse(raw) as DigitalHuman[]
      if (Array.isArray(list) && list.length) {
        return list.map((d) => ({
          ...d,
          avatarPrompt: d.avatarPrompt ?? imageGen.buildPortraitPrompt(d.description, d.style),
        }))
      }
    }
  } catch {
    /* 存档损坏时回退初始数据 */
  }
  return mockDigitalHumans.map((d) => ({ ...d }))
}

export const useProjectStore = defineStore('project', {
  state: () => ({
    lines: initialLines as ScriptLine[],
    digitalHumans: loadDigitalHumans(),
    /** 歌曲项目列表（左侧任务栏：一个目录处理一首歌曲） */
    songProjects: [] as SongProject[],
    /** 当前打开的歌曲项目 id */
    activeSongId: 'song-nunan',
    /** 当前选中的处理任务 id */
    activeTaskId: 'task-nunan-1' as string | null,
    /** 正在切换歌曲（载入脚本中） */
    songSwitching: false,
    /** 已打开过的歌曲编辑现场缓存，切回时不丢编辑状态 */
    songCache: {} as Record<string, { cast: string[]; lines: ScriptLine[] }>,
    /** 全局角色阵容：本 MV 选定的数字人（全片统一），分镜只能从阵容中挑选出演角色 */
    castIds: [...initialCastIds] as string[],
    selectedLineId: initialLines[0]?.id ?? null as string | null,
    /** 当前在弹窗中编辑的分镜行 */
    editingLineId: null as string | null,
    /** 资产库（角色阵容管理）弹窗开关 */
    libraryOpen: false,
    /** AI 魔法脚本弹窗开关 */
    magicOpen: false,
    currentTime: 0,
    isPlaying: false,
    playMode: { single: true, loop: false },
    volume: 1,
    muted: false,
    batchVoicing: false,
    batchShooting: false,
    magicLoading: false,
    /** 正在调用真实生图接口生成数字人形象 */
    dhGenerating: false,
    /** 编辑弹窗中正在重新生成形象的数字人 id（null 表示空闲） */
    dhRegeneratingId: null as string | null,
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

    /** 当前选用资产的真实可播放视频地址（mock:// 假地址除外） */
    videoOf: () => (line: ScriptLine): string | undefined => {
      const asset = line.shot.assets.find((a) => a.id === line.shot.currentAssetId)
      return asset && /^(\/|https?:)/.test(asset.videoUrl) ? asset.videoUrl : undefined
    },

    /** 歌词的中文翻译：仅当歌词非中文（不含汉字）且存在译文时展示 */
    translationOf: () => (line: ScriptLine): string | undefined => {
      if (!line.lyrics || /[\u4e00-\u9fff]/.test(line.lyrics)) return undefined
      return line.lyricsZh?.trim() || undefined
    },

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
    /** 载入歌曲项目列表（侧边栏挂载时调用） */
    async loadSongProjects() {
      this.songProjects = await api.fetchSongProjects()
    },

    /** 新建歌曲项目并加入列表 */
    async createSongProject(name: string): Promise<SongProject> {
      const song = await api.createSongProject(name)
      this.songProjects.push(song)
      return song
    },

    /** 切换到某歌曲的处理任务：载入对应分镜脚本与阵容，当前编辑现场写入缓存 */
    async selectSongTask(songId: string, taskId: string | null = null) {
      if (this.songSwitching) return
      if (songId === this.activeSongId) {
        if (taskId) this.activeTaskId = taskId
        return
      }
      this.songSwitching = true
      try {
        this.songCache[this.activeSongId] = { cast: this.castIds, lines: this.lines }
        const script = this.songCache[songId] ?? (await api.fetchSongScript(songId))
        this.stop()
        this.editingLineId = null
        this.castIds = [...script.cast]
        this.lines = script.lines
        this.songCache[songId] = script
        this.activeSongId = songId
        this.activeTaskId = taskId
        this.selectedLineId = this.lines[0]?.id ?? null
        this.currentTime = 0
      } finally {
        this.songSwitching = false
      }
    },

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

    /** 更新分镜视频生成参数（清晰度 / 时长 / 画幅） */
    updateShotOptions(lineId: string, options: ShotGenOptions) {
      const line = this.lines.find((l) => l.id === lineId)
      if (line) line.shotOptions = { ...options }
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

    /** 调用真实异步生图接口生成数字人形象，图片本地化存储后加入资产库 */
    async generateDigitalHuman(input: { name: string; style: string; description: string }): Promise<DigitalHuman> {
      this.dhGenerating = true
      try {
        const prompt = imageGen.buildPortraitPrompt(input.description, input.style)
        const id = nextId('dh')
        const remoteUrl = await imageGen.generateImage(prompt, { size: '768x1024', quality: 'medium' })
        const avatar = await imageGen.localizeImage(id, remoteUrl)
        const dh: DigitalHuman = {
          id,
          name: input.name,
          style: input.style,
          avatar,
          description: input.description,
          avatarPrompt: prompt,
        }
        this.digitalHumans.push(dh)
        this.persistDigitalHumans()
        return dh
      } finally {
        this.dhGenerating = false
      }
    },

    /** 数字人资产库写入 localStorage（头像已是本地路径，体积很小） */
    persistDigitalHumans() {
      try {
        localStorage.setItem(DH_STORAGE_KEY, JSON.stringify(this.digitalHumans))
      } catch {
        /* 存储超限时忽略，不影响当前会话使用 */
      }
    },

    /** 编辑数字人基础信息 / 提示词 */
    updateDigitalHuman(
      id: string,
      patch: Partial<Pick<DigitalHuman, 'name' | 'style' | 'description' | 'avatarPrompt'>>,
    ) {
      const dh = this.digitalHumans.find((d) => d.id === id)
      if (!dh) return
      Object.assign(dh, patch)
      this.persistDigitalHumans()
    },

    /** 删除数字人：同步从全局阵容与所有分镜出演角色中移除 */
    deleteDigitalHuman(id: string) {
      const idx = this.digitalHumans.findIndex((d) => d.id === id)
      if (idx < 0) return
      this.digitalHumans.splice(idx, 1)
      const c = this.castIds.indexOf(id)
      if (c >= 0) this.castIds.splice(c, 1)
      this.lines.forEach((l) => {
        const i = l.digitalHumanIds.indexOf(id)
        if (i >= 0) l.digitalHumanIds.splice(i, 1)
      })
      this.persistDigitalHumans()
    },

    /** 用（可能已修改的）提示词重新生成数字人形象，成功后本地化存储并替换头像 */
    async regenerateDigitalHumanAvatar(id: string, prompt?: string): Promise<void> {
      const dh = this.digitalHumans.find((d) => d.id === id)
      if (!dh || this.dhRegeneratingId) return
      this.dhRegeneratingId = id
      try {
        const finalPrompt = (prompt ?? dh.avatarPrompt ?? imageGen.buildPortraitPrompt(dh.description, dh.style)).trim()
        const remoteUrl = await imageGen.generateImage(finalPrompt, { size: '768x1024', quality: 'medium' })
        dh.avatar = await imageGen.localizeImage(dh.id, remoteUrl)
        dh.avatarPrompt = finalPrompt
        this.persistDigitalHumans()
      } finally {
        this.dhRegeneratingId = null
      }
    },

    // ---------- Mock API 联动 ----------
    openMagic() {
      this.magicOpen = true
    },
    closeMagic() {
      this.magicOpen = false
    },

    /** 提交魔法脚本表单，生成成功后替换当前脚本与角色阵容 */
    async runMagicScript(req?: api.MagicScriptRequest) {
      if (this.magicLoading) return
      this.magicLoading = true
      try {
        const script = await api.generateMagicScript(req)
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
        this.magicOpen = false
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

    /** 生成/重新生成分镜视频片段（场景 × 分镜提示词 × 出演角色 × 生成参数）；新片段作为资产追加并选中 */
    async generateShotFor(lineId: string, shotPrompt?: string, options?: ShotGenOptions) {
      const idx = this.lines.findIndex((l) => l.id === lineId)
      if (idx < 0 || this.lines[idx].shot.status === 'generating') return
      const line = this.lines[idx]
      if (shotPrompt !== undefined) line.shotPrompt = shotPrompt
      if (options) line.shotOptions = { ...options }
      const genOptions = line.shotOptions ?? DEFAULT_SHOT_OPTIONS
      line.shot.status = 'generating'
      const variant = line.shot.assets.length
      const { coverUrl, videoUrl, duration } = await api.generateShotVideo(
        line.scenePrompt,
        line.shotPrompt,
        line.digitalHumanIds,
        idx,
        variant,
        genOptions,
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
