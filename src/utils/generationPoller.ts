/**
 * 统一媒体生成轮询调度器（P1：轮询架构收敛）。
 *
 * 改造前：每个生成任务（场景图/视频/数字人）各自跑一条独立的 3s 轮询循环，
 * 多行并发生成时形成 2N 条循环；切换子项目时旧任务的循环也不会停止，
 * 与新任务的全量脚本拉取叠加形成"切换风暴"。
 *
 * 改造后：
 * - 所有生成任务共享一个 3s tick，每个 tick 将最多 500 个任务合并为一次状态请求；
 * - 每个任务可携带 AbortSignal，切换子项目时经 taskWatchers 统一 abort，
 *   旧任务的轮询立即停止（后端任务仍在跑，资产落库；切回时由 resumeActiveGenerations 恢复）；
 * - taskWatchers 同时管理 SSE 长连接（大纲/素材导出）与脚本轮询的 AbortController。
 */
import { apiRequest } from '../api/client'
import { ApiError } from '../errorBus'

/** 轮询被主动取消（切换子项目）时抛出：调用方静默处理，不弹错误、不标失败 */
export class PollingCancelledError extends Error {
  constructor() {
    super('轮询已取消')
    this.name = 'PollingCancelledError'
  }
}

export interface GenerationJobSnapshot<R = unknown> {
  id: string
  status: string
  progress?: number
  result?: R
  error?: string | null
}

interface WatchEntry<T> {
  id: string
  deadline: number
  signal?: AbortSignal
  /** 任务成功时从 result 提取业务数据；可抛错以指定失败文案 */
  select: (snapshot: GenerationJobSnapshot) => T
  resolve: (value: T) => void
  reject: (error: unknown) => void
  failureMessage: string
  timeoutMessage: string
  /** 是否已至少查询过一次（新注册的任务需要尽快首查，不等待完整周期间隔） */
  polled: boolean
}

const POLL_INTERVAL_MS = 3000
/** 周期 tick 进行中注册的新任务，尽快补一次首查 */
const FIRST_POLL_DELAY_MS = 50

const entries = new Map<string, WatchEntry<unknown>>()
let timer: number | null = null
let ticking = false

async function fetchBatchSnapshots(
  batch: WatchEntry<unknown>[],
  signal: AbortSignal,
): Promise<GenerationJobSnapshot[]> {
  const fetchLegacy = () =>
    Promise.all(
      batch.map((entry) =>
        apiRequest<GenerationJobSnapshot>(`/generations/${entry.id}`, {
          headers: { 'X-Polling': '1' },
          signal,
        }).then((snapshot) => ({ ...snapshot, id: entry.id })),
      ),
    )
  try {
    const response = await apiRequest<GenerationJobSnapshot[] | GenerationJobSnapshot>(
      '/generations/status',
      {
        method: 'POST',
        headers: { 'X-Polling': '1' },
        body: JSON.stringify({ ids: batch.map((entry) => entry.id) }),
        signal,
      },
    )
    if (Array.isArray(response)) {
      const terminalIds = response
        .filter((item) =>
          ['succeeded', 'failed', 'cancelled'].includes((item.status ?? '').toLowerCase()),
        )
        .map((item) => item.id)
      if (terminalIds.length) {
        await apiRequest('/generations/observed', {
          method: 'POST',
          headers: { 'X-Polling': '1' },
          body: JSON.stringify({ ids: terminalIds }),
          signal,
        }).catch(() => undefined)
      }
      return response
    }
    // 单对象兼容旧测试桩及灰度期间的非标准代理响应。
    if (batch.length === 1) return [{ ...response, id: batch[0].id }]
    return fetchLegacy()
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404) throw error
    // 前端先于后端发布时回退旧接口；新后端正常情况下始终只走上面的聚合请求。
    return fetchLegacy()
  }
}

function settleEntry(entry: WatchEntry<unknown>, job: GenerationJobSnapshot): boolean {
  entry.polled = true
  const status = (job.status ?? '').toLowerCase()
  if (status === 'succeeded') {
    entry.resolve(entry.select(job))
    return true
  }
  if (status === 'failed' || status === 'cancelled') {
    entry.reject(new Error(job.error || entry.failureMessage))
    return true
  }
  if (Date.now() >= entry.deadline) {
    entry.reject(new Error(entry.timeoutMessage))
    return true
  }
  return false
}

