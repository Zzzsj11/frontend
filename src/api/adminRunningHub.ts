import { apiRequest } from './client'

/** RunningHub 测试页初始化信息（key 只回显脱敏尾号） */
export interface RunningHubStatus {
  configured: boolean
  keyTail: string
  workflowId: string
  modes: Array<'reference' | 'text' | 'first_frame' | 'first_last'>
  aspectRatios: string[]
  firstFrameAspectRatios: string[]
  textAspectRatios: string[]
  durationRange: [number, number]
  /** 一/二阶段共用的 megapixels 档位（size 为 16:9 输出分辨率） */
  megapixelsPresets: Array<{ value: number; size: string }>
  /** 工作流默认 [一采, 二采] megapixels */
  megapixelsDefault: [number, number]
  textMegapixelsDefault: number
  firstFrameMegapixelsDefault: number
}

/** RunningHub 任务查询响应（透传上游） */
export interface RunningHubTaskResult {
  taskId: string
  status: string
  errorCode?: string
  errorMessage?: string
  results?: Array<{ url: string; nodeId: string; outputType: string; text: string | null }> | null
  usage?: { consumeCoins?: string | null; taskCostTime?: string | null } | null
}

export interface H3TestMedia {
  type: 'image' | 'video' | 'audio'
  url: string
  sourceUrl?: string
  runningHubFileName?: string
  name?: string
  outputType?: string
  role?: 'comparison_cover' | 'seedance_source'
  lineId?: string
  lineOrder?: number
  shotType?: 'empty' | 'character'
  username?: string
  projectId?: string
  projectName?: string
  taskId?: string
  taskTitle?: string
}

export interface H3ComparisonSource {
  lineId: string
  lineOrder: number
  shotType: 'empty' | 'character'
  prompt: string
  coverUrl: string
  seedanceUrl: string
  duration: number
  username: string
  userId: string
  projectId: string
  projectName: string
  taskId: string
  taskTitle: string
  referenceCandidates?: Array<{
    id: string
    label: string
    url: string
    kind: 'cover' | 'character'
    humanId?: string
    assetAvatarUrl?: string
    avatarUrl?: string
  }>
}

export interface H3TestPreset {
  id: string
  name: string
  mode: 'reference' | 'text' | 'first_frame' | 'first_last'
  comparisonMode?: 'reference' | 'multi_reference' | 'first_frame'
  prompt: string
  duration: number
  aspectRatio: string
  inputMedia: H3TestMedia[]
  outputMedia: H3TestMedia[]
  taskId?: string | null
  taskStatus: string
  usage: { consumeCoins?: string | null; taskCostTime?: string | null }
  createdAt: string
}

export const fetchRunningHubStatus = () => apiRequest<RunningHubStatus>('/admin/runninghub/status')

export const fetchRunningHubPresets = () =>
  apiRequest<{ items: H3TestPreset[] }>('/admin/runninghub/presets')

export const fetchRunningHubComparisonSources = () =>
  apiRequest<{ items: H3ComparisonSource[] }>('/admin/runninghub/comparison-sources')

export const submitRunningHubComparison = (lineId: string) =>
  apiRequest<H3TestPreset>('/admin/runninghub/comparisons', {
    method: 'POST',
    body: JSON.stringify({ lineId }),
  })

export const submitRunningHubComparisonWithRefs = (input: {
  lineId: string
  referenceUrls: string[]
  comparisonMode: 'multi_reference' | 'first_frame'
}) =>
  apiRequest<H3TestPreset>('/admin/runninghub/comparisons', {
    method: 'POST',
    body: JSON.stringify({
      lineId: input.lineId,
      referenceUrls: input.referenceUrls,
      comparisonMode: input.comparisonMode,
    }),
  })

export const uploadRunningHubMedia = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return apiRequest<{ fileName: string; downloadUrl: string; size: string; tosUrl: string }>(
    '/admin/runninghub/upload',
    {
      method: 'POST',
      body: form,
    },
  )
}

/** @deprecated 使用 uploadRunningHubMedia；保留兼容现有调用方。 */
export const uploadRunningHubImage = uploadRunningHubMedia

export const submitRunningHubTask = (input: {
  mode: 'reference' | 'text' | 'first_frame' | 'first_last'
  prompt: string
  duration: number
  aspectRatio: string
  images: string[]
  videos?: string[]
  audios?: string[]
  seed?: number | null
  stage1Megapixels?: number
  stage2Megapixels?: number
  textMegapixels?: number
  firstFrameMegapixels?: number
}) =>
  apiRequest<{ taskId: string; status: string }>('/admin/runninghub/tasks', {
    method: 'POST',
    body: JSON.stringify({
      mode: input.mode,
      prompt: input.prompt,
      duration: input.duration,
      aspectRatio: input.aspectRatio,
      images: input.images,
      videos: input.videos ?? [],
      audios: input.audios ?? [],
      seed: input.seed ?? null,
      stage1Megapixels: input.stage1Megapixels,
      stage2Megapixels: input.stage2Megapixels,
      textMegapixels: input.textMegapixels,
      firstFrameMegapixels: input.firstFrameMegapixels,
    }),
  })

export const queryRunningHubTask = (taskId: string) =>
  apiRequest<RunningHubTaskResult>('/admin/runninghub/query', {
    method: 'POST',
    body: JSON.stringify({ taskId }),
  })
