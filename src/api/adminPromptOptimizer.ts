import { apiRequest } from './client'

export type PromptOptimizerProvider = 'gemini' | 'minimax'
export type PromptOptimizerMediaKind = 'image' | 'video' | 'audio'

export interface PromptOptimizerMedia {
  kind: PromptOptimizerMediaKind
  url: string
  thumbnailUrl?: string | null
  runningHubFileName?: string
  runningHubDownloadUrl?: string
  name: string
  mimeType: string
  size?: number
  role: string
}

export interface PromptOptimizerTask {
  id: string
  provider: PromptOptimizerProvider
  model: string
  status: string
  inputPrompt: string
  outputPrompt: string
  duration: number
  ratio: string
  media: PromptOptimizerMedia[]
  providerTaskId?: string | null
  usage: Record<string, unknown>
  error: string
  createdAt: string
}

export interface PromptOptimizerStatus {
  providers: Record<
    PromptOptimizerProvider,
    { configured: boolean; model: string; keyTail: string }
  >
  limits: {
    images: number
    videos: number
    audios: number
    videoSeconds: number
    audioSeconds: number
  }
  ratios: string[]
  durationRange: [number, number]
}

export const fetchPromptOptimizerStatus = () =>
  apiRequest<PromptOptimizerStatus>('/admin/prompt-optimizer/status')

export const fetchPromptOptimizerTasks = () =>
  apiRequest<{ items: PromptOptimizerTask[] }>('/admin/prompt-optimizer/tasks')

export const uploadPromptOptimizerMedia = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return apiRequest<PromptOptimizerMedia>('/admin/prompt-optimizer/upload', {
    method: 'POST',
    body: form,
  })
}

export const createPromptOptimizerTask = (input: {
  provider: PromptOptimizerProvider
  prompt: string
  duration: number
  ratio: string
  media: PromptOptimizerMedia[]
}) =>
  apiRequest<PromptOptimizerTask>('/admin/prompt-optimizer/tasks', {
    method: 'POST',
    body: JSON.stringify(input),
  })

export const queryPromptOptimizerTask = (id: string) =>
  apiRequest<PromptOptimizerTask>(`/admin/prompt-optimizer/tasks/${encodeURIComponent(id)}`, {
    headers: { 'X-Polling': '1' },
  })
