import { apiRequest } from './client'

export interface ServerMetricPoint {
  capturedAt: string
  cpuPercent: number
  load: [number, number, number]
  memoryUsedPercent: number
  memoryTotalBytes: number
  memoryAvailableBytes: number
  diskUsedPercent: number
  diskTotalBytes: number
  diskAvailableBytes: number
  networkTxBps: number
  networkRxBps: number
  interface: string
  containers: Array<{
    name: string
    cpuPercent: number
    memoryPercent: number
    memoryUsage: string
    networkIO: string
    blockIO: string
  }>
}

export interface ServerMonitoringSummary {
  latest: ServerMetricPoint | null
  points: ServerMetricPoint[]
  stale: boolean
  traffic: {
    month: string
    quotaBytes: number
    egressBytes: number
    remainingBytes: number
    usedPercent: number
    accounting: 'public-egress'
    unit: 'GiB'
    reset: 'calendar-month'
  }
  alerts: Array<{
    id: string
    key: string
    severity: string
    status: string
    title: string
    message: string
    firstTriggeredAt: string
    lastObservedAt: string
    resolvedAt?: string | null
  }>
  maintenanceRuns: Array<{
    id: string
    action: string
    trigger: string
    dryRun: boolean
    status: string
    summary: string
    createdAt: string
  }>
}

export const fetchServerMonitoring = (hours: number) =>
  apiRequest<ServerMonitoringSummary>(`/admin/server-monitoring?hours=${hours}`)

export const dryRunServerMaintenance = (action: string) =>
  apiRequest<{ id: string; status: string; dryRun: boolean; summary: string }>(
    '/admin/server-monitoring/maintenance/dry-run',
    { method: 'POST', body: JSON.stringify({ action }) },
  )
