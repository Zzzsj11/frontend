import { apiRequest } from './client'

export interface VideoBillingItem {
  id: string
  generationJobId: string
  username: string
  projectName: string
  taskTitle: string
  provider: string
  model: string
  resolution: string
  generationStatus: string
  isFailed: boolean
  billingStatus: string
  usageQuantity: number
  usageUnit: string
  unitPrice: number
  amount: number
  currency: string
  completedAt?: string
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
  }
}

export const getVideoBilling = (query: URLSearchParams) =>
  apiRequest<VideoBillingResponse>(`/admin/video-billing?${query.toString()}`)

export const reconcileVideoBilling = () =>
  apiRequest<{ processed: number; priced: number; failed: number }>(
    '/admin/video-billing/reconcile',
    { method: 'POST' },
  )
