/** 生成状态 */
import type { ImageModelId, VideoModelId } from '../generationModels'

export type GenStatus = 'none' | 'generating' | 'done' | 'failed'

/** 歌曲目录下的处理任务（一个任务 = 一次 MV 制作会话） */
export interface SongTask {
  id: string
  title: string
  /** 相对时间标注，如「刚刚」「3天」 */
  updatedAt: string
  /** 任务状态：parsed/outlining/outline_failed/generating/ready/partial/failed */
  status?: string
  storyboardType?: string
}

/** 歌曲项目（侧边栏一个目录处理一首歌曲） */
export interface SongProject {
  id: string
  /** 歌曲名 / 目录名 */
  name: string
  artist?: string
  tasks: SongTask[]
}

/** 数字人资产 */
export interface DigitalHuman {
  id: string
  name: string
  /** 风格（国风 / 赛博朋克 / 二次元 …） */
  style: string
  avatar: string
  /** TOS 原图；avatar 默认是列表缩略图。 */
  originalAvatar?: string
  description: string
  /** 生成形象时使用的完整提示词（可在编辑界面查看 / 修改后重新生成） */
  avatarPrompt?: string
  scope?: 'system' | 'private'
  readOnly?: boolean
  styleId?: string
  assetCode?: string
  gender?: string
  ageDescription?: string
  appearanceStyle?: string
  clothingDescription?: string
  suitableMusicStyles?: string
  systemPrompt?: string
}

/** 配音信息 */
export interface VoiceInfo {
  status: GenStatus
  url?: string
  /** 时长（秒） */
  duration?: number
}

/** 分镜视频片段资产（一次生成的产物） */
export interface ShotAsset {
  id: string
  /** 视频封面图 */
  coverUrl: string
  /** 视频封面原图，仅在放大预览时加载 */
  originalCoverUrl?: string
  /** 视频地址（mock） */
  videoUrl: string
  /** 片段时长（秒） */
  duration: number
  /** 生成时出演的数字人（可为空 = 空镜头） */
  digitalHumanIds: string[]
}

/** 场景信息（分镜的背景底图，由场景提示词生成） */
export interface SceneInfo {
  status: GenStatus
  /** 场景图 */
  imageUrl?: string
  /** 场景原图，仅在放大预览时加载 */
  originalImageUrl?: string
  /** 最近一次生成失败的原因（status === 'failed' 时展示） */
  error?: string
}

/** 分镜信息 */
export interface ShotInfo {
  status: GenStatus
  /** 当前选用资产的封面（冗余字段，方便列表/时间轴/播放器直接展示） */
  imageUrl?: string
  /** 当前选用的资产 id */
  currentAssetId?: string
  /** 历史生成的视频片段资产 */
  assets: ShotAsset[]
  /** 最近一次生成失败的原因（status === 'failed' 时展示） */
  error?: string
}

/** 分镜视频生成参数（清晰度 / 时长 / 画幅） */
export interface ShotGenOptions {
  resolution: '480p' | '720p' | '1080p'
  /** 时长（秒） */
  duration: number
  ratio: '16:9' | '9:16' | '4:3' | '1:1'
  imageModel: ImageModelId
  videoModel: VideoModelId
  segmentType?: 'lyric' | 'intro' | 'interlude' | 'outro'
  timelineLabel?: string
  /** 时间轴原始时长（秒，未归一化） */
  sourceDuration?: number
  gapBefore?: number
  gapAfter?: number
  gapAfterAllocation?: 'current' | 'next' | 'none'
  /** 时间轴素材时长（秒） */
  materialDuration?: number
  /** ASS 大纲状态：pending=待生成 / ready=已生成 / failed=所在场景段生成失败 */
  outlineStatus?: 'pending' | 'ready' | 'failed'
  /** 所属场景段序号（第一轮场景规划结果） */
  sceneIndex?: number
}

/** 脚本行（每一条 = 一个分镜） */
export interface ScriptLine {
  id: string
  /** 脚本来源；通用分镜不包含歌词与翻译 */
  source?: 'ass' | 'general' | 'manual'
  /** 通用分镜的镜头类型 */
  shotType?: 'empty' | 'character'
  /** 脚本规划时长（秒），不等同于单次视频生成时长 */
  plannedDuration?: number
  /** ASS 时间轴起止时间（秒） */
  start?: number
  end?: number
  /** 当前分镜歌词 */
  lyrics: string
  /** 歌词中文翻译（歌词非中文时展示在歌词下方） */
  lyricsZh?: string
  /** 场景提示词（生成分镜的背景场景） */
  scenePrompt: string
  /** 分镜提示词（镜头运动、角色表演等，与场景、角色一起生成视频片段） */
  shotPrompt: string
  /** 出演该分镜的数字人（从全局角色阵容中挑选，可为空 = 空镜头，也可多个） */
  digitalHumanIds: string[]
  voice: VoiceInfo
  scene: SceneInfo
  shot: ShotInfo
  /** 分镜视频生成参数（未设置时使用默认值） */
  shotOptions?: ShotGenOptions
  /** 是否手动添加的分镜（仅手动添加的分镜允许删除，脚本生成的分镜不可删） */
  manual?: boolean
  generationStatus?: 'pending' | 'running' | 'succeeded' | 'failed'
  generationError?: string
  generationAttempt?: number
}

