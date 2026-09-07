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
  providerResolution?: string
  actualWidth?: number
  actualHeight?: number
  fps?: number
  durationSeconds: number
  generationElapsedSeconds?: number
  generationStatus: string
  isFailed: boolean
  billingStatus: string
  usageQuantity: number
  usageUnit: string
  unitPrice: number
  listUnitPrice: number
  discountRate: number
  discountLabel: string
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
  providerResolution?: string
  actualWidth?: number
  actualHeight?: number
  fps?: number
  codec?: string
  actualDuration?: number
  fileSize?: number
  durationSeconds: number
  generationElapsedSeconds?: number
  usageQuantity: number
  usageUnit: string
  unitPrice: number
  listUnitPrice: number
  discountRate: number
  discountLabel: string
  rateLabel: string
  amount: number
  billingStatus: string
  attempt: number
  providerAttempts: {
    attempt: number
    stage: string
    outcome: string
    detail?: string
    providerTaskId?: string
    recordedAt?: string
  }[]
  prompts: { label: string; content: string }[]
  references: { label: string; type: string; url: string; providerUrl?: string }[]
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
  apiRequest<{ jobId: string; status: string; reused: boolean }>('/admin/video-billing/reconcile', {
    method: 'POST',
  })

export const getVideoBillingReconcileJob = (jobId: string) =>
  apiRequest<{
    id: string
    status: string
    progress: number
    error?: string
    result?: { processed: number; priced: number; failed: number }
  }>(`/generations/${encodeURIComponent(jobId)}`, { headers: { 'X-Polling': '1' } })

export const getVideoBillingDetail = (id: string) =>
  apiRequest<VideoBillingDetail>(`/admin/video-billing/${encodeURIComponent(id)}`)
