import { apiRequest } from './client'

/** RunningHub 测试页初始化信息（key 只回显脱敏尾号） */
export interface RunningHubStatus {
  configured: boolean
  keyTail: string
  workflowId: string
  aspectRatios: string[]
  durationRange: [number, number]
  /** 一/二阶段共用的 megapixels 档位（size 为 16:9 输出分辨率） */
  megapixelsPresets: Array<{ value: number; size: string }>
  /** 工作流默认 [一采, 二采] megapixels */
  megapixelsDefault: [number, number]
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

export const fetchRunningHubStatus = () => apiRequest<RunningHubStatus>('/admin/runninghub/status')

export const uploadRunningHubImage = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return apiRequest<{ fileName: string; downloadUrl: string; size: string }>(
    '/admin/runninghub/upload',
    {
      method: 'POST',
      body: form,
    },
  )
}

export const submitRunningHubTask = (input: {
  prompt: string
  duration: number
  aspectRatio: string
  images: string[]
  seed?: number | null
  stage1Megapixels?: number
  stage2Megapixels?: number
}) =>
  apiRequest<{ taskId: string; status: string }>('/admin/runninghub/tasks', {
    method: 'POST',
    body: JSON.stringify({
      prompt: input.prompt,
      duration: input.duration,
      aspectRatio: input.aspectRatio,
      images: input.images,
      seed: input.seed ?? null,
      stage1Megapixels: input.stage1Megapixels,
      stage2Megapixels: input.stage2Megapixels,
    }),
  })

export const queryRunningHubTask = (taskId: string) =>
  apiRequest<RunningHubTaskResult>('/admin/runninghub/query', {
    method: 'POST',
    body: JSON.stringify({ taskId }),
  })
