import { defineStore } from 'pinia'
import { useAuthStore } from './auth'
import type {
  DigitalHuman,
  GeneralStoryboardOptions,
  GeneralStoryboardRequest,
  MaterialExport,
  OutlineFailedSegment,
  OutlinePlannedLine,
  OutlineProgress,
  ScriptLine,
  ShotAsset,
  ShotGenOptions,
  SongProject,
  StoryBible,
  SynthesisState,
  TimelineClip,
} from '../types'
import * as api from '../api/domain'
import * as imageGen from '../api/imageGen'
import { generateVoice } from '../api/voice'
import { nextId } from '../utils/id'
import { ApiError, reportApiError } from '../errorBus'
import { DEFAULT_VIDEO_DURATION, normalizeShotOptions } from '../mediaConstraints'
import { DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL } from '../generationModels'

/** 侧边栏选中状态持久化 key（按用户隔离） */
const sidebarKeys = (userId: string) => ({
  song: `mv_sidebar_song_${userId}`,
  task: `mv_sidebar_task_${userId}`,
})

/** 无配音时的占位时长（秒） */
export const DEFAULT_CLIP_DURATION = 5

/** 分镜视频生成参数默认值（清晰度 / 时长 / 画幅） */
export const DEFAULT_SHOT_OPTIONS: ShotGenOptions = {
  resolution: '480p',
  duration: DEFAULT_VIDEO_DURATION,
  ratio: '16:9',
  imageModel: DEFAULT_IMAGE_MODEL,
  videoModel: DEFAULT_VIDEO_MODEL,
}

let rafId = 0
let lastTick = 0
/** 每行场景图重新生成次数（仅用于 mock 占位图换款） */
const sceneVariants: Record<string, number> = {}
const exportStreams = new Map<string, AbortController>()
/** 刷新恢复后正在续跑的媒体生成任务（防止重复恢复同一任务） */
const resumedGenerationJobs = new Set<string>()
/** 正在轮询「逐句提示词生成」孤儿任务的任务 ID */
const storyboardRunningWatchers = new Set<string>()
/** 本地逐句生成队列正在处理的行（刷新恢复轮询需跳过，避免用旧数据覆盖） */
const localGeneratingLines = new Set<string>()
/** 未完成的数字人生成草稿（localStorage）：刷新/重开后恢复等待态并补建 */
const PENDING_DH_KEY = 'mv:pending-dh'

interface PendingDhDraft {
  mode: 'generated' | 'uploaded'
  jobId: string
  name: string
  style: string
  description: string
  styleId?: string
}

