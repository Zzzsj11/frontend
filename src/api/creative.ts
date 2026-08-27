import { apiRequest } from './client'
import type { CreativeReferenceMedia } from '../types'

export type CreativeProvider = 'gemini' | 'minimax'

export interface CreativeStatus {
  providers: Record<CreativeProvider, { configured: boolean; model: string }>
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

export interface CreativeOptimization {
  id: string
  provider: CreativeProvider
  model: string
  status: string
  inputPrompt: string
  outputPrompt: string
  duration: number
  ratio: string
  media: CreativeReferenceMedia[]
  providerTaskId?: string
  error: string
}

export const fetchCreativeStatus = () => apiRequest<CreativeStatus>('/creative/status')

export const uploadCreativeMedia = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return apiRequest<CreativeReferenceMedia>('/creative/upload', { method: 'POST', body: form })
}

export const optimizeCreativePrompt = (input: {
  provider: CreativeProvider
  prompt: string
  duration: number
  ratio: string
  media: CreativeReferenceMedia[]
}) =>
  apiRequest<CreativeOptimization>('/creative/optimizations', {
    method: 'POST',
    body: JSON.stringify(input),
  })

export const queryCreativeOptimization = (id: string) =>
  apiRequest<CreativeOptimization>(`/creative/optimizations/${encodeURIComponent(id)}`, {
    headers: { 'X-Polling': '1' },
  })
