import { apiRequest } from './client'

/** Kling 测试页初始化信息（key 只回显脱敏尾号） */
export interface KlingStatus {
  configured: boolean
  keyTail: string
  baseUrl: string
  model: string
  modes: string[]
  aspectRatios: string[]
  imageTypes: string[]
  durationRange: [number, number]
}

/** Kling 任务查询响应（透传上游 data 字段） */
export interface KlingTaskResult {
  task_id: string
  task_status: string
  task_status_msg?: string
  task_result?: { videos?: Array<{ id: string; url: string; duration: string }> } | null
}

export const fetchKlingStatus = () => apiRequest<KlingStatus>('/admin/kling/status')

export const submitKlingTask = (input: {
  prompt: string
  negativePrompt?: string
  images?: Array<{ imageUrl: string; type: string }>
  videos?: Array<{ videoUrl: string; referType?: string; keepOriginalSound?: string }>
  elementIds?: string[]
  duration: number
  mode: string
  aspectRatio: string
  sound: string
  cfgScale: number
}) =>
  apiRequest<{ taskId: string; status: string }>('/admin/kling/tasks', {
    method: 'POST',
    body: JSON.stringify(input),
  })

export const queryKlingTask = (taskId: string) =>
  apiRequest<KlingTaskResult>(`/admin/kling/tasks/${encodeURIComponent(taskId)}`)
