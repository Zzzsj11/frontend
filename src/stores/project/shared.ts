import { useAuthStore } from '../auth'
import type { GeneralStoryboardResult, ScriptLine, ShotGenOptions } from '../../types'
import { nextId } from '../../utils/id'
import {
  DEFAULT_H3_MODE,
  DEFAULT_VIDEO_DURATION,
  normalizeShotOptions,
} from '../../mediaConstraints'
import { DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL } from '../../generationModels'

/** 侧边栏选中状态持久化 key（按用户隔离） */
export const sidebarKeys = (userId: string) => ({
  song: `mv_sidebar_song_${userId}`,
  task: `mv_sidebar_task_${userId}`,
})

/** 「批量生成视频」进行中标记持久化 key（按用户+任务隔离）：刷新/切走子任务中断后，回到该任务时续跑 */
export const batchShotKey = (userId: string, taskId: string) => `mv_batch_shot_${userId}_${taskId}`

/** 与后端单用户视频生成上限一致，仅控制本地提交队列；供应商并发由后端执行池管理。 */
export const BATCH_SHOT_CONCURRENCY = 200

export const mapGeneralStoryboardLines = (
  items: GeneralStoryboardResult['lines'],
  source: 'general' | 'general_random',
  fallbackOptions: (item: GeneralStoryboardResult['lines'][number]) => ShotGenOptions,
): ScriptLine[] =>
  items.map((item) => ({
    id: item.id || nextId(),
    source,
    shotType: item.shotType,
    plannedDuration: item.plannedDuration,
    lyrics: '',
    scenePrompt: item.scenePrompt,
    shotPrompt: item.shotPrompt,
    digitalHumanIds: [...item.digitalHumanIds],
    voice: { status: 'none' },
    scene: { status: 'none' },
    shot: { status: 'none', assets: [] },
    shotOptions: normalizeShotOptions(item.shotOptions ?? fallbackOptions(item)),
    generationStatus: item.generationStatus || (source === 'general' ? 'pending' : 'succeeded'),
  }))

/** 无配音时的占位时长（秒） */
export const DEFAULT_CLIP_DURATION = 5

/** 分镜视频生成参数默认值（清晰度 / 时长 / 画幅） */
export const DEFAULT_SHOT_OPTIONS: ShotGenOptions = {
  resolution: '480p',
  imageResolution: '1K',
  duration: DEFAULT_VIDEO_DURATION,
  ratio: '16:9',
  imageModel: DEFAULT_IMAGE_MODEL,
  videoModel: DEFAULT_VIDEO_MODEL,
  generateAudio: false,
  watermark: false,
  h3Mode: DEFAULT_H3_MODE,
}

/** 每行场景图重新生成次数（仅用于 mock 占位图换款） */
export const sceneVariants: Record<string, number> = {}

export const exportStreams = new Map<string, AbortController>()

/** 刷新恢复后正在续跑的媒体生成任务（防止重复恢复同一任务） */
export const resumedGenerationJobs = new Set<string>()

/** 正在轮询「逐句提示词生成」孤儿任务的任务 ID */
export const storyboardRunningWatchers = new Set<string>()

/** 本地逐句生成队列正在处理的行（刷新恢复轮询需跳过，避免用旧数据覆盖） */
export const localGeneratingLines = new Set<string>()

/** 未完成的数字人生成草稿（localStorage）：刷新/重开后恢复等待态并补建 */
export const pendingDhKey = () => `mv:pending-dh:${useAuthStore().user?.id || 'anonymous'}`

export interface PendingDhDraft {
  mode: 'generated' | 'uploaded'
  jobId: string
  name: string
  style: string
  description: string
  styleId?: string
}

export const savePendingDhDraft = (draft: PendingDhDraft) => {
  try {
    localStorage.setItem(pendingDhKey(), JSON.stringify(draft))
  } catch {
    /* 存储不可用时仅放弃恢复能力 */
  }
}

export const clearPendingDhDraft = () => {
  try {
    localStorage.removeItem(pendingDhKey())
  } catch {
    /* ignore */
  }
}

export const readPendingDhDraft = (): PendingDhDraft | null => {
  try {
    const raw = localStorage.getItem(pendingDhKey())
    return raw ? (JSON.parse(raw) as PendingDhDraft) : null
  } catch {
    return null
  }
}

/** 数字人资产库本地持久化 key */
/** 删除分类后，该分类下数字人的归属分类 */
export const FALLBACK_STYLE = '未分类'

/** mm:ss 格式化 */
export const formatTime = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds))
  const mm = String(Math.floor(s / 60)).padStart(2, '0')
  const ss = String(s % 60).padStart(2, '0')
  return `${mm}:${ss}`
}
