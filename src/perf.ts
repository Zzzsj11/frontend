/**
 * 前端性能观测（本浏览器会话内，内存 Ring Buffer，不落库）：
 *
 *  - API 耗时：apiRequest/openApiStream 埋点，区分「网络+服务端」与「JSON 解析」，
 *    直接回答「页面卡是接口慢还是渲染慢」
 *  - Long Task：主线程阻塞 >50ms 的片段，渲染/布局卡顿的直接证据
 *  - 导航计时：TTFB / DOMContentLoaded / 首屏完成
 *
 * 所有记录只保存在当前会话；管理后台「性能」页展示本浏览器数据 + 后端全量数据。
 */

export interface ApiTiming {
  id: number
  path: string
  method: string
  status: number
  /** fetch 发出 → 响应头到达（网络 + 服务端处理；含重试预算等待） */
  networkMs: number
  /** 响应头 → json() 解析完成（响应体大小 / 序列化开销） */
  parseMs: number
  totalMs: number
  retried: boolean
  at: number
}

export interface LongTaskSample {
  id: number
  at: number
  durationMs: number
  target: string
}

export interface ApiTimingRow {
  path: string
  method: string
  count: number
  avgMs: number
  p95Ms: number
  maxMs: number
  parseAvgMs: number
}

const MAX_API_ENTRIES = 500
const MAX_LONG_TASKS = 200
const apiEntries: ApiTiming[] = []
const longTasks: LongTaskSample[] = []
let seq = 0

/** 跳过轮询/长连接请求（与后端全量日志同一语义，避免 ring buffer 被刷屏） */
export const isPollingHeaders = (headers?: HeadersInit): boolean =>
  new Headers(headers).get('X-Polling') === '1'

export function recordApiTiming(t: Omit<ApiTiming, 'id' | 'at'>) {
  const entry: ApiTiming = { ...t, id: ++seq, at: Date.now() }
  apiEntries.push(entry)
  if (apiEntries.length > MAX_API_ENTRIES) apiEntries.splice(0, apiEntries.length - MAX_API_ENTRIES)
  return entry
}

/** 按 path+method 聚合（本会话）：count/avg/p95/max/解析平均，按 max 倒序 */
export function apiTimingSummary(limit = 30): ApiTimingRow[] {
  const buckets = new Map<string, { path: string; method: string; ms: number[]; parseMs: number[] }>()
  for (const entry of apiEntries) {
    const key = `${entry.method} ${entry.path}`
    let bucket = buckets.get(key)
    if (!bucket) {
      bucket = { path: entry.path, method: entry.method, ms: [], parseMs: [] }
      buckets.set(key, bucket)
    }
    bucket.ms.push(entry.totalMs)
    bucket.parseMs.push(entry.parseMs)
  }
  const rows: ApiTimingRow[] = []
  for (const bucket of buckets.values()) {
    bucket.ms.sort((a, b) => a - b)
    const avg = bucket.ms.reduce((s, v) => s + v, 0) / bucket.ms.length
    rows.push({
      path: bucket.path,
      method: bucket.method,
      count: bucket.ms.length,
      avgMs: Math.round(avg),
      // ceil(n*0.95)-1：保证「95% 的样本不超过 p95」语义
      p95Ms: bucket.ms[Math.max(0, Math.ceil(bucket.ms.length * 0.95) - 1)],
      maxMs: bucket.ms[bucket.ms.length - 1],
      parseAvgMs: Math.round(
        bucket.parseMs.reduce((s, v) => s + v, 0) / bucket.parseMs.length,
      ),
    })
  }
  rows.sort((a, b) => b.maxMs - a.maxMs)
  return rows.slice(0, limit)
}

export function recentSlowApi(minMs = 800, limit = 30): ApiTiming[] {
  return [...apiEntries]
    .reverse()
    .filter((entry) => entry.totalMs >= minMs)
    .slice(0, limit)
}

export function recordLongTask(durationMs: number, target: string, at = Date.now()) {
  const sample: LongTaskSample = { id: ++seq, at, durationMs, target }
  longTasks.push(sample)
  if (longTasks.length > MAX_LONG_TASKS) longTasks.shift()
  return sample
}

/** 导航计时：TTFB / DCL / Load（仅整页加载后可用） */
export function navigationTiming() {
  const nav = performance.getEntriesByType('navigation')[0] as
    | PerformanceNavigationTiming
    | undefined
  if (!nav) return null
  const start = nav.requestStart || nav.startTime
  return {
    ttfbMs: Math.round(nav.responseStart - start),
    domContentLoadedMs: Math.round(nav.domContentLoadedEventEnd - start),
    loadMs: Math.round(nav.loadEventEnd - start),
  }
}

/** Long Task 条目的 attribution 类型（TS lib 未内置 PerformanceLongTaskTiming） */
interface LongTaskAttribution {
  name?: string
  containerType?: string
}

let monitoringStarted = false
/** 启动会话级性能观测：Long Task 监听（幂等，可在应用入口调用一次） */
export function startPerfMonitoring() {
  if (monitoringStarted || typeof PerformanceObserver === 'undefined') return
  monitoringStarted = true
  try {
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const attribution = (entry as PerformanceEntry & { attribution?: LongTaskAttribution[] })
          .attribution?.[0]
        recordLongTask(
          Math.round(entry.duration),
          attribution?.name || attribution?.containerType || 'unknown',
        )
      }
    })
    observer.observe({ entryTypes: ['longtask'] })
  } catch {
    // 浏览器不支持 Long Task API 时静默降级
  }
}

export function perfSnapshot() {
  return {
    apiEntries: [...apiEntries].reverse().slice(0, 50),
    apiSummary: apiTimingSummary(),
    slowApi: recentSlowApi(),
    longTasks: longTasks.slice(-50).reverse(),
    navigation: navigationTiming(),
  }
}
