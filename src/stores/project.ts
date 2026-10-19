import { defineStore } from 'pinia'
import type {
  DigitalHuman,
  GeneralStoryboardOptions,
  MaterialExport,
  OutlineFailedSegment,
  OutlineProgress,
  ProjectAudio,
  ScriptLine,
  SongProject,
  StoryBible,
  SynthesisState,
  TimelineClip,
} from '../types'
import { DEFAULT_CLIP_DURATION } from './project/shared'
import type { ProjectState, ProjectActions } from './project/contracts'
import { workspaceActions } from './project/workspace'
import { storyboardActions } from './project/storyboard'
import { outlineActions } from './project/outline'
import { linesActions } from './project/lines'
import { charactersActions } from './project/characters'
import { creationActions } from './project/creation'
import { mediaActions } from './project/media'
import { exportActions } from './project/export'
import { playerActions } from './project/player'
export { DEFAULT_CLIP_DURATION, DEFAULT_SHOT_OPTIONS, formatTime } from './project/shared'

export const useProjectStore = defineStore('project', {
  state: (): ProjectState => ({
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
    /** 子任务载入序号：较早请求即使后返回，也不得覆盖较新的切换结果 */
    taskLoadVersion: 0,
    /** 工作区数据属主用户 id：loadSongProjects 发现账号变化时先清空上一账号现场 */
    ownerUserId: '',
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
    /** 创意视频创建弹窗开关。 */
    creativeOpen: false,
    magicError: null as string | null,
    /** 通用分镜参数弹窗 */
    generalStoryboardOpen: false,
    generalStoryboardLoading: false,
    generalStoryboardError: null as string | null,
    generalStoryboardOptions: null as GeneralStoryboardOptions | null,
    randomGeneralStoryboardOpen: false,
    randomGeneralStoryboardLoading: false,
    randomGeneralStoryboardError: null as string | null,
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
    activeStoryboardConfig: {} as Record<string, unknown>,
    taskVideoModelEditing: false,
    /** 当前歌曲项目的整首审核音轨。 */
    projectAudio: null as ProjectAudio | null,
    audioTrackVisible: false,
    audioOffsetSeconds: 0,
    /** 正在重试的场景段序号（段级大纲重新生成） */
    segmentRetrying: {} as Record<number, boolean>,
    currentTime: 0,
    /** 正在拖动时间轴/进度条：主时钟暂停视频回写（避免拖动被弹回），video 回设走节流 */
    scrubbing: false,
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
    exportSubmitting: {} as Record<string, boolean>,
    exportConnectionIssues: {} as Record<string, boolean>,
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
      const latest = state.activeTaskId
        ? state.exportsByTaskId[state.activeTaskId]?.find((item) => item.kind !== 'video')
        : undefined
      if (!latest) return { status: 'idle', progress: 0 }
      return {
        status: latest.status,
        // 只展示后端持久化的真实进度；按时间虚拟爬升会在下一次 SSE 快照到达时产生倒退。
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
        // pending 只表示「待生成」（含 429 被还原、切任务遗留的行），不代表队列在跑；
        // 仅 running 说明统一队列正在执行——否则队列终止后残留的 pending 行会让批量生成入口永远禁用
        active: generated.some((line) => line.generationStatus === 'running'),
      }
    },

    /** 大纲加载锁：仅当「当前任务自己」正在生成大纲时为 true。
     *  outlineLoading 是全局的（别的子项目生成中也会置位），用它直接锁弹窗/按钮
     *  会把其他任务的大纲弹窗一并锁死（无法关闭），故用 outlineTaskId 归属隔离 */
    outlineLocked(state): boolean {
      return state.outlineLoading && state.outlineTaskId === state.activeTaskId
    },

    /** 大纲阶段：pending=待生成 / outlining=生成中 / failed=生成失败（ASS 与通用分镜统一） */
    outlinePhase(state): 'none' | 'pending' | 'outlining' | 'failed' {
      if (state.activeStoryboardType !== 'ass' && state.activeStoryboardType !== 'general')
        return 'none'
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
    ...workspaceActions,
    ...storyboardActions,
    ...outlineActions,
    ...linesActions,
    ...charactersActions,
    ...creationActions,
    ...mediaActions,
    ...exportActions,
    ...playerActions,
  } satisfies ProjectActions,
})
