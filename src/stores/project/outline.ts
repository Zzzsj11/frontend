import type { OutlinePlannedLine, OutlineProgress, ShotGenOptions } from '../../types'
import * as api from '../../api/domain'
import { ApiError, reportApiError } from '../../errorBus'
import { normalizeShotOptions } from '../../mediaConstraints'
import { OUTLINE_WATCH_TIMEOUT_MS } from '../../generationConstraints'
import { abortableSleep, registerTaskWatcher } from '../../utils/generationPoller'
import type { ProjectContext } from './contracts'

export const outlineActions = {
  openOutline() {
    if (this.activeTaskId && this.activeStoryBible) this.outlineOpen = true
  },

  closeOutline() {
    // 只锁「当前任务自己」的生成中状态；其他任务生成中不影响本任务弹窗关闭
    if (this.outlineLocked) return
    this.outlineOpen = false
  },

  /** 同步任务状态到当前编辑区与侧边栏任务列表 */
  _setTaskStatus(taskId: string, status: string) {
    if (this.activeTaskId === taskId) this.activeTaskStatus = status
    for (const song of this.songProjects) {
      const task = song.tasks.find((item) => item.id === taskId)
      if (task) {
        task.status = status
        break
      }
    }
  },

  /** 把大纲规划结果回填到行：镜头类型/人物/时长/参数，清空旧提示词等待逐句生成 */
  _applyOutlineLines(plannedLines: OutlinePlannedLine[]) {
    for (const planned of plannedLines) {
      const line = this.lines.find((item) => item.id === planned.id)
      if (!line) continue
      line.shotType = planned.shotType
      if (planned.plannedDuration) line.plannedDuration = planned.plannedDuration
      if (planned.shotOptions)
        line.shotOptions = normalizeShotOptions({
          ...line.shotOptions,
          ...planned.shotOptions,
        } as ShotGenOptions)
      line.digitalHumanIds = [...planned.digitalHumanIds]
      line.scenePrompt = ''
      line.shotPrompt = ''
      line.generationStatus = 'pending'
      line.generationError = undefined
    }
  },

  /**
   * 订阅大纲进度；连接超时仅重新查询/订阅，不代表后台工单失败。
   * 服务端只在 status 离开 outlining 后关闭流；僵尸任务（后台丢失）时流不会关闭，由看门狗兜底。
   */
  async _watchOutline(taskId: string): Promise<'completed' | 'timeout' | 'navigation-cancelled'> {
    // 注册到任务 watcher：切换子项目时 SSE 立即停止（后端大纲生成照跑，切回后重新订阅）
    const controller = registerTaskWatcher(taskId)
    let lastEventAt = Date.now()
    let watchdogTimedOut = false
    let observedJobId = ''
    const watchdog = window.setInterval(() => {
      if (Date.now() - lastEventAt > 150_000) {
        watchdogTimedOut = true
        controller.abort()
      }
    }, 1000)
    try {
      await api.streamStoryboardOutline(
        taskId,
        (event) => {
          lastEventAt = Date.now()
          this.outlineProgress = event.progress
          observedJobId = String(event.progress?.jobId ?? observedJobId)
          this._setTaskStatus(taskId, event.status)
        },
        controller.signal,
      )
      if (observedJobId)
        await api.acknowledgeGenerationResults([observedJobId]).catch(() => undefined)
      return 'completed'
    } catch (error) {
      if (controller.signal.aborted) return watchdogTimedOut ? 'timeout' : 'navigation-cancelled'
      // SSE 连接失败：降级为直接查询一次任务状态
      const fresh = await api.fetchSongScript(taskId).catch(() => null)
      return fresh !== null && fresh.status !== 'outlining' ? 'completed' : 'timeout'
    } finally {
      window.clearInterval(watchdog)
    }
  },

  /** 分镜大纲生成（ASS 上传后自动调用 / 通用分镜创建后自动调用 / 失败后手动重试）：202 受理 + SSE 进度；成功后自动接续逐句提示词生成 */
  async runOutlineGeneration(taskId?: string) {
    const id = taskId ?? this.activeTaskId
    if (
      !id ||
      this.activeTaskId !== id ||
      (this.activeStoryboardType !== 'ass' && this.activeStoryboardType !== 'general') ||
      // 防重入只看同任务：别的子项目正在生成时不阻塞本任务触发
      (this.outlineLoading && this.outlineTaskId === id)
    )
      return
    // 进入时已是 outlining：后台仍在生成（如刷新后续跑），直接订阅进度，不重复触发
    const resumeWatching = this.activeTaskStatus === 'outlining'
    this.outlineLoading = true
    this.outlineTaskId = id
    this.outlineError = null
    this.outlineProgress = null
    this.outlineStartedAt = Date.now()
    this._setTaskStatus(id, 'outlining')
    try {
      // POST 仅提交一次。断线恢复通过持久化状态判断，禁止因观察超时重复生成。
      const watchDeadline = Date.now() + OUTLINE_WATCH_TIMEOUT_MS
      for (let attempt = 0; Date.now() < watchDeadline && this.activeTaskId === id; attempt++) {
        if (attempt === 0 && !resumeWatching) {
          try {
            await api.regenerateStoryboardOutline(id)
          } catch (error) {
            if (!(error instanceof ApiError && error.status === 409)) throw error
          }
        }
        const watchResult = await this._watchOutline(id)
        if (watchResult === 'navigation-cancelled') return
        if (watchResult === 'completed') break
        const current = await api.fetchSongScript(id)
        this._setTaskStatus(id, current.status)
        if (current.status !== 'outlining') break
        await abortableSleep(5000)
      }
      if (this.activeTaskId !== id) return
      // 终态后全量刷新（storyBible 含 failedSegments，行含最新大纲规划）
      const fresh = await api.fetchSongScript(id)
      if (this.activeTaskId !== id) return
      this.activeStoryBible = fresh.storyBible ?? null
      this.castIds = [...fresh.cast]
      this.lines = fresh.lines
      this._setTaskStatus(id, fresh.status)
      if (fresh.status === 'outline_failed' || fresh.status === 'outlining') {
        this.outlineError =
          // SSE 回调中的赋值对 TS 控制流分析不可见，需显式还原类型
          String(fresh.outlineProgress?.error || '') ||
          (this.outlineProgress as OutlineProgress | null)?.error ||
          (fresh.status === 'outlining'
            ? '大纲仍在后台生成，可稍后返回查看进度'
            : '大纲生成失败，请重试')
        return
      }
      // 段级失败的行保持占位标注，不进入逐句生成队列（由段级重试恢复）
      const readyIds = fresh.lines
        .filter((line) => line.shotOptions?.outlineStatus !== 'failed')
        .map((line) => line.id)
      if (readyIds.length) void this._generateStoryboardBatch(id, readyIds)
    } catch (error) {
      const fresh = await api.fetchSongScript(id).catch(() => null)
      if (fresh) this._setTaskStatus(id, fresh.status)
      this.outlineError = error instanceof Error ? error.message : '大纲生成失败'
    } finally {
      if (this.outlineTaskId === id) {
        this.outlineLoading = false
        this.outlineTaskId = null
      }
    }
  },

  /** 批量定制通用分镜的非当前子项目：启动大纲、等待落库，再接续逐镜提示词。 */
  async _runSiblingGeneralStoryboard(taskId: string) {
    try {
      await api.regenerateStoryboardOutline(taskId)
      const deadline = Date.now() + OUTLINE_WATCH_TIMEOUT_MS
      while (Date.now() < deadline) {
        const controller = new AbortController()
        const timeout = window.setTimeout(() => controller.abort(), 150_000)
        try {
          await api.streamStoryboardOutline(taskId, () => undefined, controller.signal)
        } catch {
          // SSE 断开后以数据库状态继续等待，不再次 POST。
        } finally {
          window.clearTimeout(timeout)
        }
        const current = await api.fetchSongScript(taskId)
        this._setTaskStatus(taskId, current.status)
        if (current.status !== 'outlining') break
        await abortableSleep(5000)
      }
      const fresh = await api.fetchSongScript(taskId)
      if (fresh.status) this._setTaskStatus(taskId, fresh.status)
      if (fresh.status === 'outline_failed' || fresh.status === 'outlining') return
      this.taskScripts[taskId] = { cast: [...fresh.cast], lines: fresh.lines }
      const readyIds = fresh.lines
        .filter((line) => line.shotOptions?.outlineStatus !== 'failed')
        .map((line) => line.id)
      if (readyIds.length) await this._generateStoryboardBatch(taskId, readyIds)
    } catch {
      // 子项目错误状态由持久化任务和侧边栏刷新呈现，不影响其他组继续执行。
    }
  },

  async regenerateOutline() {
    await this.runOutlineGeneration()
  },

  /** 段级大纲重试：仅重跑指定场景段的第二轮生成，保留其他段成果 */
  async retryOutlineSegment(sceneIndex: number) {
    const taskId = this.activeTaskId
    if (!taskId || this.activeStoryboardType !== 'ass' || this.segmentRetrying[sceneIndex]) return
    this.segmentRetrying = { ...this.segmentRetrying, [sceneIndex]: true }
    try {
      // 202：后台任务已受理；409：后台已有任务在跑，转为轮询等待
      try {
        await api.regenerateStoryboardOutlineSegment(taskId, sceneIndex)
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 409)) throw error
      }
      await this._pollSegmentRetry(taskId, sceneIndex)
      // 后台完成后全量刷新
      const fresh = await api.fetchSongScript(taskId)
      if (this.activeTaskId === taskId && fresh.storyBible) this.activeStoryBible = fresh.storyBible
      // 重试成功的行进入逐句生成队列
      const retriedLineIds = fresh.lines
        .filter((line) => line.shotOptions?.outlineStatus !== 'failed')
        .map((line) => line.id)
      // 只提交那些还没在生成中的行
      const newIds = retriedLineIds.filter(
        (id) =>
          !this.lines.find((line) => line.id === id)?.generationStatus ||
          this.lines.find((line) => line.id === id)?.generationStatus === 'pending',
      )
      if (newIds.length) void this._generateStoryboardBatch(taskId, newIds)
    } catch (error) {
      reportApiError(error, '场景段大纲重新生成失败')
    } finally {
      this.segmentRetrying = { ...this.segmentRetrying, [sceneIndex]: false }
    }
  },

  /** 轮询等待段级重试完成后返回（最多 5 分钟）；切换子项目时随 watcher 立即停止 */
  async _pollSegmentRetry(taskId: string, sceneIndex: number): Promise<void> {
    const deadline = Date.now() + 300_000
    const watcher = registerTaskWatcher(taskId)
    let observedJobId = ''
    while (Date.now() < deadline && this.activeTaskId === taskId && !watcher.signal.aborted) {
      const fresh = await api.fetchSongScript(taskId, true).catch(() => null)
      if (!fresh || this.activeTaskId !== taskId || watcher.signal.aborted) return
      const progress = fresh.outlineProgress as
        { phase?: string; sceneIndex?: number; error?: string; jobId?: string } | undefined
      observedJobId = String(progress?.jobId ?? observedJobId)
      if (progress?.phase === 'segment_retry_failed') {
        throw new Error(progress.error || '场景段大纲重新生成失败')
      }
      // outlineProgress 被清掉或 phase 不是 segment_retry 说明任务已结束
      if (!progress || progress.phase !== 'segment_retry' || progress.sceneIndex !== sceneIndex) {
        if (observedJobId)
          await api.acknowledgeGenerationResults([observedJobId]).catch(() => undefined)
        return
      }
      await abortableSleep(2000, watcher.signal)
    }
  },
} satisfies ThisType<ProjectContext>
