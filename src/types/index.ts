/** 生成状态 */
export type GenStatus = 'none' | 'generating' | 'done'

/** 歌曲目录下的处理任务（一个任务 = 一次 MV 制作会话） */
export interface SongTask {
  id: string
  title: string
  /** 相对时间标注，如「刚刚」「3天」 */
  updatedAt: string
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
  description: string
  /** 生成形象时使用的完整提示词（可在编辑界面查看 / 修改后重新生成） */
  avatarPrompt?: string
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
}

/** 分镜视频生成参数（清晰度 / 时长 / 画幅） */
export interface ShotGenOptions {
  resolution: '480p' | '720p' | '1080p'
  /** 时长（秒） */
  duration: number
  ratio: '16:9' | '9:16' | '4:3' | '1:1'
}

/** 脚本行（每一条 = 一个分镜） */
export interface ScriptLine {
  id: string
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
  status: 'idle' | 'running' | 'done'
  progress: number
  videoUrl?: string
}
