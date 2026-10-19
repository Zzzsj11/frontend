import type {
  CreativeReferenceMedia,
  DigitalHuman,
  GeneralStoryboardOptions,
  GeneralStoryboardRequest,
  RandomGeneralStoryboardRequest,
  MaterialExport,
  OutlineFailedSegment,
  OutlinePlannedLine,
  OutlineProgress,
  ProjectAudio,
  ScriptLine,
  ShotGenOptions,
  SongProject,
  StoryBible,
  SynthesisState,
  TimelineClip,
} from '../../types'
import * as api from '../../api/domain'

export type ProjectState = {
  lines: ScriptLine[]
  digitalHumans: DigitalHuman[]
  /** 风格分类列表（支持增删改查，空分类也会保留） */
  dhStyles: string[]
  dhStyleIds: Record<string, string>
  systemDhStyles: string[]
  /** 歌曲项目列表（左侧任务栏：一个目录处理一首歌曲） */
  songProjects: SongProject[]
  songProjectsLoading: boolean
  songProjectsError: string | null
  /** 当前打开的歌曲项目 id */
  activeSongId: string
  /** 当前选中的处理任务 id */
  activeTaskId: string | null
  /** 正在切换歌曲（载入脚本中） */
  songSwitching: boolean
  /** 子任务载入序号：较早请求即使后返回，也不得覆盖较新的切换结果 */
  taskLoadVersion: number
  /** 工作区数据属主用户 id：loadSongProjects 发现账号变化时先清空上一账号现场 */
  ownerUserId: string
  /** 各子项目(任务)的脚本编辑现场缓存(按 taskId)，切回时不丢编辑状态 */
  taskScripts: Record<
    string,
    {
      cast: string[]
      lines: ScriptLine[]
    }
  >
  /** 全局角色阵容：本 MV 选定的数字人（全片统一），分镜只能从阵容中挑选出演角色 */
  castIds: string[]
  selectedLineId: string | null
  /** 当前在弹窗中编辑的分镜行 */
  editingLineId: string | null
  /** 打开分镜编辑弹窗时默认展开的选项 */
  editingTab: 'cast' | 'shot' | 'scene' | null
  /** 资产库（角色阵容管理）弹窗开关 */
  libraryOpen: boolean
  /** AI 魔法脚本弹窗开关 */
  magicOpen: boolean
  /** 创意视频创建弹窗开关。 */
  creativeOpen: boolean
  magicError: string | null
  /** 通用分镜参数弹窗 */
  generalStoryboardOpen: boolean
  generalStoryboardLoading: boolean
  generalStoryboardError: string | null
  generalStoryboardOptions: GeneralStoryboardOptions | null
  randomGeneralStoryboardOpen: boolean
  randomGeneralStoryboardLoading: boolean
  randomGeneralStoryboardError: string | null
  outlineOpen: boolean
  outlineLoading: boolean
  /** 大纲生成中的任务归属：全局 outlineLoading 不区分任务，切到其他子项目时
   *  该任务自己的弹窗/按钮不能被别人的生成状态锁死，用 outlineTaskId 隔离 */
  outlineTaskId: string | null
  outlineError: string | null
  /** 大纲后台生成进度（SSE 推送：planning/segments 阶段与场景段计数） */
  outlineProgress: OutlineProgress | null
  /** 大纲本轮开始时间戳（ms），用于前端正向计时器 */
  outlineStartedAt: number
  activeStoryBible: StoryBible | null
  activeStoryboardType: string | null
  /** 当前任务状态（parsed/outlining/outline_failed/generating/ready/partial/failed） */
  activeTaskStatus: string | null
  activeStoryboardConfig: Record<string, unknown>
  taskVideoModelEditing: boolean
  /** 当前歌曲项目的整首审核音轨。 */
  projectAudio: ProjectAudio | null
  audioTrackVisible: boolean
  audioOffsetSeconds: number
  /** 正在重试的场景段序号（段级大纲重新生成） */
  segmentRetrying: Record<number, boolean>
  currentTime: number
  /** 正在拖动时间轴/进度条：主时钟暂停视频回写（避免拖动被弹回），video 回设走节流 */
  scrubbing: boolean
  isPlaying: boolean
  playMode: {
    single: boolean
    loop: boolean
  }
  volume: number
  muted: boolean
  batchVoicing: boolean
  batchShooting: boolean
  magicLoading: boolean
  /** 正在调用真实生图接口生成数字人形象 */
  dhGenerating: boolean
  /** 当前阶段：uploading / generating */
  dhGeneratingPhase: string
  /** 编辑弹窗中正在重新生成形象的数字人 id（null 表示空闲） */
  dhRegeneratingId: string | null
  exportsByTaskId: Record<string, MaterialExport[]>
  exportSubmitting: Record<string, boolean>
  exportConnectionIssues: Record<string, boolean>
}

