import { apiRequest } from './client'

export interface ChatComparisonModel {
  code: string
  name: string
  protocol: 'openai' | 'anthropic'
}

export interface ChatComparisonResult {
  model: string
  name: string
  protocol: string
  status: 'ok' | 'error'
  text: string
  error: string
  durationMs: number
  requestId?: string
  usage: {
    inputTokens: number
    outputTokens: number
    cachedInputTokens: number
    totalTokens: number
  }
}

export interface GeneralOutlineShot {
  index: number
  shotType: 'empty' | 'character'
  outlineScene: string
  outlineShot: string
  requiredCharacterIds: string[]
  intent: string
  characterAction: string
  emotionalFocus: string
  cameraPurpose: string
}

export interface GeneralOutlineComparisonResult {
  model: string
  name: string
  protocol: string
  status: 'ok' | 'error'
  error: string
  totalDurationMs: number
  attempts: number
  callMetrics: Array<{ operation: string; status: string; durationMs: number }>
  usage: ChatComparisonResult['usage']
  shots: GeneralOutlineShot[]
}

export const fetchChatComparisonModels = () =>
  apiRequest<ChatComparisonModel[]>('/admin/chat-comparison/models')

export const runChatComparison = (payload: {
  systemPrompt: string
  prompt: string
  models: string[]
  temperature: number
  maxTokens: number
}) =>
  apiRequest<{ results: ChatComparisonResult[] }>('/admin/chat-comparison/run', {
    method: 'POST',
    body: JSON.stringify({
      system_prompt: payload.systemPrompt,
      prompt: payload.prompt,
      models: payload.models,
      temperature: payload.temperature,
      max_tokens: payload.maxTokens,
    }),
  })

export const runGeneralOutlineComparison = (payload: Record<string, unknown>) =>
  apiRequest<{ results: GeneralOutlineComparisonResult[] }>(
    '/admin/chat-comparison/general-outline',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  )
