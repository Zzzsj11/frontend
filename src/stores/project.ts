import { defineStore } from 'pinia'
import type { DigitalHuman, GeneralStoryboardOptions, GeneralStoryboardRequest, MaterialExport, ScriptLine, ShotAsset, ShotGenOptions, SongProject, StoryBible, SynthesisState, TimelineClip } from '../types'
import * as api from '../mock/api'
import * as imageGen from '../api/imageGen'
import { nextId } from '../mock/data'
import { reportApiError } from '../errorBus'
import { DEFAULT_VIDEO_DURATION, normalizeShotOptions } from '../mediaConstraints'
import { DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL } from '../generationModels'

/** 无配音时的占位时长（秒） */
export const DEFAULT_CLIP_DURATION = 5

/** 分镜视频生成参数默认值（清晰度 / 时长 / 画幅） */
export const DEFAULT_SHOT_OPTIONS: ShotGenOptions = { resolution: '720p', duration: DEFAULT_VIDEO_DURATION, ratio: '16:9', imageModel: DEFAULT_IMAGE_MODEL, videoModel: DEFAULT_VIDEO_MODEL }

let rafId = 0
let lastTick = 0
/** 每行场景图重新生成次数（仅用于 mock 占位图换款） */
const sceneVariants: Record<string, number> = {}
const exportStreams = new Map<string, AbortController>()

/** 数字人资产库本地持久化 key */
/** 删除分类后，该分类下数字人的归属分类 */
const FALLBACK_STYLE = '未分类'

