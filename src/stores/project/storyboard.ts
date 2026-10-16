import type { ScriptLine } from '../../types'
import * as api from '../../api/domain'
import { ApiError } from '../../errorBus'
import { STORYBOARD_LINE_WAIT_TIMEOUT_MS } from '../../generationConstraints'
import {
  PollingCancelledError,
  abortableSleep,
  registerTaskWatcher,
} from '../../utils/generationPoller'
import { resumedGenerationJobs, storyboardRunningWatchers, localGeneratingLines } from './shared'
import type { ProjectContext } from './contracts'

export const storyboardActions = {
  /** 行的大纲是否已就绪（未就绪的行不能进入逐句生成，后端会 422） */
  _outlineReady(line: ScriptLine): boolean {
    return (
      line.shotOptions?.outlineStatus !== 'pending' && line.shotOptions?.outlineStatus !== 'failed'
    )
  },

  async _generateStoryboardQueue(taskId: string, lineIds: string[], force = false) {
    const watcher = registerTaskWatcher(taskId)
    let cursor = 0
    const worker = async () => {
      while (cursor < lineIds.length) {
        // 切换子项目后立即停止派发旧任务的生成请求（P1：不再为已切走的任务继续提交）
        if (watcher.signal.aborted || this.activeTaskId !== taskId) return
        const lineId = lineIds[cursor++]
        const local = this.lines.find((line) => line.id === lineId)
        if (local && this.activeTaskId === taskId && !this._outlineReady(local)) continue
        // 跳过已经在生成中或已完成的，避免重复提交触发后端 409
        if (
          local &&
          this.activeTaskId === taskId &&
          (local.generationStatus === 'running' || local.generationStatus === 'succeeded')
        )
          continue
        if (local && this.activeTaskId === taskId) {
          local.generationStatus = 'running'
          local.generationError = undefined
          local.generationErrorSummary = undefined
          local.generationFailedAt = undefined
        }
        localGeneratingLines.add(lineId)
        try {
          let item = await api.generateStoryboardLine(taskId, lineId, force)
          if (local && item.id) local.generationJobId = String(item.id)
          if (local && item.created_at)
            local.generationStartedAt = new Date(Number(item.created_at) * 1000).toISOString()
          if (item.id && ['queued', 'running'].includes(String(item.status || ''))) {
            await api.waitGenerationJob(
              String(item.id),
              watcher.signal,
              STORYBOARD_LINE_WAIT_TIMEOUT_MS,
            )
            item = (await api.fetchStoryboardLine(taskId, lineId)) as unknown as Record<
              string,
              unknown
            >
          }
          const current = this.lines.find((line) => line.id === lineId)
          if (current && this.activeTaskId === taskId) {
            current.scenePrompt = String(item.scenePrompt || '')
            current.shotPrompt = String(item.shotPrompt || '')
            current.digitalHumanIds = (item.digitalHumanIds as string[]) || []
            current.generationStatus = 'succeeded'
            current.generationError = undefined
            current.generationErrorSummary = undefined
            current.generationFailedAt = undefined
            current.generationAttempt = Number(
              item.generationAttempt || current.generationAttempt || 1,
            )
          }
        } catch (error) {
          if (watcher.signal.aborted || error instanceof PollingCancelledError) return
          // 409 表示后端已有任务在处理，静默跳过
          if (error instanceof ApiError && error.status === 409) {
            const current = this.lines.find((line) => line.id === lineId)
            if (current && this.activeTaskId === taskId) current.generationStatus = 'running'
          } else if (error instanceof ApiError && error.status === 429) {
            // 单账号并行上限：行还原为待生成并终止本轮队列（弹窗由 apiRequest 经 errorBus 统一上报）
            const current = this.lines.find((line) => line.id === lineId)
            if (current && this.activeTaskId === taskId) current.generationStatus = 'pending'
            cursor = lineIds.length
          } else {
            const current = this.lines.find((line) => line.id === lineId)
            if (current && this.activeTaskId === taskId) {
              current.generationStatus = 'failed'
              current.generationError =
                error instanceof Error ? error.message : '单条视频提示词生成失败'
              current.generationErrorSummary = '提示词生成失败，请查看详情'
              current.generationFailedAt = new Date().toISOString()
            }
          }
        } finally {
          localGeneratingLines.delete(lineId)
        }
      }
    }
    try {
      await Promise.all(Array.from({ length: Math.min(4, lineIds.length) }, () => worker()))
      if (this.activeTaskId === taskId) this._cacheCurrentTask()
    } finally {
      watcher.abort()
    }
  },

  /** 一次性将整批提示词工单交给服务端，浏览器只负责等待持久化工单落定。 */
  async _generateStoryboardBatch(taskId: string, lineIds: string[], force = false) {
    const uniqueIds = [...new Set(lineIds)].slice(0, 100)
    if (!uniqueIds.length) return
    const watcher = registerTaskWatcher(taskId)
    for (const line of this.lines) {
      if (uniqueIds.includes(line.id)) {
        line.generationStatus = 'running'
        line.generationError = undefined
        line.generationErrorSummary = undefined
        line.generationFailedAt = undefined
      }
    }
    try {
      const result = await api.generateStoryboardLinesBatch(taskId, uniqueIds, force)
      for (const item of result.jobs) {
        const lineId = String(item.storyboard_line_id || '')
        const line = this.lines.find((candidate) => candidate.id === lineId)
        if (!line) continue
        line.generationJobId = String(item.id || '') || line.generationJobId
        if (item.created_at)
          line.generationStartedAt = new Date(Number(item.created_at) * 1000).toISOString()
      }
      await Promise.allSettled(
        result.jobs
          .map((item) => String(item.id || ''))
          .filter(Boolean)
          .map((jobId) =>
            api.waitGenerationJob(jobId, watcher.signal, STORYBOARD_LINE_WAIT_TIMEOUT_MS),
          ),
      )
      if (watcher.signal.aborted) return
      const script = await api.fetchSongScript(taskId)
      // 侧栏也消费任务状态；切走后完成的批次同样要同步，避免一直显示生成中。
      if (script.status) this._setTaskStatus(taskId, script.status)
      if (this.activeTaskId === taskId) {
        this.taskScripts[taskId] = script
        this.lines = script.lines
        this._cacheCurrentTask()
      }
    } catch (error) {
      for (const line of this.lines) {
        if (uniqueIds.includes(line.id) && line.generationStatus === 'running') {
          line.generationStatus = 'pending'
          line.generationError = error instanceof Error ? error.message : '批量提示词提交失败'
        }
      }
      if (error instanceof ApiError && error.status === 429) return
      throw error
    } finally {
      watcher.abort()
    }
  },

  async retryStoryboardLine(lineId: string) {
    if (!this.activeTaskId) return
    await this._generateStoryboardQueue(this.activeTaskId, [lineId], true)
  },

  /** 只同步已有提示词工单，不创建新任务，也不会再次调用模型。 */
  async refreshStoryboardLineGenerationStatus(
    lineId: string,
  ): Promise<'queued' | 'running' | 'succeeded' | 'failed'> {
    if (!this.activeTaskId) throw new Error('当前没有打开的子项目')
    const line = this.lines.find((item) => item.id === lineId)
    if (!line?.generationJobId) throw new Error('该分镜没有可刷新的生成工单')
    const taskId = this.activeTaskId
    const job = await api.getGenerationJob(line.generationJobId)
    const rawStatus = String(job.status || 'running')
    const status: 'queued' | 'running' | 'succeeded' | 'failed' =
      rawStatus === 'queued' ||
      rawStatus === 'running' ||
      rawStatus === 'succeeded' ||
      rawStatus === 'failed'
        ? rawStatus
        : 'failed'
    if (job.created_at)
      line.generationStartedAt = new Date(Number(job.created_at) * 1000).toISOString()
    if (status === 'queued' || status === 'running') return status
    const fresh = await api.fetchStoryboardLine(taskId, lineId)
    const index = this.lines.findIndex((item) => item.id === lineId)
    if (this.activeTaskId === taskId && index >= 0) this.lines[index] = fresh
    this._cacheCurrentTask()
    return status
  },

  async retryFailedStoryboardLines() {
    if (!this.activeTaskId) return
    const { lineIds } = await api.resetFailedStoryboardLines(this.activeTaskId)
    await this._generateStoryboardBatch(this.activeTaskId, lineIds, true)
  },

  /** 批量生成：一次提交最多100条持久工单，执行并发由 storyboard worker 统一控制。 */
  async generateAllPendingStoryboardLines() {
    const taskId = this.activeTaskId
    if (!taskId) return
    const lineIds = this.lines
      .filter(
        (line) =>
          (line.generationStatus === 'pending' || line.generationStatus === 'failed') &&
          this._outlineReady(line),
      )
      .map((line) => line.id)
    if (!lineIds.length) return
    await this._generateStoryboardBatch(taskId, lineIds)
  },

  /** 刷新/切任务后恢复仍在排队或执行中的媒体生成（场景图/视频）等待态；结果由后端落库，落定后重新拉取合并 */
  async resumeActiveGenerations(taskId: string) {
    const jobs = await api.fetchActiveGenerations(taskId).catch(() => [])
    for (const job of jobs) {
      if (!job.storyboardLineId || resumedGenerationJobs.has(job.id)) continue
      const line = this.lines.find((item) => item.id === job.storyboardLineId)
      if (!line) continue
      if (job.kind === 'storyboard_line') {
        line.generationStatus = 'running'
        line.generationJobId = job.id
        resumedGenerationJobs.add(job.id)
        const watcher = registerTaskWatcher(taskId)
        void (async () => {
          try {
            await api.waitGenerationJob(job.id, watcher.signal, STORYBOARD_LINE_WAIT_TIMEOUT_MS)
            const fresh = await api.fetchStoryboardLine(taskId, job.storyboardLineId!)
            const index = this.lines.findIndex((item) => item.id === job.storyboardLineId)
            if (this.activeTaskId === taskId && index >= 0) this.lines[index] = fresh
          } catch (error) {
            if (watcher.signal.aborted || error instanceof PollingCancelledError) return
            const current = this.lines.find((item) => item.id === job.storyboardLineId)
            if (current) {
              current.generationStatus = 'failed'
              current.generationError =
                error instanceof Error ? error.message : '单条视频提示词生成失败'
              current.generationErrorSummary = '提示词生成失败，请查看详情'
              current.generationFailedAt = new Date().toISOString()
            }
          } finally {
            watcher.abort()
            resumedGenerationJobs.delete(job.id)
          }
        })()
        continue
      }
      const slot = job.kind === 'video' ? line.shot : line.scene
      if (slot.status === 'generating') continue
      slot.status = 'generating'
      slot.error = undefined
      if (job.kind === 'video') {
        line.shot.generationSubmittedAt = job.createdAt
      }
      resumedGenerationJobs.add(job.id)
      void this._watchGenerationJob(taskId, job.id, job.storyboardLineId, job.kind)
    }
  },

  async _watchGenerationJob(
    taskId: string,
    jobId: string,
    lineId: string,
    kind: 'image' | 'video',
  ) {
    const watcher = registerTaskWatcher(taskId)
    let failed: string | undefined
    try {
      await api.waitGenerationJob(jobId, watcher.signal, kind === 'video' ? 1_260_000 : 660_000)
    } catch (error) {
      // 切换子项目被取消：后端任务照跑且资产落库，切回时会重新恢复，静默退出
      if (error instanceof PollingCancelledError) return
      failed =
        error instanceof Error
          ? error.message
          : kind === 'video'
            ? '视频生成失败'
            : '场景图生成失败'
    } finally {
      resumedGenerationJobs.delete(jobId)
    }
    if (this.activeTaskId !== taskId) return
    // P2 切换路径瘦身：只拉取该行（单行全量端点）做增量合并，不再全量拉脚本；
    // 后端在任务成功时已把资产落库，只合并媒体子状态，不覆盖用户正在编辑的提示词
    const freshLine = await api.fetchStoryboardLine(taskId, lineId).catch(() => null)
    if (!freshLine || this.activeTaskId !== taskId) return
    const current = this.lines.find((item) => item.id === lineId)
    if (!current) return
    if (kind === 'video') current.shot = freshLine.shot
    else current.scene = freshLine.scene
    if (failed) {
      const slot = kind === 'video' ? current.shot : current.scene
      slot.status = 'failed'
      slot.error = failed
    }
  },

  /** 懒加载某行的完整视频资产历史（详情弹窗打开时调用；脚本载入默认只带当前选用资产） */
  async ensureShotHistory(lineId: string) {
    const line = this.lines.find((l) => l.id === lineId)
    const taskId = this.activeTaskId
    if (!line || !taskId) return
    const total = line.shot.assetCount ?? line.shot.assets.length
    if (total <= line.shot.assets.length) return
    const fresh = await api.fetchStoryboardLine(taskId, lineId).catch(() => null)
    if (!fresh || this.activeTaskId !== taskId) return
    const current = this.lines.find((l) => l.id === lineId)
    if (!current) return
    current.shot.assets = fresh.shot.assets
    current.shot.assetCount = fresh.shot.assets.length
    if (fresh.shot.currentAssetId) {
      current.shot.currentAssetId = fresh.shot.currentAssetId
      const asset = fresh.shot.assets.find((a) => a.id === fresh.shot.currentAssetId)
      if (asset) current.shot.imageUrl = asset.coverUrl
    }
  },

  /** 刷新前被中断的逐句提示词生成：后端孤儿请求仍会跑完并落库，轮询任务直至行状态落定后合并 */
  async _watchRunningStoryboardLines(taskId: string) {
    if (storyboardRunningWatchers.has(taskId)) return
    storyboardRunningWatchers.add(taskId)
    const watcher = registerTaskWatcher(taskId)
    try {
      for (let attempt = 0; attempt < 60; attempt++) {
        await abortableSleep(5000, watcher.signal)
        if (watcher.signal.aborted || this.activeTaskId !== taskId) return
        const fresh = await api.fetchSongScript(taskId, true).catch(() => null)
        if (!fresh || this.activeTaskId !== taskId) return
        if (fresh.status) this._setTaskStatus(taskId, fresh.status)
        for (const freshLine of fresh.lines) {
          const current = this.lines.find((item) => item.id === freshLine.id)
          if (
            current &&
            current.generationStatus === 'running' &&
            !localGeneratingLines.has(current.id) &&
            freshLine.generationStatus !== 'running'
          ) {
            current.scenePrompt = freshLine.scenePrompt
            current.shotPrompt = freshLine.shotPrompt
            current.digitalHumanIds = freshLine.digitalHumanIds
            current.generationStatus = freshLine.generationStatus
            current.generationError = freshLine.generationError
            current.generationErrorSummary = freshLine.generationErrorSummary
            current.generationJobId = freshLine.generationJobId
            current.generationFailedAt = freshLine.generationFailedAt
            current.generationAttempt = freshLine.generationAttempt
          }
        }
        if (!fresh.lines.some((line) => line.generationStatus === 'running')) return
      }
    } finally {
      storyboardRunningWatchers.delete(taskId)
    }
  },
} satisfies ThisType<ProjectContext>
