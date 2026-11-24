import { reactive } from 'vue'
import { apiRequest, currentSession } from '../api/client'
import {
  GenerationJobFailed,
  GenerationObservationTimeout,
  GenerationReconciliationRequired,
  PollingCancelledError,
  watchGenerationJob,
  type GenerationJobSnapshot,
} from './generationPoller'

type Action = 'refresh' | 'reconcile' | 'retry'
const labels = { refresh: '刷新状态', reconcile: '查询原任务', retry: '重新生成' }
export const imageRecoveryActions = reactive(
  new Map<
    string,
    { label: string; target: string; message: string; run: () => void; dismiss?: () => void }
  >(),
)

function awaitAction(
  id: string,
  action: Action,
  target: string,
  message: string,
  signal: AbortSignal,
) {
  return new Promise<boolean>((resolve, reject) => {
    if (signal.aborted) {
      reject(new PollingCancelledError())
      return
    }
    const finish = (choice: boolean) => {
      signal.removeEventListener('abort', abort)
      imageRecoveryActions.delete(id)
      resolve(choice)
    }
    const abort = () => {
      imageRecoveryActions.delete(id)
      reject(new PollingCancelledError())
    }
    signal.addEventListener('abort', abort, { once: true })
    imageRecoveryActions.set(id, {
      label: labels[action],
      target,
      message,
      run: () => finish(true),
      ...(action === 'retry' ? { dismiss: () => finish(false) } : {}),
    })
  })
}

const activeObservations = new Set<string>()
export const isObservingImage = (id: string) => activeObservations.has(id)

export async function waitForRecoverableImage<T>(
  id: string,
  select: (snapshot: GenerationJobSnapshot) => T,
  options: { signal?: AbortSignal; timeoutMs?: number; target?: string } = {},
): Promise<T> {
  activeObservations.add(id)
  try {
    return await observeImage(id, select, options)
  } finally {
    activeObservations.delete(id)
  }
}

async function observeImage<T>(
  id: string,
  select: (snapshot: GenerationJobSnapshot) => T,
  options: { signal?: AbortSignal; timeoutMs?: number; target?: string } = {},
): Promise<T> {
  const signal = options.signal
    ? AbortSignal.any([currentSession(), options.signal])
    : currentSession()
  const target = options.target || '图片生成'
  for (;;) {
    try {
      return await watchGenerationJob(id, { ...options, signal, select })
    } catch (error) {
      if (error instanceof GenerationObservationTimeout) {
        await awaitAction(id, 'refresh', target, '图片仍在等待结果，可刷新原工单状态。', signal)
      } else if (error instanceof GenerationReconciliationRequired) {
        let message = '图片提交结果待核对，请查询原任务。'
        for (;;) {
          await awaitAction(id, 'reconcile', target, message, signal)
          try {
            const status = await apiRequest<GenerationJobSnapshot>(
              `/generations/${encodeURIComponent(id)}/check-image`,
              {
                method: 'POST',
                signal: AbortSignal.any([signal, AbortSignal.timeout(15_000)]),
                headers: { 'X-Polling': '1' },
              },
            )
            if (status.phase !== 'manual_review') break
            message = '暂未确认原任务结果，可稍后再查。'
          } catch {
            message = '暂时无法查询原任务，可稍后再查。'
          }
        }
      } else throw error
    }
  }
}

export async function runImageGeneration<J extends { id: string }, T>(
  submit: () => Promise<J>,
  wait: (job: J) => Promise<T>,
  options: { signal?: AbortSignal; target?: string } = {},
): Promise<T> {
  const signal = options.signal
    ? AbortSignal.any([currentSession(), options.signal])
    : currentSession()
  for (;;) {
    if (signal.aborted) throw new PollingCancelledError()
    const job = await submit()
    try {
      return await wait(job)
    } catch (error) {
      if (!(error instanceof GenerationJobFailed)) throw error
      const retry = await awaitAction(
        job.id,
        'retry',
        options.target || '图片生成',
        error.message,
        signal,
      )
      if (!retry) throw error
    }
  }
}