const savePendingDhDraft = (draft: PendingDhDraft) => {
  try {
    localStorage.setItem(PENDING_DH_KEY, JSON.stringify(draft))
  } catch {
    /* 存储不可用时仅放弃恢复能力 */
  }
}
const clearPendingDhDraft = () => {
  try {
    localStorage.removeItem(PENDING_DH_KEY)
  } catch {
    /* ignore */
  }
}
const readPendingDhDraft = (): PendingDhDraft | null => {
  try {
    const raw = localStorage.getItem(PENDING_DH_KEY)
    return raw ? (JSON.parse(raw) as PendingDhDraft) : null
  } catch {
    return null
  }
}

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
    /** 大纲生成中的任务归属：全局 outlineLoading 不区分任务，切到其他子项目时
     *  该任务自己的弹窗/按钮不能被别人的生成状态锁死，用 outlineTaskId 隔离 */
    outlineTaskId: null as string | null,
    outlineError: null as string | null,
    /** 大纲后台生成进度（SSE 推送：planning/segments 阶段与场景段计数） */
    outlineProgress: null as OutlineProgress | null,
    /** 大纲本轮开始时间戳（ms），用于前端正向计时器 */
    outlineStartedAt: 0,
    activeStoryBible: null as StoryBible | null,
    activeStoryboardType: null as string | null,
    /** 当前任务状态（parsed/outlining/outline_failed/generating/ready/partial/failed） */
    activeTaskStatus: null as string | null,
    /** 正在重试的场景段序号（段级大纲重新生成） */
    segmentRetrying: {} as Record<number, boolean>,
    currentTime: 0,
    isPlaying: false,
    playMode: { single: false, loop: false },
    volume: 1,
    muted: false,
    batchVoicing: false,
    batchShooting: false,
    magicLoading: false,
    /** 正在调用真实生图接口生成数字人形象 */
    dhGenerating: false,
    /** 当前阶段：uploading / generating */
    dhGeneratingPhase: '' as string,
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
        clips.find(
          (c) => state.currentTime >= c.start && state.currentTime < c.start + c.duration,
        ) ?? clips[clips.length - 1]
      )
    },

    currentLine(): ScriptLine | undefined {
      const clip: TimelineClip | undefined = this.currentClip
      return clip ? this.lines.find((l) => l.id === clip.lineId) : undefined
    },

    editingLine(state): ScriptLine | undefined {
      return state.lines.find((l) => l.id === state.editingLineId)
    },

    digitalHumanOf: (state) => (id?: string) => state.digitalHumans.find((d) => d.id === id),

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
    lineHumans:
      (state) =>
      (line: ScriptLine): DigitalHuman[] =>
        line.digitalHumanIds
          .map((id) => state.digitalHumans.find((d) => d.id === id))
          .filter((d): d is DigitalHuman => !!d),

    /** 分镜展示图：优先视频片段封面，其次场景底图 */
    coverOf:
      () =>
      (line: ScriptLine): string | undefined =>
        line.shot.imageUrl ?? line.scene.imageUrl,

    /** 当前选用资产的真实可播放视频地址（mock:// 假地址除外） */
    videoOf:
      () =>
      (line: ScriptLine): string | undefined => {
        const asset = line.shot.assets.find((a) => a.id === line.shot.currentAssetId)
        return asset && /^(\/|https?:)/.test(asset.videoUrl) ? asset.videoUrl : undefined
      },

    /** 歌词的中文翻译：仅当歌词非中文（不含汉字）且存在译文时展示 */
    translationOf:
      () =>
      (line: ScriptLine): string | undefined => {
        if (!line.lyrics || /[\u4e00-\u9fff]/.test(line.lyrics)) return undefined
        return line.lyricsZh?.trim() || undefined
      },

    /** 是否有可导出的视频片段 */
    hasVideoAssets(state): boolean {
      return state.lines.some((line) =>
        line.shot.assets.some((asset) => /^(https?:)/.test(asset.videoUrl)),
      )
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

    storyboardProgress(state): {
      total: number
      completed: number
      failed: number
      active: boolean
    } {
      // 大纲未就绪（pending/failed）的行不参与逐句生成进度统计
      const generated = state.lines.filter(
        (line) =>
          line.generationStatus &&
          line.shotOptions?.outlineStatus !== 'pending' &&
          line.shotOptions?.outlineStatus !== 'failed',
      )
      return {
        total: generated.length,
        completed: generated.filter((line) => line.generationStatus === 'succeeded').length,
        failed: generated.filter((line) => line.generationStatus === 'failed').length,
        active: generated.some(
          (line) => line.generationStatus === 'pending' || line.generationStatus === 'running',
        ),
      }
    },

    /** 大纲加载锁：仅当「当前任务自己」正在生成大纲时为 true。
     *  outlineLoading 是全局的（别的子项目生成中也会置位），用它直接锁弹窗/按钮
     *  会把其他任务的大纲弹窗一并锁死（无法关闭），故用 outlineTaskId 归属隔离 */
    outlineLocked(state): boolean {
      return state.outlineLoading && state.outlineTaskId === state.activeTaskId
    },

    /** ASS 大纲阶段：pending=拆分完成待生成 / outlining=生成中 / failed=生成失败 */
    outlinePhase(state): 'none' | 'pending' | 'outlining' | 'failed' {
      if (state.activeStoryboardType !== 'ass') return 'none'
      if (this.outlineLocked || state.activeTaskStatus === 'outlining') return 'outlining'
      if (state.activeTaskStatus === 'outline_failed') return 'failed'
      if (state.activeTaskStatus === 'parsed') return 'pending'
      return 'none'
    },

    /** 大纲生成失败的场景段（段级重试入口） */
    failedOutlineSegments(state): OutlineFailedSegment[] {
      if (state.activeStoryboardType !== 'ass') return []
      return state.activeStoryBible?.failedSegments ?? []
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
        const [projects, humans, styles] = await Promise.all([
          api.fetchSongProjects(),
          api.fetchDigitalHumans(),
          api.fetchDigitalHumanStyles(),
        ])
        this.songProjects = projects
        this.digitalHumans = humans
        // 以系统人物 001 的三视图为后续生成的模板参考
        const template = humans.find((h) => h.id === 'dh-system-001')
        if (template) imageGen.setTemplateAvatar(template.avatar)
        this.dhStyles = styles.map((item) => item.name)
        this.dhStyleIds = Object.fromEntries(styles.map((item) => [item.name, item.id]))
        this.systemDhStyles = styles.filter((item) => item.readOnly).map((item) => item.name)
        void this.resumePendingDigitalHuman()
        // 恢复上次选中的项目和子项目（按用户隔离），无记录则默认第一个
        const auth = useAuthStore()
        const userId = auth.user?.id || ''
        const savedSongId =
          !this.activeSongId && userId ? localStorage.getItem(sidebarKeys(userId).song) : null
        const savedTaskId =
          !this.activeTaskId && userId ? localStorage.getItem(sidebarKeys(userId).task) : null
        const song = savedSongId ? projects.find((p) => p.id === savedSongId) : projects[0]
        if (song) {
          const task = savedTaskId ? song.tasks.find((t) => t.id === savedTaskId) : song.tasks[0]
          if (task) await this._loadTask(song.id, task.id)
          else if (song.tasks[0]) await this._loadTask(song.id, song.tasks[0].id)
          else this.activeSongId = song.id
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
      const script = taskId
        ? await api.fetchSongScript(taskId)
        : {
            cast: [],
            lines: [] as ScriptLine[],
            storyboardType: '',
            storyBible: undefined,
            status: '',
          }
      if (taskId) this.taskScripts[taskId] = script
      this.stop()
      this.editingLineId = null
      this.castIds = [...script.cast]
      this.lines = script.lines
      this.activeSongId = songId
      this.activeTaskId = taskId
      const auth = useAuthStore()
      if (songId && auth.user) localStorage.setItem(sidebarKeys(auth.user.id).song, songId)
      if (taskId && auth.user) localStorage.setItem(sidebarKeys(auth.user.id).task, taskId)
      this.activeStoryBible = script.storyBible ?? null
      this.activeStoryboardType = script.storyboardType || null
      this.activeTaskStatus = script.status || null
      this.selectedLineId = this.lines[0]?.id ?? null
      this.currentTime = 0
      if (taskId) {
        void this.restoreMaterialExports(taskId)
        void this.resumeActiveGenerations(taskId)
        if (
          script.storyboardType === 'ass' &&
          (script.status === 'parsed' || script.status === 'outlining')
        ) {
          // parsed：上传仅完成拆分，自动接续大纲生成；outlining：上次大纲中断遗留，重新生成
          void this.runOutlineGeneration(taskId)
        } else {
          const pending = this.lines
            .filter((line) => line.generationStatus === 'pending' && this._outlineReady(line))
            .map((line) => line.id)
          if (pending.length) void this._generateStoryboardQueue(taskId, pending)
        }
        // 刷新前仍在逐句生成的行：后端孤儿请求仍会跑完，轮询待其落定后合并
        if (this.lines.some((line) => line.generationStatus === 'running'))
          void this._watchRunningStoryboardLines(taskId)
        // 有失败的场景段：自动重试（后台任务可能还在跑，幂等保护由后端 409 兜底）
        const failedSegments = script.storyBible?.failedSegments ?? []
        if (failedSegments.length) {
          void (async () => {
            for (const seg of failedSegments) {
              if (this.activeTaskId !== taskId) break
              await this.retryOutlineSegment(seg.sceneIndex).catch(() => {})
            }
          })()
        }
      }
    },

    /** 行的大纲是否已就绪（未就绪的行不能进入逐句生成，后端会 422） */
    _outlineReady(line: ScriptLine): boolean {
      return (
        line.shotOptions?.outlineStatus !== 'pending' &&
        line.shotOptions?.outlineStatus !== 'failed'
      )
    },

    async _generateStoryboardQueue(taskId: string, lineIds: string[], force = false) {
      let cursor = 0
      const worker = async () => {
        while (cursor < lineIds.length) {
          const lineId = lineIds[cursor++]
          const local = this.lines.find((line) => line.id === lineId)
          if (local && this.activeTaskId === taskId && !this._outlineReady(local)) continue
          // 跳过已经在生成中或已完成的，避免重复提交触发后端 409
          if (
            local &&
            this.activeTaskId === taskId &&
            (local.generationStatus === 'running' || local.generationStatus === 'succeeded')
          )
            continue
          if (local && this.activeTaskId === taskId) {
            local.generationStatus = 'running'
            local.generationError = undefined
          }
          localGeneratingLines.add(lineId)
          try {
            const item = await api.generateStoryboardLine(taskId, lineId, force)
            const current = this.lines.find((line) => line.id === lineId)
            if (current && this.activeTaskId === taskId) {
              current.scenePrompt = String(item.scenePrompt || '')
              current.shotPrompt = String(item.shotPrompt || '')
              current.digitalHumanIds = (item.digitalHumanIds as string[]) || []
              current.generationStatus = 'succeeded'
              current.generationError = undefined
              current.generationAttempt = Number(
                item.generationAttempt || current.generationAttempt || 1,
              )
            }
          } catch (error) {
            // 409 表示后端已有任务在处理，静默跳过
            if (error instanceof ApiError && error.status === 409) {
              const current = this.lines.find((line) => line.id === lineId)
              if (current && this.activeTaskId === taskId) current.generationStatus = 'running'
            } else {
              const current = this.lines.find((line) => line.id === lineId)
              if (current && this.activeTaskId === taskId) {
                current.generationStatus = 'failed'
                current.generationError =
                  error instanceof Error ? error.message : '单条视频提示词生成失败'
              }
            }
          } finally {
            localGeneratingLines.delete(lineId)
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

    /** 刷新/切任务后恢复仍在排队或执行中的媒体生成（场景图/视频）等待态；结果由后端落库，落定后重新拉取合并 */
    async resumeActiveGenerations(taskId: string) {
      const jobs = await api.fetchActiveGenerations(taskId).catch(() => [])
      for (const job of jobs) {
        if (!job.storyboardLineId || resumedGenerationJobs.has(job.id)) continue
        const line = this.lines.find((item) => item.id === job.storyboardLineId)
        if (!line) continue
        const slot = job.kind === 'video' ? line.shot : line.scene
        if (slot.status === 'generating') continue
        slot.status = 'generating'
        slot.error = undefined
        resumedGenerationJobs.add(job.id)
        void this._watchGenerationJob(taskId, job.id, job.storyboardLineId, job.kind)
      }
    },

    async _watchGenerationJob(
      taskId: string,
      jobId: string,
      lineId: string,
      kind: 'image' | 'video',
    ) {
      let failed: string | undefined
      try {
        await api.waitGenerationJob(jobId)
      } catch (error) {
        failed =
          error instanceof Error
            ? error.message
            : kind === 'video'
              ? '视频生成失败'
              : '场景图生成失败'
      } finally {
        resumedGenerationJobs.delete(jobId)
      }
      if (this.activeTaskId !== taskId) return
      // 后端在任务成功时已把资产落库，重新拉取后只合并媒体子状态，不覆盖用户正在编辑的提示词
      const fresh = await api.fetchSongScript(taskId).catch(() => null)
      if (!fresh || this.activeTaskId !== taskId) return
      const freshLine = fresh.lines.find((item) => item.id === lineId)
      const current = this.lines.find((item) => item.id === lineId)
      if (!freshLine || !current) return
      if (kind === 'video') current.shot = freshLine.shot
      else current.scene = freshLine.scene
      if (failed) {
        const slot = kind === 'video' ? current.shot : current.scene
        slot.status = 'failed'
        slot.error = failed
      }
    },

    /** 刷新前被中断的逐句提示词生成：后端孤儿请求仍会跑完并落库，轮询任务直至行状态落定后合并 */
    async _watchRunningStoryboardLines(taskId: string) {
      if (storyboardRunningWatchers.has(taskId)) return
      storyboardRunningWatchers.add(taskId)
      try {
        for (let attempt = 0; attempt < 60; attempt++) {
          await new Promise((resolve) => setTimeout(resolve, 5000))
          if (this.activeTaskId !== taskId) return
          const fresh = await api.fetchSongScript(taskId).catch(() => null)
          if (!fresh || this.activeTaskId !== taskId) return
          for (const freshLine of fresh.lines) {
            const current = this.lines.find((item) => item.id === freshLine.id)
            if (
              current &&
              current.generationStatus === 'running' &&
              !localGeneratingLines.has(current.id) &&
              freshLine.generationStatus !== 'running'
            ) {
              current.scenePrompt = freshLine.scenePrompt
              current.shotPrompt = freshLine.shotPrompt
              current.digitalHumanIds = freshLine.digitalHumanIds
              current.generationStatus = freshLine.generationStatus
              current.generationError = freshLine.generationError
              current.generationAttempt = freshLine.generationAttempt
            }
          }
          if (!fresh.lines.some((line) => line.generationStatus === 'running')) return
        }
      } finally {
        storyboardRunningWatchers.delete(taskId)
      }
    },

    openOutline() {
      if (this.activeTaskId && this.activeStoryBible) this.outlineOpen = true
    },
    closeOutline() {
      // 只锁「当前任务自己」的生成中状态；其他任务生成中不影响本任务弹窗关闭
      if (this.outlineLocked) return
      this.outlineOpen = false
    },

    /** 同步任务状态到当前编辑区与侧边栏任务列表 */
    _setTaskStatus(taskId: string, status: string) {
      if (this.activeTaskId === taskId) this.activeTaskStatus = status
      for (const song of this.songProjects) {
        const task = song.tasks.find((item) => item.id === taskId)
        if (task) {
          task.status = status
          break
        }
      }
    },

    /** 把大纲规划结果回填到行：镜头类型/人物/时长/参数，清空旧提示词等待逐句生成 */
    _applyOutlineLines(plannedLines: OutlinePlannedLine[]) {
      for (const planned of plannedLines) {
        const line = this.lines.find((item) => item.id === planned.id)
        if (!line) continue
        line.shotType = planned.shotType
        if (planned.plannedDuration) line.plannedDuration = planned.plannedDuration
        if (planned.shotOptions)
          line.shotOptions = normalizeShotOptions({
            ...line.shotOptions,
            ...planned.shotOptions,
          } as ShotGenOptions)
        line.digitalHumanIds = [...planned.digitalHumanIds]
        line.scenePrompt = ''
        line.shotPrompt = ''
        line.generationStatus = 'pending'
        line.generationError = undefined
      }
    },

    /**
     * 订阅大纲生成进度 SSE；返回 true=已到达终态，false=看门狗超时（进度长时间无更新，需重新触发）。
     * 服务端只在 status 离开 outlining 后关闭流；僵尸任务（后台丢失）时流不会关闭，由看门狗兜底。
     */
    async _watchOutline(taskId: string): Promise<boolean> {
      const controller = new AbortController()
      let lastEventAt = Date.now()
      const watchdog = window.setInterval(() => {
        if (Date.now() - lastEventAt > 150_000) controller.abort()
      }, 1000)
      try {
        await api.streamStoryboardOutline(
          taskId,
          (event) => {
            lastEventAt = Date.now()
            this.outlineProgress = event.progress
            this._setTaskStatus(taskId, event.status)
          },
          controller.signal,
        )
        return true
      } catch (error) {
        if (controller.signal.aborted) return false
        // SSE 连接失败：降级为直接查询一次任务状态
        const fresh = await api.fetchSongScript(taskId).catch(() => null)
        return fresh !== null && fresh.status !== 'outlining'
      } finally {
        window.clearInterval(watchdog)
      }
    },

    /** ASS 大纲生成（上传后自动调用 / 失败后手动重试）：202 受理 + SSE 进度；成功后自动接续逐句提示词生成 */
    async runOutlineGeneration(taskId?: string) {
      const id = taskId ?? this.activeTaskId
      if (
        !id ||
        this.activeTaskId !== id ||
        this.activeStoryboardType !== 'ass' ||
        // 防重入只看同任务：别的子项目正在生成时不阻塞本任务触发
        (this.outlineLoading && this.outlineTaskId === id)
      )
        return
      // 进入时已是 outlining：后台仍在生成（如刷新后续跑），直接订阅进度，不重复触发
      const resumeWatching = this.activeTaskStatus === 'outlining'
      this.outlineLoading = true
      this.outlineTaskId = id
      this.outlineError = null
      this.outlineProgress = null
      this.outlineStartedAt = Date.now()
      this._setTaskStatus(id, 'outlining')
      try {
        // 僵尸恢复循环：409 表示后台仍在生成，转为订阅；看门狗超时说明后台丢失，重新 POST 触发
        for (let attempt = 0; attempt < 5 && this.activeTaskId === id; attempt++) {
          if (!(attempt === 0 && resumeWatching)) {
            try {
              await api.regenerateStoryboardOutline(id)
            } catch (error) {
              if (!(error instanceof ApiError && error.status === 409)) throw error
            }
          }
          if (await this._watchOutline(id)) break
        }
        if (this.activeTaskId !== id) return
        // 终态后全量刷新（storyBible 含 failedSegments，行含最新大纲规划）
        const fresh = await api.fetchSongScript(id)
        if (this.activeTaskId !== id) return
        this.activeStoryBible = fresh.storyBible ?? null
        this.castIds = [...fresh.cast]
        this.lines = fresh.lines
        this._setTaskStatus(id, fresh.status)
        if (fresh.status === 'outline_failed' || fresh.status === 'outlining') {
          if (fresh.status === 'outlining') this._setTaskStatus(id, 'outline_failed')
          this.outlineError =
            // SSE 回调中的赋值对 TS 控制流分析不可见，需显式还原类型
            (this.outlineProgress as OutlineProgress | null)?.error ||
            (fresh.status === 'outlining' ? '大纲生成超时，请重试' : '大纲生成失败，请重试')
          return
        }
        // 段级失败的行保持占位标注，不进入逐句生成队列（由段级重试恢复）
        const readyIds = fresh.lines
          .filter((line) => line.shotOptions?.outlineStatus !== 'failed')
          .map((line) => line.id)
        if (readyIds.length) void this._generateStoryboardQueue(id, readyIds)
      } catch (error) {
        this._setTaskStatus(id, 'outline_failed')
        this.outlineError = error instanceof Error ? error.message : '大纲生成失败'
      } finally {
        this.outlineLoading = false
        if (this.outlineTaskId === id) this.outlineTaskId = null
      }
    },

    async regenerateOutline() {
      await this.runOutlineGeneration()
    },

    /** 段级大纲重试：仅重跑指定场景段的第二轮生成，保留其他段成果 */
    async retryOutlineSegment(sceneIndex: number) {
      const taskId = this.activeTaskId
      if (!taskId || this.activeStoryboardType !== 'ass' || this.segmentRetrying[sceneIndex]) return
      this.segmentRetrying = { ...this.segmentRetrying, [sceneIndex]: true }
      try {
        // 202：后台任务已受理；409：后台已有任务在跑，转为轮询等待
        try {
          await api.regenerateStoryboardOutlineSegment(taskId, sceneIndex)
        } catch (error) {
          if (!(error instanceof ApiError && error.status === 409)) throw error
        }
        await this._pollSegmentRetry(taskId, sceneIndex)
        // 后台完成后全量刷新
        const fresh = await api.fetchSongScript(taskId)
        if (this.activeTaskId === taskId && fresh.storyBible)
          this.activeStoryBible = fresh.storyBible
        // 重试成功的行进入逐句生成队列
        const retriedLineIds = fresh.lines
          .filter((line) => line.shotOptions?.outlineStatus !== 'failed')
          .map((line) => line.id)
        // 只提交那些还没在生成中的行
        const newIds = retriedLineIds.filter(
          (id) =>
            !this.lines.find((line) => line.id === id)?.generationStatus ||
            this.lines.find((line) => line.id === id)?.generationStatus === 'pending',
        )
        if (newIds.length) void this._generateStoryboardQueue(taskId, newIds)
      } catch (error) {
        reportApiError(error, '场景段大纲重新生成失败')
      } finally {
        this.segmentRetrying = { ...this.segmentRetrying, [sceneIndex]: false }
      }
    },

    /** 轮询等待段级重试完成后返回（最多 5 分钟） */
    async _pollSegmentRetry(taskId: string, sceneIndex: number): Promise<void> {
      const deadline = Date.now() + 300_000
      while (Date.now() < deadline && this.activeTaskId === taskId) {
        const fresh = await api.fetchSongScript(taskId).catch(() => null)
        if (!fresh || this.activeTaskId !== taskId) return
        const progress = fresh.outlineProgress as
          { phase?: string; sceneIndex?: number; error?: string } | undefined
        if (progress?.phase === 'segment_retry_failed') {
          throw new Error(progress.error || '场景段大纲重新生成失败')
        }
        // outlineProgress 被清掉或 phase 不是 segment_retry 说明任务已结束
        if (!progress || progress.phase !== 'segment_retry' || progress.sceneIndex !== sceneIndex) {
          return
        }
        await new Promise((resolve) => setTimeout(resolve, 2000))
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

    /** 拖拽排序：项目 */
    async reorderSongProjects(order: string[]) {
      const prev = [...this.songProjects]
      this.songProjects = order
        .map((id) => this.songProjects.find((s) => s.id === id)!)
        .filter(Boolean)
      try {
        await api.reorderProjects(order)
      } catch {
        this.songProjects = prev
      }
    },

    /** 拖拽排序：子项目 */
    async reorderSongTasks(songId: string, order: string[]) {
      const song = this.songProjects.find((s) => s.id === songId)
      if (!song) return
      const prev = [...song.tasks]
      song.tasks = order.map((id) => song.tasks.find((t) => t.id === id)!).filter(Boolean)
      try {
        await api.reorderProjectTasks(songId, order)
      } catch {
        song.tasks = prev
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
      if (this.activeTaskId)
        void api
          .createStoryboardLine(this.activeTaskId, {
            source: 'manual',
            lyrics: '',
            scene_prompt: '',
            shot_prompt: '',
            digital_human_ids: [],
          })
          .then((saved) => {
            line.id = saved.id
            this.selectedLineId = saved.id
          })
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
      if (line) {
        line.lyrics = lyrics
        void api.updateStoryboardLine(lineId, { lyrics })
      }
    },

    updateScenePrompt(lineId: string, scenePrompt: string) {
      const line = this.lines.find((l) => l.id === lineId)
      if (line) {
        line.scenePrompt = scenePrompt
        void api.updateStoryboardLine(lineId, { scene_prompt: scenePrompt })
      }
    },

    updateShotPrompt(lineId: string, shotPrompt: string) {
      const line = this.lines.find((l) => l.id === lineId)
      if (line) {
        line.shotPrompt = shotPrompt
        void api.updateStoryboardLine(lineId, { shot_prompt: shotPrompt })
      }
    },

    /** 更新分镜视频生成参数（清晰度 / 时长 / 画幅） */
    updateShotOptions(lineId: string, options: ShotGenOptions) {
      const line = this.lines.find((l) => l.id === lineId)
      if (line) {
        const normalized = normalizeShotOptions(options)
        line.shotOptions = normalized
        void api.updateStoryboardLine(lineId, { shot_options: normalized })
      }
    },

    /** 切换某分镜的出演角色（只能选全局阵容内的数字人，可多选/可全不选） */
    toggleLineHuman(lineId: string, digitalHumanId: string) {
      const line = this.lines.find((l) => l.id === lineId)
      if (!line || !this.castIds.includes(digitalHumanId)) return
      const idx = line.digitalHumanIds.indexOf(digitalHumanId)
      idx >= 0 ? line.digitalHumanIds.splice(idx, 1) : line.digitalHumanIds.push(digitalHumanId)
      void api.updateStoryboardLine(lineId, { digital_human_ids: line.digitalHumanIds })
    },

    moveLine(fromIndex: number, toIndex: number) {
      if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) return
      const [moved] = this.lines.splice(fromIndex, 1)
      this.lines.splice(toIndex, 0, moved)
      if (this.activeTaskId)
        void api.reorderStoryboardLines(
          this.activeTaskId,
          this.lines.map((line) => line.id),
        )
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
      if (this.activeTaskId) void api.updateTaskCast(this.activeTaskId, this.castIds)
      this.lines.forEach(
        (line) =>
          void api.updateStoryboardLine(line.id, { digital_human_ids: line.digitalHumanIds }),
      )
    },

    /** 数字人落库：确保风格存在 → 创建记录 → 更新本地列表（AI 生成 / 自定义上传 / 刷新恢复共用） */
    async _finalizeDigitalHuman(input: {
      name: string
      style: string
      description: string
      avatar: string
      thumbnail?: string
      avatarPrompt: string
      source: 'uploaded' | 'generated'
      styleId?: string
    }): Promise<DigitalHuman> {
      let styleId = input.styleId ?? this.dhStyleIds[input.style]
      if (!styleId) {
        const style = await api.createDigitalHumanStyle(input.style)
        styleId = style.id
        this.dhStyleIds[input.style] = style.id
        if (!this.dhStyles.includes(input.style)) this.dhStyles.push(input.style)
      }
      const dh = await api.createDigitalHuman({
        name: input.name,
        styleId,
        description: input.description,
        avatar: input.avatar,
        thumbnail: input.thumbnail,
        avatarPrompt: input.avatarPrompt,
        source: input.source,
      })
      const existing = this.digitalHumans.findIndex((item) => item.id === dh.id)
      if (existing >= 0) this.digitalHumans.splice(existing, 1, dh)
      else this.digitalHumans.push(dh)
      this.ensureDhStyle(dh.style)
      return dh
    },

    /** 刷新/重开后恢复上次未完成的数字人生成：任务还在跑则恢复等待态续跑，已跑完则直接补建落库 */
    async resumePendingDigitalHuman() {
      const draft = readPendingDhDraft()
      if (!draft) return
      this.dhGenerating = true
      try {
        const generated = await imageGen.waitForImageAsset(draft.jobId)
        await this._finalizeDigitalHuman({
          name: draft.name,
          style: draft.style,
          description: draft.description,
          avatar: generated.url,
          thumbnail: generated.thumbnailUrl,
          avatarPrompt: imageGen.buildPortraitPrompt(draft.description || draft.name, draft.style),
          source: draft.mode,
          styleId: draft.styleId,
        })
      } catch (error) {
        reportApiError(error, '数字人生成失败')
      } finally {
        clearPendingDhDraft()
        this.dhGenerating = false
      }
    },

    /** 调用真实异步生图接口生成数字人形象，图片本地化存储后加入资产库 */
    async generateDigitalHuman(input: {
      name: string
      style: string
      description: string
      referenceImage?: string
    }): Promise<DigitalHuman> {
      this.dhGenerating = true
      try {
        const prompt = imageGen.buildPortraitPrompt(input.description, input.style)
        const id = nextId('dh')
        const template = imageGen.getTemplateAvatar()
        const userRef =
          input.referenceImage || this.digitalHumans.find((human) => human.readOnly)?.avatar
        const references = [template, userRef].filter(Boolean) as string[]
        const generated = await imageGen.generateImageAsset(
          prompt,
          {
            size: '1344x768',
            quality: 'medium',
            ...(references.length ? { image: references } : {}),
          },
          // 任务创建后先留草稿：页面刷新后可据此恢复等待态并补建数字人
          (jobId) =>
            savePendingDhDraft({
              mode: 'generated',
              jobId,
              name: input.name,
              style: input.style,
              description: input.description,
            }),
        )
        const avatar = await imageGen.localizeImage(id, generated.url)
        return await this._finalizeDigitalHuman({
          name: input.name,
          style: input.style,
          description: input.description,
          avatar,
          thumbnail: generated.thumbnailUrl,
          avatarPrompt: prompt,
          source: 'generated',
        })
      } finally {
        clearPendingDhDraft()
        this.dhGenerating = false
      }
    },

    /** 上传自定义数字人：以用户自备头像为参考图生成三视图定妆照后加入资产库（名称、风格必填） */
    async addCustomDigitalHuman(input: {
      name: string
      style: string
      description?: string
      avatar: string
    }): Promise<DigitalHuman> {
      this.dhGenerating = true
      this.dhGeneratingPhase = 'uploading'
      try {
        let styleId = this.dhStyleIds[input.style]
        if (!styleId) {
          const style = await api.createDigitalHumanStyle(input.style)
          styleId = style.id
          this.dhStyleIds[input.style] = style.id
          if (!this.dhStyles.includes(input.style)) this.dhStyles.push(input.style)
        }
        const prompt = imageGen.buildPortraitPrompt(input.description || input.name, input.style)
        const reference = await api.uploadDataUrl(input.avatar, `${nextId('reference')}.jpg`)
        this.dhGeneratingPhase = 'generating'
        const template = imageGen.getTemplateAvatar()
        const generated = await imageGen.generateImageAsset(
          prompt,
          {
            size: '1344x768',
            quality: 'medium',
            image: template ? [template, reference.url] : reference.url,
          },
          (jobId) =>
            savePendingDhDraft({
              mode: 'uploaded',
              jobId,
              name: input.name,
              style: input.style,
              description: input.description ?? '',
              styleId,
            }),
        )
        return await this._finalizeDigitalHuman({
          name: input.name,
          style: input.style,
          description: input.description ?? '',
          avatar: generated.url,
          thumbnail: generated.thumbnailUrl,
          avatarPrompt: prompt,
          source: 'uploaded',
          styleId,
        })
      } finally {
        clearPendingDhDraft()
        this.dhGenerating = false
        this.dhGeneratingPhase = ''
      }
    },

    // ---------- 风格分类增删改查 ----------
    /** 登记某风格到分类列表（生成/上传/编辑数字人使用新风格时自动登记） */
    ensureDhStyle(style: string) {
      const s = style.trim()
      if (!s || this.dhStyles.includes(s)) return
      this.dhStyles.push(s)
      void api.createDigitalHumanStyle(s).then((item) => {
        this.dhStyleIds[s] = item.id
      })
    },

    /** 新增风格分类；名称为空或已存在时返回 false */
    addDhStyle(name: string): boolean {
      const s = name.trim()
      if (!s || s === '全部' || this.allDhStyles.includes(s)) return false
      this.dhStyles.push(s)
      void api.createDigitalHumanStyle(s).then((item) => {
        this.dhStyleIds[s] = item.id
      })
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
      if (touched)
        this.digitalHumans
          .filter((d) => d.style === s && !d.readOnly)
          .forEach((d) => void api.updateDigitalHuman(d.id, { style_id: this.dhStyleIds[s] }))
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
      const styleId = this.dhStyleIds[name]
      if (styleId) void api.deleteDigitalHumanStyle(styleId)
    },

    /** 编辑数字人基础信息 / 提示词 */
    updateDigitalHuman(
      id: string,
      patch: Partial<Pick<DigitalHuman, 'name' | 'style' | 'description' | 'avatarPrompt'>>,
    ) {
      const dh = this.digitalHumans.find((d) => d.id === id)
      if (!dh || dh.readOnly) return
      Object.assign(dh, patch)
      if (!dh.readOnly)
        void api.updateDigitalHuman(id, {
          name: patch.name,
          style_id: patch.style ? this.dhStyleIds[patch.style] : undefined,
          description: patch.description,
          avatar_prompt: patch.avatarPrompt,
        })
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
    },

    /** 用（可能已修改的）提示词重新生成数字人形象，成功后本地化存储并替换头像 */
    async regenerateDigitalHumanAvatar(id: string, prompt?: string): Promise<void> {
      const dh = this.digitalHumans.find((d) => d.id === id)
      if (!dh || this.dhRegeneratingId) return
      this.dhRegeneratingId = id
      try {
        const finalPrompt = (
          prompt ??
          dh.avatarPrompt ??
          imageGen.buildPortraitPrompt(dh.description, dh.style)
        ).trim()
        const template = imageGen.getTemplateAvatar()
        const dhRef = dh.avatar
        const references = [template, dhRef].filter(Boolean) as string[]
        const generated = await imageGen.generateImageAsset(finalPrompt, {
          size: '1344x768',
          quality: 'medium',
          ...(references.length ? { image: references } : {}),
        })
        dh.avatar = generated.thumbnailUrl || generated.url
        dh.originalAvatar = generated.url
        dh.avatarPrompt = finalPrompt
        if (!dh.readOnly)
          await api.updateDigitalHuman(id, {
            avatar_url: generated.url,
            avatar_thumbnail_url: generated.thumbnailUrl,
            avatar_prompt: finalPrompt,
          })
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
          shotOptions: normalizeShotOptions(
            item.shotOptions ?? {
              ...DEFAULT_SHOT_OPTIONS,
              duration: item.plannedDuration ?? DEFAULT_SHOT_OPTIONS.duration,
              ratio: req.ratio,
              resolution: req.resolution,
              imageModel: req.imageModel,
              videoModel: req.videoModel,
            },
          ),
          generationStatus: item.generationStatus || 'pending',
        }))
        this._cacheCurrentTask()
        let song = this.songProjects.find((s) => s.id === this.activeSongId)
        if (!song) {
          song = {
            id: nextId('song'),
            name: [req.genre, req.secondaryCategory].filter(Boolean).join('·') || '未命名歌曲',
            tasks: [],
          }
          this.songProjects.push(song)
          this.activeSongId = song.id
        }
        const task = {
          id: result.taskId,
          title: result.title,
          updatedAt: '刚刚',
          status: 'generating',
          storyboardType: 'general',
        }
        song.tasks.push(task)
        this.stop()
        this.editingLineId = null
        this.castIds = [...result.cast]
        this.lines = lines
        this.taskScripts[task.id] = { cast: this.castIds, lines: this.lines }
        this.activeTaskId = task.id
        this.activeStoryBible =
          (result as typeof result & { storyboardConfig?: { storyBible?: StoryBible } })
            .storyboardConfig?.storyBible ?? null
        this.activeStoryboardType = 'general'
        this.activeTaskStatus = 'generating'
        this.selectedLineId = this.lines[0]?.id ?? null
        this.currentTime = 0
        this.generalStoryboardOpen = false
        void this._generateStoryboardQueue(
          task.id,
          lines.map((line) => line.id),
        )
      } catch (err) {
        this.generalStoryboardError = err instanceof Error ? err.message : '通用 MV 视频生成失败'
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
          id: item.id || nextId(),
          source: 'ass',
          shotType: item.shotType,
          plannedDuration: item.plannedDuration,
          start: item.start,
          end: item.end,
          lyrics: item.lyrics,
          scenePrompt: item.scenePrompt,
          shotPrompt: item.shotPrompt,
          digitalHumanIds: [...item.digitalHumanIds],
          voice: { status: 'none' },
          scene: { status: 'none' },
          shot: { status: 'none', assets: [] },
          shotOptions: normalizeShotOptions(
            item.shotOptions ?? {
              ...DEFAULT_SHOT_OPTIONS,
              duration: item.plannedDuration ?? DEFAULT_SHOT_OPTIONS.duration,
              ratio: req.ratio,
              resolution: req.resolution,
              imageModel: req.imageModel,
              videoModel: req.videoModel,
            },
          ),
          generationStatus: item.generationStatus || 'pending',
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
        const task = {
          id: script.taskId,
          title: script.title,
          updatedAt: '刚刚',
          status: script.status || 'parsed',
          storyboardType: 'ass',
        }
        song.tasks.push(task)
        // 载入生成结果到新子项目
        this.stop()
        this.editingLineId = null
        this.castIds = [...script.cast]
        this.lines = lines
        this.taskScripts[task.id] = { cast: this.castIds, lines: this.lines }
        this.activeTaskId = task.id
        this.activeStoryBible =
          (script as typeof script & { storyBible?: StoryBible }).storyBible ?? null
        this.activeStoryboardType = 'ass'
        this.activeTaskStatus = script.status || 'parsed'
        this.selectedLineId = this.lines[0]?.id ?? null
        this.currentTime = 0
        this.magicOpen = false
        // 两阶段流程：上传仅完成时间轴拆分（parsed），自动接续大纲生成；大纲成功后再启动逐句提示词生成
        void this.runOutlineGeneration(task.id)
      } catch (err) {
        this.magicError = err instanceof Error ? err.message : 'ASS 视频生成失败'
      } finally {
        this.magicLoading = false
      }
    },

    async generateVoiceFor(lineId: string) {
      const line = this.lines.find((l) => l.id === lineId)
      if (!line || line.voice.status === 'generating') return
      line.voice.status = 'generating'
      const { url, duration } = await generateVoice(lineId)
      // 生成期间行可能被删除
      const still = this.lines.find((l) => l.id === lineId)
      if (still) still.voice = { status: 'done', url, duration }
    },

    /** 生成/重新生成场景底图（仅由场景提示词决定） */
    async generateSceneFor(lineId: string, scenePrompt?: string, selectedOptions?: ShotGenOptions) {
      const idx = this.lines.findIndex((l) => l.id === lineId)
      if (idx < 0 || this.lines[idx].scene.status === 'generating') return
      const line = this.lines[idx]
      if (scenePrompt !== undefined) line.scenePrompt = scenePrompt
      if (selectedOptions) line.shotOptions = normalizeShotOptions(selectedOptions)
      line.scene.status = 'generating'
      line.scene.error = undefined
      const variant = sceneVariants[lineId] ?? 0
      sceneVariants[lineId] = variant + 1
      try {
        const options = normalizeShotOptions(line.shotOptions ?? DEFAULT_SHOT_OPTIONS)
        const { imageUrl, thumbnailUrl } = await api.generateSceneImage(
          line.scenePrompt,
          idx,
          variant,
          this.activeTaskId ?? undefined,
          lineId,
          options.ratio,
          options.imageModel,
          options.resolution,
        )
        const still = this.lines.find((l) => l.id === lineId)
        if (still)
          still.scene = {
            status: 'done',
            imageUrl: thumbnailUrl || imageUrl,
            originalImageUrl: imageUrl,
          }
      } catch (error) {
        // 失败状态与原因留在行内（可重试），全局弹窗只做即时反馈；不再 throw，
        // 避免 fire-and-forget 调用产生 unhandled rejection、批量生成被单行失败中断
        const reported = reportApiError(error, '场景图生成失败')
        const still = this.lines.find((l) => l.id === lineId)
        if (still) {
          still.scene.status = 'failed'
          still.scene.error = reported.message
        }
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
      line.shot.error = undefined
      const variant = line.shot.assets.length
      const characterUrls = line.digitalHumanIds
        .map((id) => this.digitalHumans.find((h) => h.id === id)?.avatar)
        .filter(Boolean) as string[]
      try {
        const { coverUrl, coverThumbnailUrl, videoUrl, duration } = await api.generateShotVideo(
          line.scenePrompt,
          line.shotPrompt,
          characterUrls,
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
          still.shot.error = undefined
        }
      } catch (error) {
        // 同场景图：失败原因入行内状态，不 throw（保留已有资产封面，重试由行内/详情弹窗发起）
        const reported = reportApiError(error, '视频生成失败')
        const still = this.lines.find((l) => l.id === lineId)
        if (still) {
          still.shot.status = 'failed'
          still.shot.error = reported.message
        }
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
          if (line.source !== 'general' && line.voice.status !== 'done')
            await this.generateVoiceFor(line.id)
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
      this.exportsByTaskId[item.taskId] = next.sort((left, right) =>
        right.createdAt.localeCompare(left.createdAt),
      )
    },

    async _watchMaterialExport(item: MaterialExport) {
      if (!item.jobId || exportStreams.has(item.id) || ['ready', 'failed'].includes(item.status))
        return
      const controller = new AbortController()
      exportStreams.set(item.id, controller)
      try {
        for (let attempt = 0; attempt < 4 && !controller.signal.aborted; attempt += 1) {
          try {
            await api.streamMaterialExport(
              item.id,
              (update) => this._upsertMaterialExport(update),
              controller.signal,
            )
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
        items
          .filter((item) => ['queued', 'running'].includes(item.status))
          .forEach((item) => void this._watchMaterialExport(item))
      } catch (error) {
        reportApiError(error, '导出任务恢复失败')
      }
    },

    async runSynthesize() {
      if (
        ['queued', 'running'].includes(this.synthesis.status) ||
        !this.hasVideoAssets ||
        !this.activeTaskId
      )
        return
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