export type ProjectGetters = {
  readonly lineDuration: (line: ScriptLine) => number
  readonly timelineClips: TimelineClip[]
  readonly totalDuration: number
  readonly selectedLine: ScriptLine | undefined
  readonly selectedClip: TimelineClip | undefined
  readonly currentClip: TimelineClip | undefined
  readonly currentLine: ScriptLine | undefined
  readonly editingLine: ScriptLine | undefined
  readonly digitalHumanOf: (id?: string) =>
    | {
        id: string
        name: string
        style: string
        avatar: string
        originalAvatar?: string | undefined
        assetAvatarUrl?: string | undefined
        providerAssetAvatarUrls?:
          | {
              yinghe?: string | undefined
            }
          | undefined
        description: string
        avatarPrompt?: string | undefined
        scope?: 'system' | 'private' | undefined
        readOnly?: boolean | undefined
        styleId?: string | undefined
        assetCode?: string | undefined
        gender?: string | undefined
        ageDescription?: string | undefined
        appearanceStyle?: string | undefined
        clothingDescription?: string | undefined
        suitableMusicStyles?: string | undefined
        systemPrompt?: string | undefined
      }
    | undefined
  readonly allDhStyles: string[]
  readonly castHumans: DigitalHuman[]
  readonly lineHumans: (line: ScriptLine) => DigitalHuman[]
  readonly coverOf: (line: ScriptLine) => string | undefined
  readonly videoOf: (line: ScriptLine) => string | undefined
  readonly translationOf: (line: ScriptLine) => string | undefined
  readonly hasVideoAssets: boolean
  readonly synthesis: SynthesisState
  readonly storyboardProgress: {
    total: number
    completed: number
    failed: number
    active: boolean
  }
  readonly outlineLocked: boolean
  readonly outlinePhase: 'none' | 'pending' | 'outlining' | 'failed'
  readonly failedOutlineSegments: OutlineFailedSegment[]
  readonly playRange: {
    start: number
    end: number
  }
}