export const useProjectStore = defineStore('project', {
  state: () => ({
    lines: [] as ScriptLine[],
    digitalHumans: [] as DigitalHuman[],
    /** 风格分类列表（支持增删改查，空分类也会保留） */
    dhStyles: [] as string[],
    dhStyleIds: {} as Record<string, string>,
    systemDhStyles: [] as string[],
    /** 歌曲项目列表（左侧任务栏：一个目录处理一首歌曲） */
    songProjects: [] as SongProject[],
    songProjectsLoading: false,
    songProjectsError: null as string | null,
    /** 当前打开的歌曲项目 id */
    activeSongId: '',
    /** 当前选中的处理任务 id */
    activeTaskId: null as string | null,
    /** 正在切换歌曲（载入脚本中） */
    songSwitching: false,
    /** 各子项目(任务)的脚本编辑现场缓存(按 taskId)，切回时不丢编辑状态 */
    taskScripts: {} as Record<string, { cast: string[]; lines: ScriptLine[] }>,
    /** 全局角色阵容：本 MV 选定的数字人（全片统一），分镜只能从阵容中挑选出演角色 */
    castIds: [] as string[],
    selectedLineId: null as string | null,
    /** 当前在弹窗中编辑的分镜行 */
    editingLineId: null as string | null,
    /** 打开分镜编辑弹窗时默认展开的选项 */
    editingTab: null as 'cast' | 'shot' | 'scene' | null,
    /** 资产库（角色阵容管理）弹窗开关 */
    libraryOpen: false,
    /** AI 魔法脚本弹窗开关 */
    magicOpen: false,
    magicError: null as string | null,
    /** 通用分镜参数弹窗 */
    generalStoryboardOpen: false,
    generalStoryboardLoading: false,
    generalStoryboardError: null as string | null,
    generalStoryboardOptions: null as GeneralStoryboardOptions | null,
    outlineOpen: false,
    outlineLoading: false,
    outlineError: null as string | null,
    activeStoryBible: null as StoryBible | null,
    activeStoryboardType: null as string | null,
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
    exportsByTaskId: {} as Record<string, MaterialExport[]>,
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

    /** 全部风格分类：显式管理的分类 + 数字人实际在用的分类（兜底合并，防止遗漏） */
    allDhStyles(state): string[] {
      return [...new Set([...state.dhStyles, ...state.digitalHumans.map((d) => d.style)])]
    },

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

    /** 是否有可导出的视频片段 */
    hasVideoAssets(state): boolean {
      return state.lines.some((line) => line.shot.assets.some((asset) => /^(https?:)/.test(asset.videoUrl)))
    },

    synthesis(state): SynthesisState {
      const latest = state.activeTaskId ? state.exportsByTaskId[state.activeTaskId]?.[0] : undefined
      if (!latest) return { status: 'idle', progress: 0 }
      return {
        status: latest.status,
        progress: latest.progress,
        stage: latest.stage,
        videoUrl: latest.archiveUrl,
        error: latest.error,
      }
    },

    storyboardProgress(state): { total: number; completed: number; failed: number; active: boolean } {
      const generated = state.lines.filter((line) => line.generationStatus)
      return {
        total: generated.length,
        completed: generated.filter((line) => line.generationStatus === 'succeeded').length,
        failed: generated.filter((line) => line.generationStatus === 'failed').length,
        active: generated.some((line) => line.generationStatus === 'pending' || line.generationStatus === 'running'),
      }
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
      if (this.songProjectsLoading) return
      this.songProjectsLoading = true
      this.songProjectsError = null
      try {
        const [projects, humans, styles] = await Promise.all([api.fetchSongProjects(), api.fetchDigitalHumans(), api.fetchDigitalHumanStyles()])
        this.songProjects = projects
        this.digitalHumans = humans
        this.dhStyles = styles.map((item) => item.name)
        this.dhStyleIds = Object.fromEntries(styles.map((item) => [item.name, item.id]))
        this.systemDhStyles = styles.filter((item) => item.readOnly).map((item) => item.name)
        if (!this.activeSongId && projects[0]) {
          this.activeSongId = projects[0].id
          const taskId = projects[0].tasks[0]?.id
          if (taskId) await this._loadTask(projects[0].id, taskId)
        }
      } catch (err) {
        this.songProjectsError = err instanceof Error ? err.message : '歌曲项目加载失败'
      } finally {
        this.songProjectsLoading = false
      }
    },

    /** 新建歌曲项目并加入列表 */
    async createSongProject(name: string): Promise<SongProject> {
      const song = await api.createSongProject(name)
      this.songProjects.push(song)
      // Creating a project is also a navigation action. Keep both operations in
      // one store transaction so a concurrent/finishing selection cannot leave
      // the editor attached to the previously active project.
      this._cacheCurrentTask()
      this.songSwitching = true
      try {
        await this._loadTask(song.id, null)
      } finally {
        this.songSwitching = false
      }
      return song
    },

    /** 把当前子项目(任务)的编辑现场写入缓存 */
    _cacheCurrentTask() {
      if (this.activeTaskId) {
        this.taskScripts[this.activeTaskId] = { cast: this.castIds, lines: this.lines }
      }
    },

    /** 载入指定子项目(任务)的脚本到编辑区（不负责缓存当前，调用方自行处理） */
    async _loadTask(songId: string, taskId: string | null) {
      const script = taskId ? await api.fetchSongScript(taskId) : { cast: [], lines: [], storyboardType: '', storyBible: undefined }
      if (taskId) this.taskScripts[taskId] = script
      this.stop()
      this.editingLineId = null
      this.castIds = [...script.cast]
      this.lines = script.lines
      this.activeSongId = songId
      this.activeTaskId = taskId
      this.activeStoryBible = script.storyBible ?? null
      this.activeStoryboardType = script.storyboardType || null
      this.selectedLineId = this.lines[0]?.id ?? null
      this.currentTime = 0
      if (taskId) {
        void this.restoreMaterialExports(taskId)
        const pending = this.lines.filter((line) => line.generationStatus === 'pending').map((line) => line.id)
        if (pending.length) void this._generateStoryboardQueue(taskId, pending)
      }
    },

    async _generateStoryboardQueue(taskId: string, lineIds: string[], force = false) {
      let cursor = 0
      const worker = async () => {
        while (cursor < lineIds.length) {
          const lineId = lineIds[cursor++]
          const local = this.lines.find((line) => line.id === lineId)
          if (local && this.activeTaskId === taskId) {
            local.generationStatus = 'running'
            local.generationError = undefined
          }
          try {
            const item = await api.generateStoryboardLine(taskId, lineId, force)
            const current = this.lines.find((line) => line.id === lineId)
            if (current && this.activeTaskId === taskId) {
              current.scenePrompt = String(item.scenePrompt || '')
              current.shotPrompt = String(item.shotPrompt || '')
              current.digitalHumanIds = (item.digitalHumanIds as string[]) || []
              current.generationStatus = 'succeeded'
              current.generationError = undefined
              current.generationAttempt = Number(item.generationAttempt || current.generationAttempt || 1)
            }
          } catch (error) {
            const current = this.lines.find((line) => line.id === lineId)
            if (current && this.activeTaskId === taskId) {
              current.generationStatus = 'failed'
              current.generationError = error instanceof Error ? error.message : '单条分镜生成失败'
            }
          }
        }
      }
      await Promise.all(Array.from({ length: Math.min(4, lineIds.length) }, () => worker()))
      if (this.activeTaskId === taskId) this._cacheCurrentTask()
    },

    async retryStoryboardLine(lineId: string) {
      if (!this.activeTaskId) return
      await this._generateStoryboardQueue(this.activeTaskId, [lineId], true)
    },

    async retryFailedStoryboardLines() {
      if (!this.activeTaskId) return
      const { lineIds } = await api.resetFailedStoryboardLines(this.activeTaskId)
      await this._generateStoryboardQueue(this.activeTaskId, lineIds, true)
    },

    openOutline() { if (this.activeTaskId && this.activeStoryBible) this.outlineOpen = true },
    closeOutline() { if (!this.outlineLoading) this.outlineOpen = false },
    async regenerateOutline() {
      if (!this.activeTaskId || this.activeStoryboardType !== 'ass' || this.outlineLoading) return
      this.outlineLoading = true
      this.outlineError = null
      try {
        const result = await api.regenerateStoryboardOutline(this.activeTaskId)
        this.activeStoryBible = result.storyBible
        for (const planned of result.lines) {
          const line = this.lines.find((item) => item.id === planned.id)
          if (!line) continue
          line.shotType = planned.shotType
          line.digitalHumanIds = [...planned.digitalHumanIds]
          line.scenePrompt = ''
          line.shotPrompt = ''
          line.generationStatus = 'pending'
          line.generationError = undefined
        }
        void this._generateStoryboardQueue(this.activeTaskId, result.lines.map((line) => line.id))
      } catch (error) {
        this.outlineError = error instanceof Error ? error.message : '大纲重新生成失败'
      } finally {
        this.outlineLoading = false
      }
    },

    /** 切换到某歌曲的处理任务(子项目)：每个任务是独立脚本，当前编辑现场先写入缓存 */
    async selectSongTask(songId: string, taskId: string | null = null) {
      if (this.songSwitching) return
      // 已在该任务上无需切换（无 taskId 时仅按歌曲判断）
      if (taskId ? taskId === this.activeTaskId : songId === this.activeSongId) return
      this.songSwitching = true
      try {
        this._cacheCurrentTask()
        await this._loadTask(songId, taskId)
      } finally {
        this.songSwitching = false
      }
    },

    /** 重命名歌曲项目(目录) */
    renameSongProject(songId: string, name: string) {
      const song = this.songProjects.find((s) => s.id === songId)
      const trimmed = name.trim()
      if (!song || !trimmed) return
      song.name = trimmed
      void api.updateSongProject(songId, trimmed)
    },

    /** 删除歌曲项目(目录)：连同其下所有子项目与脚本缓存；删除激活项时切到其余首个任务 */
    async deleteSongProject(songId: string) {
      const idx = this.songProjects.findIndex((s) => s.id === songId)
      if (idx < 0) return
      const [removed] = this.songProjects.splice(idx, 1)
      await api.deleteSongProject(songId)
      removed.tasks.forEach((t) => delete this.taskScripts[t.id])
      if (songId !== this.activeSongId) return
      // 删除的是当前激活歌曲：切到剩余首个歌曲的首个任务，否则清空编辑区
      const fallback = this.songProjects[0]
      this.songSwitching = true
      try {
        if (fallback) {
          await this._loadTask(fallback.id, fallback.tasks[0]?.id ?? null)
        } else {
          this.stop()
          this.editingLineId = null
          this.lines = []
          this.castIds = []
          this.activeSongId = ''
          this.activeTaskId = null
          this.selectedLineId = null
          this.currentTime = 0
        }
      } finally {
        this.songSwitching = false
      }
    },

    /** 重命名子项目(任务) */
    renameSongTask(songId: string, taskId: string, title: string) {
      const song = this.songProjects.find((s) => s.id === songId)
      const task = song?.tasks.find((t) => t.id === taskId)
      const trimmed = title.trim()
      if (!task || !trimmed) return
      task.title = trimmed
      void api.updateSongTask(taskId, trimmed)
    },

    /** 删除子项目(任务)：删除激活任务时切到同歌曲相邻任务，否则清空编辑区 */
    async deleteSongTask(songId: string, taskId: string) {
      const song = this.songProjects.find((s) => s.id === songId)
      if (!song) return
      const idx = song.tasks.findIndex((t) => t.id === taskId)
      if (idx < 0) return
      song.tasks.splice(idx, 1)
      await api.deleteSongTask(taskId)
      delete this.taskScripts[taskId]
      if (taskId !== this.activeTaskId) return
      const next = song.tasks[idx] ?? song.tasks[idx - 1]
      this.songSwitching = true
      try {
        if (next) {
          await this._loadTask(song.id, next.id)
        } else {
          this.stop()
          this.editingLineId = null
          this.lines = []
          this.castIds = []
          this.activeTaskId = null
          this.selectedLineId = null
          this.currentTime = 0
        }
      } finally {
        this.songSwitching = false
      }
    },

    // ---------- 分镜行编辑 ----------
    addLine() {
      const line: ScriptLine = {
        id: nextId(),
        source: 'manual',
        lyrics: '',
        scenePrompt: '',
        shotPrompt: '',
        digitalHumanIds: [],
        voice: { status: 'none' },
        scene: { status: 'none' },
        shot: { status: 'none', assets: [] },
        manual: true,
      }
      this.lines.push(line)
      this.selectedLineId = line.id
      if (this.activeTaskId) void api.createStoryboardLine(this.activeTaskId,{source:'manual',lyrics:'',scene_prompt:'',shot_prompt:'',digital_human_ids:[]}).then((saved)=>{ line.id=saved.id; this.selectedLineId=saved.id })
    },

    removeLine(lineId: string) {
      const idx = this.lines.findIndex((l) => l.id === lineId)
      if (idx < 0) return
      // 脚本生成的分镜不允许删除，仅手动添加的分镜可删
      if (!this.lines[idx].manual) return
      void api.deleteStoryboardLine(lineId)
      this.lines.splice(idx, 1)
      if (this.selectedLineId === lineId) {
        this.selectedLineId = this.lines[Math.min(idx, this.lines.length - 1)]?.id ?? null
      }
      this.clampCurrentTime()
    },

    updateLyrics(lineId: string, lyrics: string) {
      const line = this.lines.find((l) => l.id === lineId)
      if (line) { line.lyrics = lyrics; void api.updateStoryboardLine(lineId,{lyrics}) }
    },

    updateScenePrompt(lineId: string, scenePrompt: string) {
      const line = this.lines.find((l) => l.id === lineId)
      if (line) { line.scenePrompt = scenePrompt; void api.updateStoryboardLine(lineId,{scene_prompt:scenePrompt}) }
    },

    updateShotPrompt(lineId: string, shotPrompt: string) {
      const line = this.lines.find((l) => l.id === lineId)
      if (line) { line.shotPrompt = shotPrompt; void api.updateStoryboardLine(lineId,{shot_prompt:shotPrompt}) }
    },

    /** 更新分镜视频生成参数（清晰度 / 时长 / 画幅） */
    updateShotOptions(lineId: string, options: ShotGenOptions) {
      const line = this.lines.find((l) => l.id === lineId)
      if (line) {
        const normalized = normalizeShotOptions(options)
        line.shotOptions = normalized
        void api.updateStoryboardLine(lineId,{shot_options:normalized})
      }
    },

    /** 切换某分镜的出演角色（只能选全局阵容内的数字人，可多选/可全不选） */
    toggleLineHuman(lineId: string, digitalHumanId: string) {
      const line = this.lines.find((l) => l.id === lineId)
      if (!line || !this.castIds.includes(digitalHumanId)) return
      const idx = line.digitalHumanIds.indexOf(digitalHumanId)
      idx >= 0 ? line.digitalHumanIds.splice(idx, 1) : line.digitalHumanIds.push(digitalHumanId)
      void api.updateStoryboardLine(lineId,{digital_human_ids:line.digitalHumanIds})
    },

    moveLine(fromIndex: number, toIndex: number) {
      if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) return
      const [moved] = this.lines.splice(fromIndex, 1)
      this.lines.splice(toIndex, 0, moved)
      if(this.activeTaskId) void api.reorderStoryboardLines(this.activeTaskId,this.lines.map((line)=>line.id))
    },

    selectLine(lineId: string) {
      this.selectedLineId = lineId
      // 单个分镜模式下，选中后把指针移到片段起点
      const clip = this.timelineClips.find((c) => c.lineId === lineId)
      if (clip && this.playMode.single) this.seek(clip.start)
    },

    openEditor(lineId: string, tab: 'cast' | 'shot' | 'scene' | null = null) {
      this.selectLine(lineId)
      this.editingTab = tab
      this.editingLineId = lineId
    },

    closeEditor() {
      this.editingLineId = null
      this.editingTab = null
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
      if(this.activeTaskId) void api.updateTaskCast(this.activeTaskId,this.castIds)
      this.lines.forEach((line)=>void api.updateStoryboardLine(line.id,{digital_human_ids:line.digitalHumanIds}))
    },

    /** 调用真实异步生图接口生成数字人形象，图片本地化存储后加入资产库 */
    async generateDigitalHuman(input: { name: string; style: string; description: string; referenceImage?: string }): Promise<DigitalHuman> {
      this.dhGenerating = true
      try {
        const prompt = imageGen.buildPortraitPrompt(input.description, input.style)
        const id = nextId('dh')
        const referenceImage = input.referenceImage || this.digitalHumans.find((human) => human.readOnly)?.originalAvatar
        const generated = await imageGen.generateImageAsset(prompt, {
          size: '1344x768',
          quality: 'medium',
          ...(referenceImage ? { image: referenceImage } : {}),
        })
        const avatar = await imageGen.localizeImage(id, generated.url)
        const draft: DigitalHuman = {
          id,
          name: input.name,
          style: input.style,
          avatar,
          description: input.description,
          avatarPrompt: prompt,
        }
        const dh = await api.createDigitalHuman({ name:draft.name, styleId:this.dhStyleIds[draft.style], description:draft.description, avatar:draft.avatar, thumbnail:generated.thumbnailUrl, avatarPrompt:draft.avatarPrompt, source:'generated' })
        this.digitalHumans.push(dh)
        this.ensureDhStyle(dh.style)
        return dh
      } finally {
        this.dhGenerating = false
      }
    },

    /** 上传自定义数字人：用户自备头像与信息直接加入资产库（名称、风格必填，不调用生图接口） */
    async addCustomDigitalHuman(input: {
      name: string
      style: string
      description?: string
      avatar: string
    }): Promise<DigitalHuman> {
      this.dhGenerating = true
      try {
        const prompt = imageGen.buildPortraitPrompt(input.description || input.name, input.style)
        const reference = await api.uploadDataUrl(input.avatar, `${nextId('reference')}.jpg`)
        const generated = await imageGen.generateImageAsset(prompt, { size:'1344x768', quality:'medium', image:reference.url })
        const dh = await api.createDigitalHuman({ name:input.name, styleId:this.dhStyleIds[input.style], description:input.description ?? '', avatar:generated.url, thumbnail:generated.thumbnailUrl, avatarPrompt:prompt, source:'uploaded' })
        this.digitalHumans.push(dh)
        this.ensureDhStyle(dh.style)
        return dh
      } finally {
        this.dhGenerating = false
      }
    },

    // ---------- 风格分类增删改查 ----------
    /** 分类持久化已迁移至 PostgreSQL */
    persistDhStyles() {
      /* 分类由 PostgreSQL 持久化；本方法保留以兼容现有同步 UI。 */
    },

    /** 登记某风格到分类列表（生成/上传/编辑数字人使用新风格时自动登记） */
    ensureDhStyle(style: string) {
      const s = style.trim()
      if (!s || this.dhStyles.includes(s)) return
      this.dhStyles.push(s)
      void api.createDigitalHumanStyle(s).then((item) => { this.dhStyleIds[s] = item.id })
    },

    /** 新增风格分类；名称为空或已存在时返回 false */
    addDhStyle(name: string): boolean {
      const s = name.trim()
      if (!s || s === '全部' || this.allDhStyles.includes(s)) return false
      this.dhStyles.push(s)
      void api.createDigitalHumanStyle(s).then((item) => { this.dhStyleIds[s] = item.id })
      return true
    },

    /** 重命名风格分类：同步更新该分类下所有数字人；目标名已存在时合并到该分类 */
    renameDhStyle(oldName: string, newName: string): boolean {
      if (this.systemDhStyles.includes(oldName)) return false
      const s = newName.trim()
      if (!s || s === '全部' || s === oldName) return false
      const idx = this.dhStyles.indexOf(oldName)
      // 分类可能仅来自兜底合并（在用但未登记），此时也允许重命名
      if (idx < 0 && !this.digitalHumans.some((d) => d.style === oldName)) return false
      if (idx >= 0) {
        this.dhStyles.includes(s) ? this.dhStyles.splice(idx, 1) : (this.dhStyles[idx] = s)
      } else if (!this.dhStyles.includes(s)) {
        this.dhStyles.push(s)
      }
      let touched = false
      this.digitalHumans.forEach((d) => {
        if (d.style === oldName) {
          d.style = s
          touched = true
        }
      })
      this.persistDhStyles()
      if (touched) this.digitalHumans.filter((d)=>d.style===s && !d.readOnly).forEach((d)=>void api.updateDigitalHuman(d.id,{style_id:this.dhStyleIds[s]}))
      return true
    },

    /** 删除风格分类：该分类下的数字人归入「未分类」 */
    deleteDhStyle(name: string) {
      if (this.systemDhStyles.includes(name)) return
      const idx = this.dhStyles.indexOf(name)
      if (idx >= 0) this.dhStyles.splice(idx, 1)
      let moved = false
      this.digitalHumans.forEach((d) => {
        if (d.style === name) {
          d.style = FALLBACK_STYLE
          moved = true
        }
      })
      if (moved && !this.dhStyles.includes(FALLBACK_STYLE)) this.dhStyles.push(FALLBACK_STYLE)
      this.persistDhStyles()
      const styleId=this.dhStyleIds[name]; if(styleId) void api.deleteDigitalHumanStyle(styleId)
    },

    /** 数字人持久化已迁移至 PostgreSQL */
    persistDigitalHumans() {
      /* 角色由 PostgreSQL 持久化；本方法保留以兼容现有同步 UI。 */
    },

    /** 编辑数字人基础信息 / 提示词 */
    updateDigitalHuman(
      id: string,
      patch: Partial<Pick<DigitalHuman, 'name' | 'style' | 'description' | 'avatarPrompt'>>,
    ) {
      const dh = this.digitalHumans.find((d) => d.id === id)
      if (!dh || dh.readOnly) return
      Object.assign(dh, patch)
      if (!dh.readOnly) void api.updateDigitalHuman(id,{ name:patch.name, style_id:patch.style ? this.dhStyleIds[patch.style] : undefined, description:patch.description, avatar_prompt:patch.avatarPrompt })
      if (patch.style) this.ensureDhStyle(patch.style)
    },

    /** 删除数字人：同步从全局阵容与所有分镜出演角色中移除 */
    deleteDigitalHuman(id: string) {
      const idx = this.digitalHumans.findIndex((d) => d.id === id)
      if (idx < 0 || this.digitalHumans[idx].readOnly) return
      void api.deleteDigitalHuman(id)
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
      if (!dh || dh.readOnly || this.dhRegeneratingId) return
      this.dhRegeneratingId = id
      try {
        const finalPrompt = (prompt ?? dh.avatarPrompt ?? imageGen.buildPortraitPrompt(dh.description, dh.style)).trim()
        const generated = await imageGen.generateImageAsset(finalPrompt, { size: '1344x768', quality: 'medium', image:dh.originalAvatar || dh.avatar })
        dh.avatar = generated.thumbnailUrl || generated.url
        dh.originalAvatar = await imageGen.localizeImage(dh.id, generated.url)
        dh.avatarPrompt = finalPrompt
        if (!dh.readOnly) await api.updateDigitalHuman(id,{avatar_url:dh.originalAvatar,avatar_thumbnail_url:generated.thumbnailUrl,avatar_prompt:finalPrompt})
      } finally {
        this.dhRegeneratingId = null
      }
    },

    // ---------- Mock API 联动 ----------
    openMagic() {
      this.magicError = null
      this.magicOpen = true
    },
    closeMagic() {
      this.magicOpen = false
    },

    async openGeneralStoryboard() {
      this.generalStoryboardOpen = true
      this.generalStoryboardError = null
      if (!this.generalStoryboardOptions) {
        try {
          this.generalStoryboardOptions = await api.fetchGeneralStoryboardOptions()
        } catch (err) {
          this.generalStoryboardError = err instanceof Error ? err.message : '加载选项失败'
        }
      }
    },

    closeGeneralStoryboard() {
      if (!this.generalStoryboardLoading) this.generalStoryboardOpen = false
    },

    /** 按曲风、人物与镜头规模生成无歌词的通用分镜脚本 */
    async runGeneralStoryboard(req: GeneralStoryboardRequest) {
      if (this.generalStoryboardLoading) return
      this.generalStoryboardLoading = true
      this.generalStoryboardError = null
      try {
        const result = await api.generateGeneralStoryboard({ ...req, projectId: this.activeSongId })
        const lines: ScriptLine[] = result.lines.map((item) => ({
          id: item.id || nextId(),
          source: 'general',
          shotType: item.shotType,
          plannedDuration: item.plannedDuration,
          lyrics: '',
          scenePrompt: item.scenePrompt,
          shotPrompt: item.shotPrompt,
          digitalHumanIds: [...item.digitalHumanIds],
          voice: { status: 'none' },
          scene: { status: 'none' },
          shot: { status: 'none', assets: [] },
          shotOptions: { ...DEFAULT_SHOT_OPTIONS, ratio: req.ratio, resolution: req.resolution, imageModel: req.imageModel, videoModel: req.videoModel },
          generationStatus: item.generationStatus || 'pending',
        }))
        this._cacheCurrentTask()
        let song = this.songProjects.find((s) => s.id === this.activeSongId)
        if (!song) {
          song = { id: nextId('song'), name: req.singer?.trim() || '未命名歌曲', tasks: [] }
          this.songProjects.push(song)
          this.activeSongId = song.id
        }
        const task = { id: result.taskId, title: result.title, updatedAt: '刚刚' }
        song.tasks.push(task)
        this.stop()
        this.editingLineId = null
        this.castIds = [...result.cast]
        this.lines = lines
        this.taskScripts[task.id] = { cast: this.castIds, lines: this.lines }
        this.activeTaskId = task.id
        this.activeStoryBible = (result as typeof result & { storyboardConfig?: { storyBible?: StoryBible } }).storyboardConfig?.storyBible ?? null
        this.activeStoryboardType = 'general'
        this.selectedLineId = this.lines[0]?.id ?? null
        this.currentTime = 0
        this.generalStoryboardOpen = false
        void this._generateStoryboardQueue(task.id, lines.map((line) => line.id))
      } catch (err) {
        this.generalStoryboardError = err instanceof Error ? err.message : '通用分镜生成失败'
      } finally {
        this.generalStoryboardLoading = false
      }
    },

    /** 提交魔法脚本表单：生成成功后在当前歌曲目录下新建一个子项目(任务)并载入生成的脚本 */
    async runMagicScript(req?: api.MagicScriptRequest) {
      if (this.magicLoading) return
      this.magicLoading = true
      this.magicError = null
      try {
        if (!req || !this.activeSongId) throw new Error('请先选择歌曲项目')
        const script = await api.generateMagicScript({ ...req, projectId: this.activeSongId })
        // 脚本自带统一的角色阵容
        const lines: ScriptLine[] = script.lines.map((item) => ({
          id: (item as typeof item & { id?: string }).id || nextId(),
          source: 'ass',
          shotType: (item as typeof item & { shotType?: ScriptLine['shotType'] }).shotType,
          plannedDuration: (item as typeof item & { plannedDuration?: number }).plannedDuration,
          lyrics: item.lyrics,
          scenePrompt: item.scenePrompt,
          shotPrompt: item.shotPrompt,
          digitalHumanIds: [...item.digitalHumanIds],
          voice: { status: 'none' },
          scene: { status: 'none' },
          shot: { status: 'none', assets: [] },
          shotOptions: { ...DEFAULT_SHOT_OPTIONS, ratio: req.ratio, resolution: req.resolution, imageModel: req.imageModel, videoModel: req.videoModel },
          generationStatus: (item as typeof item & { generationStatus?: ScriptLine['generationStatus'] }).generationStatus || 'pending',
        }))
        // 先缓存当前子项目编辑现场，避免被新脚本覆盖丢失
        this._cacheCurrentTask()
        // 在当前歌曲目录下创建一个新的子项目(任务)
        let song = this.songProjects.find((s) => s.id === this.activeSongId)
        if (!song) {
          song = { id: nextId('song'), name: '未命名歌曲', tasks: [] }
          this.songProjects.push(song)
          this.activeSongId = song.id
        }
        const task = { id: script.taskId, title: 'MV 分镜制作', updatedAt: '刚刚' }
        song.tasks.push(task)
        // 载入生成结果到新子项目
        this.stop()
        this.editingLineId = null
        this.castIds = [...script.cast]
        this.lines = lines
        this.taskScripts[task.id] = { cast: this.castIds, lines: this.lines }
        this.activeTaskId = task.id
        this.activeStoryBible = (script as typeof script & { storyBible?: StoryBible }).storyBible ?? null
        this.activeStoryboardType = 'ass'
        this.selectedLineId = this.lines[0]?.id ?? null
        this.currentTime = 0
        this.magicOpen = false
        void this._generateStoryboardQueue(task.id, lines.map((line) => line.id))
      } catch (err) {
        this.magicError = err instanceof Error ? err.message : 'ASS 分镜生成失败'
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
      try {
        const options = normalizeShotOptions(line.shotOptions ?? DEFAULT_SHOT_OPTIONS)
        const { imageUrl, thumbnailUrl } = await api.generateSceneImage(line.scenePrompt, idx, variant, this.activeTaskId ?? undefined, lineId, options.ratio, options.imageModel)
        const still = this.lines.find((l) => l.id === lineId)
        if (still) still.scene = { status: 'done', imageUrl: thumbnailUrl || imageUrl, originalImageUrl: imageUrl }
      } catch (error) {
        const still = this.lines.find((l) => l.id === lineId)
        if (still) still.scene.status = 'none'
        throw reportApiError(error, '场景图生成失败')
      }
    },

    /** 生成/重新生成分镜视频片段（场景 × 分镜提示词 × 出演角色 × 生成参数）；新片段作为资产追加并选中 */
    async generateShotFor(lineId: string, shotPrompt?: string, options?: ShotGenOptions) {
      const idx = this.lines.findIndex((l) => l.id === lineId)
      if (idx < 0 || this.lines[idx].shot.status === 'generating') return
      const line = this.lines[idx]
      if (shotPrompt !== undefined) line.shotPrompt = shotPrompt
      if (options) line.shotOptions = normalizeShotOptions(options)
      const genOptions = normalizeShotOptions(line.shotOptions ?? DEFAULT_SHOT_OPTIONS)
      line.shot.status = 'generating'
      const variant = line.shot.assets.length
      try {
        const { coverUrl, coverThumbnailUrl, videoUrl, duration } = await api.generateShotVideo(
        line.scenePrompt,
        line.shotPrompt,
        line.digitalHumanIds,
        idx,
        variant,
        genOptions,
        line.scene.imageUrl,
        this.activeTaskId ?? undefined,
        lineId,
        )
        const still = this.lines.find((l) => l.id === lineId)
        if (still) {
        const asset: ShotAsset = {
          id: nextId('asset'),
          coverUrl,
          originalCoverUrl: coverUrl,
          videoUrl,
          duration,
          digitalHumanIds: [...line.digitalHumanIds],
        }
        still.shot.assets.push(asset)
        still.shot.currentAssetId = asset.id
        asset.coverUrl = coverThumbnailUrl || coverUrl
        still.shot.imageUrl = asset.coverUrl
          still.shot.status = 'done'
        }
      } catch (error) {
        const still = this.lines.find((l) => l.id === lineId)
        if (still) still.shot.status = 'none'
        throw reportApiError(error, '分镜视频生成失败')
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
          if (line.source !== 'general' && line.voice.status !== 'done') await this.generateVoiceFor(line.id)
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

    _upsertMaterialExport(item: MaterialExport) {
      const items = this.exportsByTaskId[item.taskId] || []
      const next = [item, ...items.filter((current) => current.id !== item.id)]
      this.exportsByTaskId[item.taskId] = next.sort((left, right) => right.createdAt.localeCompare(left.createdAt))
    },

    async _watchMaterialExport(item: MaterialExport) {
      if (!item.jobId || exportStreams.has(item.id) || ['ready', 'failed'].includes(item.status)) return
      const controller = new AbortController()
      exportStreams.set(item.id, controller)
      try {
        for (let attempt = 0; attempt < 4 && !controller.signal.aborted; attempt += 1) {
          try {
            await api.streamMaterialExport(item.id, (update) => this._upsertMaterialExport(update), controller.signal)
          } catch (error) {
            if (controller.signal.aborted) return
            if (attempt === 3) throw error
            await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1)))
          }
          const latest = await api.fetchMaterialExport(item.id)
          this._upsertMaterialExport(latest)
          if (['ready', 'failed'].includes(latest.status)) return
        }
      } catch (error) {
        reportApiError(error, '导出进度连接失败，可刷新页面恢复')
      } finally {
        exportStreams.delete(item.id)
      }
    },

    async restoreMaterialExports(taskId: string) {
      try {
        const items = await api.fetchMaterialExports(taskId)
        this.exportsByTaskId[taskId] = items
        items.filter((item) => ['queued', 'running'].includes(item.status)).forEach((item) => void this._watchMaterialExport(item))
      } catch (error) {
        reportApiError(error, '导出任务恢复失败')
      }
    },

    async runSynthesize() {
      if (['queued', 'running'].includes(this.synthesis.status) || !this.hasVideoAssets || !this.activeTaskId) return
      const taskId = this.activeTaskId
      try {
        const item = await api.exportMaterials(taskId)
        this._upsertMaterialExport(item)
        void this._watchMaterialExport(item)
      } catch (error) {
        throw reportApiError(error, '导出素材失败')
      }
    },

    downloadLatestExport() {
      if (!this.synthesis.videoUrl) return
      const link = document.createElement('a')
      link.href = this.synthesis.videoUrl
      link.download = ''
      link.rel = 'noopener'
      link.click()
    },

    cancelExportStreams() {
      exportStreams.forEach((controller) => controller.abort())
      exportStreams.clear()
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