export interface StoryOutlineShot {
  index: number
  stage: string
  lyrics?: string
  shotType: 'empty' | 'character'
  /** 大纲生成状态：failed = 所在场景段生成失败的占位镜头 */
  outlineStatus?: 'pending' | 'ready' | 'failed'
  /** 所属场景段序号 */
  sceneIndex?: number
  intent?: string
  outlineScene?: string
  outlineShot?: string
  requiredCharacterIds?: string[]
  preferredCharacterIds?: string[]
  locationId?: string
  locationChange?: boolean
  characterAction?: string
  emotionalFocus?: string
  cameraPurpose?: string
  motifIds?: string[]
  sourceDuration?: number
  gapBefore?: number
  gapAfter?: number
  gapAfterAllocation?: 'current' | 'next' | 'none'
  materialDuration?: number
  generationDuration?: number
  segmentType?: 'lyric' | 'intro' | 'interlude' | 'outro'
  timelineLabel?: string
}

export interface StoryBible {
  version: string
  logline: string
  characterPolicy: string
  globalVisual?: Record<string, unknown>
  locations?: Array<{ id: string; name: string; purpose: string }>
  motifs?: Array<{ id: string; name: string; meaning: string; maxAppearances: number }>
  /** 第一轮场景规划结果（ASS 两轮分段架构） */
  scenePlan?: StoryScenePlan[]
  /** 第二轮生成失败的场景段 */
  failedSegments?: OutlineFailedSegment[]
  shots: StoryOutlineShot[]
}

/** ASS 第一轮场景规划的一个大场景 */
export interface StoryScenePlan {
  sceneIndex: number
  locationId?: string
  lineStart?: number
  lineEnd?: number
  locationName: string
  mood?: string
  emotion?: string
  visualTone?: string
  narrativePurpose?: string
}

/** 大纲生成失败的场景段（段级重试入口） */
export interface OutlineFailedSegment {
  sceneIndex: number
  locationName: string
  error: string
}

/** ASS 大纲后台生成的进度（SSE 事件与任务快照共用） */
export interface OutlineProgress {
  phase?: 'planning' | 'segments' | 'error'
  segmentsDone?: number
  segmentsTotal?: number
  startedAt?: string
  error?: string
}

/** 大纲回填到分镜行的规划结果（全局/段级重试端点共用） */
export interface OutlinePlannedLine {
  id: string
  shotType: 'empty' | 'character'
  plannedDuration?: number
  shotOptions?: ShotGenOptions
  digitalHumanIds: string[]
  generationStatus: 'pending'
}

export interface StoryboardCategoryOption {
  value: string
  label: string
  children?: StoryboardCategoryOption[]
}

export interface GeneralStoryboardOptions {
  genres: StoryboardCategoryOption[]
  seasons: string[]
  ageGroups: string[]
  visualStyles: string[]
  ratios: ShotGenOptions['ratio'][]
}

/** 通用分镜：出镜人物性别构成选项（与后端 GeneralStoryboardCreate.gender 保持一致） */
export const GENERAL_GENDER_OPTIONS = [
  '女',
  '男',
  '男女',
  '女女',
  '男男',
  '多女（三人以上）',
  '多男（三人以上）',
  '多人有男有女（三人以上）',
] as const
export type GeneralGender = (typeof GENERAL_GENDER_OPTIONS)[number]

export interface GeneralStoryboardRequest {
  projectId?: string
  genre: string
  secondaryCategory: string
  tertiaryCategory?: string
  season: string
  gender: GeneralGender
  ageGroup: string
  visualStyle: string
  ratio: ShotGenOptions['ratio']
  resolution: ShotGenOptions['resolution']
  imageModel: ImageModelId
  videoModel: VideoModelId
  emptyShotCount: number
  characterShotCount: number
  totalDuration: number
  digitalHumanIds?: string[]
  extraRequirement?: string
}

export interface GeneralStoryboardResult {
  taskId: string
  title: string
  cast: string[]
  totalDuration: number
  lines: Array<{
    id?: string
    shotType: 'empty' | 'character'
    plannedDuration: number
    scenePrompt: string
    shotPrompt: string
    digitalHumanIds: string[]
    shotOptions?: ShotGenOptions
    generationStatus?: ScriptLine['generationStatus']
  }>
}

/** 时间轴片段 */
export interface TimelineClip {
  lineId: string
  index: number
  start: number
  duration: number
}

/** 合成状态 */
export interface SynthesisState {
  status: 'idle' | 'queued' | 'running' | 'ready' | 'failed'
  progress: number
  stage?: string
  videoUrl?: string
  error?: string
}

export interface MaterialExport {
  id: string
  taskId: string
  jobId?: string
  status: 'queued' | 'running' | 'ready' | 'failed'
  progress: number
  stage: string
  totalAssets: number
  processedAssets: number
  totalBytes: number
  processedBytes: number
  archiveSize?: number
  archiveUrl?: string
  error?: string
  createdAt: string
  updatedAt: string
}
