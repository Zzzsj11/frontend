import { apiRequest } from './client'

export interface ServerMetricPoint {
  capturedAt: string
  cpuPercent: number
  cpuIowaitPercent: number
  load: [number, number, number]
  memoryUsedPercent: number
  memoryTotalBytes: number
  memoryAvailableBytes: number
  swapTotalBytes: number
  swapFreeBytes: number
  diskUsedPercent: number
  diskTotalBytes: number
  diskAvailableBytes: number
  networkTxBps: number
  networkRxBps: number
  diskReadBps: number
  diskWriteBps: number
  diskReadIops: number
  diskWriteIops: number
  filesystems: Array<{
    path: string
    totalBytes: number
    availableBytes: number
    inodeTotal: number
    inodeFree: number
  }>
  workloads: {
    queues: Array<{ kind: string; queued: number; running: number; oldestQueuedSeconds: number }>
    completedLastHour: Array<{
      kind: string
      success: number
      failed: number
      queue_wait_seconds: { avg: number; p95: number }
      execution_seconds: { avg: number; p95: number }
      end_to_end_seconds: { avg: number; p95: number }
      observationCoveragePercent: number
    }>
    llmLastHour: { calls: number; failed: number; tokens: number; avgMs: number; p95Ms: number }
    configuredExecutionLimits: Record<string, number>
  }
  interface: string
  containers: Array<{
    name: string
    cpuPercent: number
    memoryPercent: number
    memoryUsage: string
    networkIO: string
    blockIO: string
    memoryUsedBytes: number
    pids: number
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