export type ProjectActions = {
  /** 载入歌曲项目列表（侧边栏挂载时调用） */
  loadSongProjects(): Promise<void>
  /** 新建歌曲项目并加入列表 */
  createSongProject(name: string): Promise<SongProject>
  /** 生成类操作前置：未选中任何项目时自动创建「未命名项目」（每次新建，允许重名） */
  ensureSongProjectForGeneration(): Promise<void>
  /** 登出/账号切换时清空工作区现场：取消全部轮询与 SSE 后重置状态，防止串号残留 */
  resetWorkspace(): void
  /** 把当前子项目(任务)的编辑现场写入缓存 */
  _cacheCurrentTask(): void
  /** 载入指定子项目(任务)的脚本到编辑区（不负责缓存当前，调用方自行处理） */
  _loadTask(songId: string, taskId: string | null): Promise<void>
  /** 行的大纲是否已就绪（未就绪的行不能进入逐句生成，后端会 422） */
  _outlineReady(line: ScriptLine): boolean
  _generateStoryboardQueue(taskId: string, lineIds: string[], force?: boolean): Promise<void>
  /** 一次性将整批提示词工单交给服务端，浏览器只负责等待持久化工单落定。 */
  _generateStoryboardBatch(taskId: string, lineIds: string[], force?: boolean): Promise<void>
  retryStoryboardLine(lineId: string): Promise<void>
  /** 只同步已有提示词工单，不创建新任务，也不会再次调用模型。 */
  refreshStoryboardLineGenerationStatus(
    lineId: string,
  ): Promise<'queued' | 'running' | 'succeeded' | 'failed'>
  retryFailedStoryboardLines(): Promise<void>
  /** 批量生成：一次提交最多100条持久工单，执行并发由 storyboard worker 统一控制。 */
  generateAllPendingStoryboardLines(): Promise<void>
  /** 刷新/切任务后恢复仍在排队或执行中的媒体生成（场景图/视频）等待态；结果由后端落库，落定后重新拉取合并 */
  resumeActiveGenerations(taskId: string): Promise<void>
  _watchGenerationJob(
    taskId: string,
    jobId: string,
    lineId: string,
    kind: 'image' | 'video',
  ): Promise<void>
  /** 懒加载某行的完整视频资产历史（详情弹窗打开时调用；脚本载入默认只带当前选用资产） */
  ensureShotHistory(lineId: string): Promise<void>
  /** 刷新前被中断的逐句提示词生成：后端孤儿请求仍会跑完并落库，轮询任务直至行状态落定后合并 */
  _watchRunningStoryboardLines(taskId: string): Promise<void>
  openOutline(): void
  closeOutline(): void
  /** 同步任务状态到当前编辑区与侧边栏任务列表 */
  _setTaskStatus(taskId: string, status: string): void
  /** 把大纲规划结果回填到行：镜头类型/人物/时长/参数，清空旧提示词等待逐句生成 */
  _applyOutlineLines(plannedLines: OutlinePlannedLine[]): void
  /**
   * 订阅大纲生成进度 SSE；返回 true=已到达终态，false=看门狗超时（进度长时间无更新，需重新触发）。
   * 服务端只在 status 离开 outlining 后关闭流；僵尸任务（后台丢失）时流不会关闭，由看门狗兜底。
   */
  _watchOutline(taskId: string): Promise<'completed' | 'timeout' | 'navigation-cancelled'>
  /** 分镜大纲生成（ASS 上传后自动调用 / 通用分镜创建后自动调用 / 失败后手动重试）：202 受理 + SSE 进度；成功后自动接续逐句提示词生成 */
  runOutlineGeneration(taskId?: string): Promise<void>
  /** 批量定制通用分镜的非当前子项目：启动大纲、等待落库，再接续逐镜提示词。 */
  _runSiblingGeneralStoryboard(taskId: string): Promise<void>
  regenerateOutline(): Promise<void>
  /** 段级大纲重试：仅重跑指定场景段的第二轮生成，保留其他段成果 */
  retryOutlineSegment(sceneIndex: number): Promise<void>
  /** 轮询等待段级重试完成后返回（最多 5 分钟）；切换子项目时随 watcher 立即停止 */
  _pollSegmentRetry(taskId: string, sceneIndex: number): Promise<void>
  /** 切换到某歌曲的处理任务(子项目)：每个任务是独立脚本，当前编辑现场先写入缓存 */
  selectSongTask(songId: string, taskId?: string | null): Promise<void>
  /** 重命名歌曲项目(目录) */
  renameSongProject(songId: string, name: string): void
  /** 删除歌曲项目(目录)：连同其下所有子项目与脚本缓存；删除激活项时切到其余首个任务 */
  deleteSongProject(songId: string): Promise<void>
  /** 拖拽排序：项目 */
  reorderSongProjects(order: string[]): Promise<void>
  /** 拖拽排序：子项目 */
  reorderSongTasks(songId: string, order: string[]): Promise<void>
  /** 重命名子项目(任务) */
  renameSongTask(songId: string, taskId: string, title: string): void
  /** 删除子项目(任务)：删除激活任务时切到同歌曲相邻任务，否则清空编辑区 */
  deleteSongTask(songId: string, taskId: string): Promise<void>
  addLine(): void
  addCreativeLine(input: {
    originalPrompt: string
    optimizedPrompt: string
    referenceMedia: CreativeReferenceMedia[]
    optimizerProvider: 'gemini' | 'minimax'
    optimizationTaskId?: string
    options: ShotGenOptions
  }): Promise<ScriptLine>
  removeLine(lineId: string): void
  updateLyrics(lineId: string, lyrics: string): void
  updateScenePrompt(lineId: string, scenePrompt: string): void
  updateShotPrompt(lineId: string, shotPrompt: string): void
  persistManualPrompt(lineId: string, input: Record<string, unknown>): Promise<void>
  updateCreativePrompts(lineId: string, originalPrompt: string, optimizedPrompt: string): void
  /** 更新分镜视频生成参数（清晰度 / 时长 / 画幅） */
  updateShotOptions(lineId: string, options: ShotGenOptions): void
  applyTaskVideoModel(plan: api.TaskVideoModelPlan): Promise<api.TaskVideoModelPlan>
  /** 切换某分镜的出演角色（只能选全局阵容内的数字人，可多选/可全不选） */
  toggleLineHuman(lineId: string, digitalHumanId: string): void
  moveLine(fromIndex: number, toIndex: number): void
  selectLine(lineId: string): void
  /** 从提示词缩略图定位对应时间轴片段，并立即从片段起点播放。 */
  playLineFromStart(lineId: string): void
  openEditor(lineId: string, tab?: 'cast' | 'shot' | 'scene' | null): void
  closeEditor(): void
  openLibrary(): void
  closeLibrary(): void
  /** 加入/移出全局角色阵容；移出时同步从所有分镜的出演角色中移除，保证全局统一 */
  toggleCast(digitalHumanId: string): void
  /** 数字人落库：确保风格存在 → 创建记录 → 更新本地列表（AI 生成 / 自定义上传 / 刷新恢复共用） */
  _finalizeDigitalHuman(input: {
    name: string
    style: string
    description: string
    avatar: string
    thumbnail?: string
    avatarPrompt: string
    source: 'uploaded' | 'generated'
    styleId?: string
  }): Promise<DigitalHuman>
  /** 刷新/重开后恢复上次未完成的数字人生成：任务还在跑则恢复等待态续跑，已跑完则直接补建落库 */
  resumePendingDigitalHuman(): Promise<void>
  /** 调用真实异步生图接口生成数字人形象，图片本地化存储后加入资产库 */
  generateDigitalHuman(input: {
    name: string
    style: string
    description: string
    referenceImage?: string
  }): Promise<DigitalHuman>
  addCustomDigitalHuman(input: {
    name: string
    style: string
    description?: string
    avatar?: string
  }): Promise<DigitalHuman>
  /** 登记某风格到分类列表（生成/上传/编辑数字人使用新风格时自动登记） */
  ensureDhStyle(style: string): void
  /** 新增风格分类；名称为空或已存在时返回 false */
  addDhStyle(name: string): boolean
  /** 重命名风格分类：同步更新该分类下所有数字人；目标名已存在时合并到该分类 */
  renameDhStyle(oldName: string, newName: string): boolean
  /** 删除风格分类：该分类下的数字人归入「未分类」 */
  deleteDhStyle(name: string): void
  /** 编辑数字人基础信息 / 提示词 */
  updateDigitalHuman(
    id: string,
    patch: Partial<Pick<DigitalHuman, 'name' | 'style' | 'description' | 'avatarPrompt'>>,
  ): void
  /** 删除数字人：同步从全局阵容与所有分镜出演角色中移除 */
  deleteDigitalHuman(id: string): void
  /** 用（可能已修改的）提示词重新生成数字人形象，成功后本地化存储并替换头像 */
  regenerateDigitalHumanAvatar(id: string): Promise<void>
  openMagic(): void
  closeMagic(): void
  openCreative(): void
  closeCreative(): void
  openGeneralStoryboard(): Promise<void>
  closeGeneralStoryboard(): void
  openRandomGeneralStoryboard(): Promise<void>
  closeRandomGeneralStoryboard(): void
  /** 按曲风、人物与镜头规模生成无歌词的通用分镜脚本 */
  runGeneralStoryboard(req: GeneralStoryboardRequest): Promise<void>
  /** 无大纲、无场景图：创建相同提示词的随机分镜并立即批量提交纯文本视频。 */
  runRandomGeneralStoryboard(req: RandomGeneralStoryboardRequest): Promise<void>
  /** 随机通用没有图片/人物参考，创建任务后一次性把全部纯文本视频持久化入队。 */
  _generateRandomShotsBatch(taskId: string, lines: ScriptLine[]): Promise<void>
  /** 提交魔法脚本表单：生成成功后在当前歌曲目录下新建一个子项目(任务)并载入生成的脚本 */
  runMagicScript(req?: api.MagicScriptRequest): Promise<void>
  generateVoiceFor(lineId: string): Promise<void>
  /** 生成/重新生成场景底图（仅由场景提示词决定） */
  generateSceneFor(
    lineId: string,
    scenePrompt?: string,
    selectedOptions?: ShotGenOptions,
  ): Promise<void>
  /** 生成/重新生成分镜视频片段（场景 × 分镜提示词 × 出演角色 × 生成参数）；新片段作为资产追加并选中 */
  generateShotFor(lineId: string, shotPrompt?: string, options?: ShotGenOptions): Promise<void>
  /** 从资产历史中选用某个视频片段 */
  selectShotAsset(lineId: string, assetId: string): void
  generateAllVoices(): Promise<void>
  /** 批量生成视频片段：提示词就绪且视频「未生成/失败」的行最多 200 路并发（与后端单用户上限一致）；
   *  单行失败不中断后续（失败原因入行内状态，429 单账号上限由后端兜底并统一弹窗）；
   *  「批量进行中」标记按任务持久化：刷新/切换子任务中断后，回到该任务自动续跑剩余行 */
  generateAllShots(): Promise<void>
  /** 等待某行视频生成落定（done/failed），切换子任务可立即打断；超时兜底防止等待态重建失败时卡死后续派发 */
  _awaitShotSettled(line: ScriptLine, signal?: AbortSignal): Promise<void>
  _upsertMaterialExport(item: MaterialExport): void
  _watchMaterialExport(item: MaterialExport): Promise<void>
  restoreMaterialExports(taskId: string): Promise<void>
  runSynthesize(): Promise<void>
  runExport(kind: 'materials' | 'video'): Promise<void>
  downloadLatestExport(): void
  cancelExportStreams(): void
  play(): void
  pause(): void
  togglePlay(): void
  stop(): void
  seek(time: number): void
  /** PlayerPanel 挂载/卸载视频元素时登记：播放中主时钟以视频真实进度为准 */
  registerVideoEl(el: HTMLVideoElement | null): void
  setAudioTrackVisible(visible: boolean): void
  setAudioOffset(seconds: number): void
  persistAudioTrackConfig(): Promise<void>
  clampCurrentTime(): void
  setPlayMode(key: 'single' | 'loop', value: boolean): void
}

export type ProjectContext = ProjectState & ProjectGetters & ProjectActions & { $reset(): void }
