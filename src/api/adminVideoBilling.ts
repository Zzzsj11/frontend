import { apiRequest } from './client'

export interface VideoBillingItem {
  id: string
  generationJobId: string
  generationOrigin: 'business' | 'agent_test'
  agentName: string
  agentRunId: string
  username: string
  projectName: string
  taskTitle: string
  provider: string
  model: string
  resolution: string
  durationSeconds: number
  generationElapsedSeconds?: number
  generationStatus: string
  isFailed: boolean
  billingStatus: string
  usageQuantity: number
  usageUnit: string
  unitPrice: number
  rateLabel: string
  amount: number
  currency: string
  completedAt?: string
}

export interface VideoBillingDetail {
  id: string
  generationJobId: string
  generationOrigin: 'business' | 'agent_test'
  agentName: string
  agentRunId: string
  providerTaskId?: string
  status: string
  error: string
  model: string
  provider: string
  resolution: string
  durationSeconds: number
  generationElapsedSeconds?: number
  usageQuantity: number
  usageUnit: string
  unitPrice: number
  rateLabel: string
  amount: number
  billingStatus: string
  prompts: { label: string; content: string }[]
  references: { label: string; type: string; url: string }[]
  rawUsage: Record<string, unknown>
  result: { videoUrl?: string; coverUrl?: string; duration?: number; ratio?: string }
}

export interface VideoBillingResponse {
  total: number
  items: VideoBillingItem[]
  models: string[]
  summary: {
    totalAmount: number
    pricedRecords: number
    failedRecords: number
    failedAmount: number
    excludedRecords: number
    unpricedRecords: number
    noUsageRecords: number
    agentTestRecords: number
    businessRecords: number
  }
}

export const getVideoBilling = (query: URLSearchParams) =>
  apiRequest<VideoBillingResponse>(`/admin/video-billing?${query.toString()}`)

export const reconcileVideoBilling = () =>
  apiRequest<{ processed: number; priced: number; failed: number }>(
    '/admin/video-billing/reconcile',
    { method: 'POST' },
  )

export const getVideoBillingDetail = (id: string) =>
  apiRequest<VideoBillingDetail>(`/admin/video-billing/${encodeURIComponent(id)}`)