async function tick() {
  if (ticking) return
  ticking = true
  try {
    const current = [...entries.values()]
    const active: WatchEntry<unknown>[] = []
    for (const entry of current) {
      if (!entries.delete(entry.id)) continue
      if (entry.signal?.aborted) {
        entry.reject(new PollingCancelledError())
      } else active.push(entry)
    }
    for (let offset = 0; offset < active.length; offset += 500) {
      const batch = active.slice(offset, offset + 500)
      const batchController = new AbortController()
      const abortBatchWhenUnused = () => {
        if (batch.every((entry) => entry.signal?.aborted)) batchController.abort()
      }
      for (const entry of batch) entry.signal?.addEventListener('abort', abortBatchWhenUnused)
      try {
        // 打 X-Polling 标记：后端全量日志与前端性能埋点均跳过轮询请求
        const snapshots = await fetchBatchSnapshots(batch, batchController.signal)
        const byId = new Map(snapshots.map((item) => [item.id, item]))
        for (const entry of batch) {
          if (entry.signal?.aborted) {
            entry.reject(new PollingCancelledError())
            continue
          }
          const snapshot = byId.get(entry.id)
          if (!snapshot) {
            entry.reject(new Error('生成任务不存在或无权访问'))
            continue
          }
          if (!settleEntry(entry, snapshot)) entries.set(entry.id, entry)
        }
      } catch (error) {
        for (const entry of batch) {
          entry.reject(entry.signal?.aborted ? new PollingCancelledError() : error)
        }
      } finally {
        for (const entry of batch) entry.signal?.removeEventListener('abort', abortBatchWhenUnused)
      }
    }
  } finally {
    ticking = false
    timer = null
    scheduleNext()
  }
}

function scheduleNext() {
  if (timer !== null || ticking || entries.size === 0) return
  const hasFresh = [...entries.values()].some((entry) => !entry.polled)
  timer = window.setTimeout(tick, hasFresh ? FIRST_POLL_DELAY_MS : POLL_INTERVAL_MS)
}

/**
 * 轮询一个媒体生成任务直至终态，返回 select 提取的结果。
 * signal  aborted 时立即 reject PollingCancelledError（包括注册前就已 abort 的情况）。
 */
export function watchGenerationJob<T>(
  jobId: string,
  options: {
    signal?: AbortSignal
    timeoutMs?: number
    select: (snapshot: GenerationJobSnapshot) => T
    failureMessage?: string
    timeoutMessage?: string
  },
): Promise<T> {
  const entry: WatchEntry<T> = {
    id: jobId,
    deadline: Date.now() + (options.timeoutMs ?? 660_000),
    signal: options.signal,
    select: options.select,
    resolve: undefined as never,
    reject: undefined as never,
    failureMessage: options.failureMessage ?? '生成失败',
    timeoutMessage: options.timeoutMessage ?? '生成超时，请稍后重试',
    polled: false,
  }
  const promise = new Promise<T>((resolve, reject) => {
    entry.resolve = resolve
    entry.reject = reject
  })
  if (options.signal?.aborted) {
    entry.reject(new PollingCancelledError())
    return promise
  }
  entries.set(jobId, entry as WatchEntry<unknown>)
  scheduleNext()
  return promise
}

// ---------- 按子项目(任务)聚合的 watcher 注册表 ----------

const taskWatchers = new Map<string, Set<AbortController>>()

/** 为某子项目注册一个 watcher（SSE / 脚本轮询 / 生成等待共用），返回其 AbortController */
export function registerTaskWatcher(taskId: string): AbortController {
  const controller = new AbortController()
  let set = taskWatchers.get(taskId)
  if (!set) {
    set = new Set()
    taskWatchers.set(taskId, set)
  }
  set.add(controller)
  controller.signal.addEventListener(
    'abort',
    () => {
      const current = taskWatchers.get(taskId)
      current?.delete(controller)
      if (current && current.size === 0) taskWatchers.delete(taskId)
    },
    { once: true },
  )
  return controller
}

/** 取消某子项目的全部 watcher（切换/删除子项目时调用）：旧任务轮询与 SSE 立即停止 */
export function cancelTaskWatchers(taskId: string): void {
  const set = taskWatchers.get(taskId)
  if (!set) return
  taskWatchers.delete(taskId)
  for (const controller of [...set]) controller.abort()
}

/** 取消所有子项目的 watcher（登出/账号切换时调用）：旧账号的轮询与 SSE 全部停止 */
export function cancelAllTaskWatchers(): void {
  for (const taskId of [...taskWatchers.keys()]) cancelTaskWatchers(taskId)
}

/** 可中断的 sleep：signal aborted 时立即返回（由调用方检查上下文后退出循环） */
export function abortableSleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve()
      return
    }
    const handle = window.setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    const onAbort = () => {
      window.clearTimeout(handle)
      resolve()
    }
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}
