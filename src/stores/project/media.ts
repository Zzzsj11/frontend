import { useAuthStore } from '../auth'
import type { ScriptLine, ShotAsset, ShotGenOptions } from '../../types'
import * as api from '../../api/domain'
import { generateVoice } from '../../api/voice'
import { nextId } from '../../utils/id'
import { ApiError, reportApiError } from '../../errorBus'
import { normalizeShotOptions } from '../../mediaConstraints'
import { videoModelConcurrency } from '../../generationModels'
import {
  PollingCancelledError,
  GenerationJobFailed,
  GenerationReconciliationRequired,
  abortableSleep,
  registerTaskWatcher,
} from '../../utils/generationPoller'
import { batchShotKey, BATCH_SHOT_CONCURRENCY, DEFAULT_SHOT_OPTIONS, sceneVariants } from './shared'
import type { ProjectContext } from './contracts'

export const mediaActions = {
  async generateVoiceFor(lineId: string) {
    const line = this.lines.find((l) => l.id === lineId)
    if (!line || line.voice.status === 'generating') return
    line.voice.status = 'generating'
    const { url, duration } = await generateVoice(lineId)
    // 生成期间行可能被删除
    const still = this.lines.find((l) => l.id === lineId)
    if (still) still.voice = { status: 'done', url, duration }
  },

  /** 生成/重新生成场景底图（仅由场景提示词决定） */
  async generateSceneFor(lineId: string, scenePrompt?: string, selectedOptions?: ShotGenOptions) {
    const idx = this.lines.findIndex((l) => l.id === lineId)
    if (idx < 0 || this.lines[idx].scene.status === 'generating') return
    const line = this.lines[idx]
    if (scenePrompt !== undefined) line.scenePrompt = scenePrompt
    if (selectedOptions) line.shotOptions = normalizeShotOptions(selectedOptions)
    line.scene.status = 'generating'
    line.scene.error = undefined
    const variant = sceneVariants[lineId] ?? 0
    sceneVariants[lineId] = variant + 1
    // P1：轮询挂到任务 watcher 上，切换子项目即被取消（后端任务照跑，切回后恢复）
    const watcher = this.activeTaskId ? registerTaskWatcher(this.activeTaskId) : null
    try {
      const options = normalizeShotOptions(line.shotOptions ?? DEFAULT_SHOT_OPTIONS)
      const { imageUrl, thumbnailUrl } = await api.generateSceneImage(
        line.scenePrompt,
        idx,
        variant,
        this.activeTaskId ?? undefined,
        lineId,
        options.ratio,
        options.imageModel,
        options.imageResolution ?? '1K',
        watcher?.signal ?? undefined,
      )
      const still = this.lines.find((l) => l.id === lineId)
      if (still)
        still.scene = {
          status: 'done',
          imageUrl: thumbnailUrl || imageUrl,
          originalImageUrl: imageUrl,
        }
    } catch (error) {
      // 切换子项目导致轮询被取消：保持 generating 等待切回恢复，不标失败不弹窗
      if (error instanceof PollingCancelledError) return
      // 失败状态与原因留在行内（可重试），全局弹窗只做即时反馈；不再 throw，
      // 避免 fire-and-forget 调用产生 unhandled rejection、批量生成被单行失败中断
      const reported = reportApiError(error, '场景图生成失败')
      const still = this.lines.find((l) => l.id === lineId)
      if (still) {
        still.scene.status = 'failed'
        still.scene.error = reported.message
      }
    }
  },

  /** 生成/重新生成分镜视频片段（场景 × 分镜提示词 × 出演角色 × 生成参数）；新片段作为资产追加并选中 */
  async generateShotFor(lineId: string, shotPrompt?: string, options?: ShotGenOptions) {
    if (this.taskVideoModelEditing) return
    const idx = this.lines.findIndex((l) => l.id === lineId)
    if (idx < 0 || this.lines[idx].shot.status === 'generating') return
    const line = this.lines[idx]
    if (line.shot.generationPhase === 'manual_review') return
    if (shotPrompt !== undefined) line.shotPrompt = shotPrompt
    if (options) line.shotOptions = normalizeShotOptions(options)
    const genOptions = normalizeShotOptions(line.shotOptions ?? DEFAULT_SHOT_OPTIONS)
    line.shot.status = 'generating'
    line.shot.error = undefined
    // 历史版本总数（含未懒加载的），用于资产版本序号
    const variant = line.shot.assetCount ?? line.shot.assets.length
    // 通用 MV 的人物镜由视频模型逐镜自由生成，不发送数字人参考图；ASS 仍用头像保护面部身份。
    const characterUrls = line.digitalHumanIds
      .map((id) => {
        const human = this.digitalHumans.find((h) => h.id === id)
        return human?.originalAvatar || human?.avatar
      })
      .filter(Boolean) as string[]
    // P1：轮询挂到任务 watcher 上，切换子项目即被取消（后端任务照跑，切回后恢复）
    const watcher = this.activeTaskId ? registerTaskWatcher(this.activeTaskId) : null
    try {
      const { coverUrl, coverThumbnailUrl, videoUrl, duration } = await api.generateShotVideo(
        line.scenePrompt,
        line.shotPrompt,
        characterUrls,
        idx,
        variant,
        genOptions,
        line.scene.originalImageUrl || line.scene.imageUrl,
        this.activeTaskId ?? undefined,
        lineId,
        watcher?.signal ?? undefined,
        (submittedAt) => {
          const current = this.lines.find((item) => item.id === lineId)
          if (current) current.shot.generationSubmittedAt = submittedAt
        },
        (snapshot) => {
          const current = this.lines.find((item) => item.id === lineId)
          if (current) {
            current.shot.generationPhase = snapshot.phase || 'provider_running'
            current.shot.generationJobId = snapshot.id
          }
        },
      )
      const still = this.lines.find((l) => l.id === lineId)
      if (still) {
        const asset: ShotAsset = {
          id: nextId('asset'),
          coverUrl,
          originalCoverUrl: coverUrl,
          videoUrl,
          duration,
          model: genOptions.videoModel,
          digitalHumanIds: [...line.digitalHumanIds],
        }
        still.shot.assets.push(asset)
        still.shot.currentAssetId = asset.id
        asset.coverUrl = coverThumbnailUrl || coverUrl
        still.shot.imageUrl = asset.coverUrl
        still.shot.assetCount = (still.shot.assetCount ?? still.shot.assets.length - 1) + 1
        still.shot.status = 'done'
        still.shot.error = undefined
      }
    } catch (error) {
      // 切换子项目导致轮询被取消：保持 generating 等待切回恢复，不标失败不弹窗
      if (error instanceof PollingCancelledError) return
      if (error instanceof GenerationReconciliationRequired) {
        const current = this.lines.find((item) => item.id === lineId)
        if (current) {
          current.shot.status = 'failed'
          current.shot.generationPhase = 'manual_review'
          current.shot.error = error.message
        }
        return
      }
      if (
        !(error instanceof GenerationJobFailed) &&
        (!(error instanceof ApiError) ||
          !error.status ||
          error.status >= 500 ||
          [408, 409].includes(error.status))
      ) {
        const current = this.lines.find((item) => item.id === lineId)
        if (current) current.shot.generationPhase = 'reconciling'
        if (this.activeTaskId) void this.resumeActiveGenerations(this.activeTaskId)
        return
      }
      // 同场景图：失败原因入行内状态，不 throw（保留已有资产封面，重试由行内/详情弹窗发起）
      const reported = reportApiError(error, '视频生成失败')
      const still = this.lines.find((l) => l.id === lineId)
      if (still) {
        still.shot.status = 'failed'
        still.shot.error = reported.message
      }
    }
  },

  /** 从资产历史中选用某个视频片段 */
  selectShotAsset(lineId: string, assetId: string) {
    const line = this.lines.find((l) => l.id === lineId)
    const asset = line?.shot.assets.find((a) => a.id === assetId)
    if (line && asset) {
      line.shot.currentAssetId = asset.id
      line.shot.imageUrl = asset.coverUrl
    }
  },

  async generateAllVoices() {
    if (this.batchVoicing) return
    this.batchVoicing = true
    const taskId = this.activeTaskId
    try {
      for (const line of [...this.lines]) {
        // 切换子项目后立即停止批量派发
        if (this.activeTaskId !== taskId) break
        if (!line.source?.startsWith('general') && line.voice.status !== 'done')
          await this.generateVoiceFor(line.id)
      }
    } finally {
      this.batchVoicing = false
    }
  },

  /** 批量生成视频片段：提示词就绪且视频「未生成/失败」的行最多 200 路并发（与后端单用户上限一致）；
   *  单行失败不中断后续（失败原因入行内状态，429 单账号上限由后端兜底并统一弹窗）；
   *  「批量进行中」标记按任务持久化：刷新/切换子任务中断后，回到该任务自动续跑剩余行 */
  async generateAllShots() {
    if (this.batchShooting) return
    this.batchShooting = true
    const taskId = this.activeTaskId
    const auth = useAuthStore()
    const flagKey = taskId && auth.user ? batchShotKey(auth.user.id, taskId) : null
    if (flagKey) localStorage.setItem(flagKey, '1')
    const watcher = taskId ? registerTaskWatcher(taskId) : null
    const interrupted = () => this.activeTaskId !== taskId || Boolean(watcher?.signal.aborted)
    const needsShot = (line: ScriptLine) =>
      line.generationStatus === 'succeeded' &&
      line.shot.status !== 'done' &&
      line.shot.generationPhase !== 'manual_review'
    const pending = [...this.lines].filter(needsShot)
    let cursor = 0
    const worker = async () => {
      while (!interrupted()) {
        const line = pending[cursor]
        cursor += 1
        if (!line) return
        // 刷新恢复时，已在后端生成的行等待落定；其他 worker 继续使用剩余并发槽位。
        await this._awaitShotSettled(line, watcher?.signal)
        if (interrupted()) return
        if (needsShot(line)) await this.generateShotFor(line.id)
      }
    }
    const dispatchConcurrency = pending.length
      ? Math.min(
          BATCH_SHOT_CONCURRENCY,
          ...pending.map((line) =>
            videoModelConcurrency(
              normalizeShotOptions(line.shotOptions ?? DEFAULT_SHOT_OPTIONS).videoModel,
            ),
          ),
        )
      : 0
    try {
      await Promise.all(
        Array.from({ length: Math.min(dispatchConcurrency, pending.length) }, worker),
      )
    } catch (error) {
      if (!(error instanceof PollingCancelledError)) throw error
    } finally {
      this.batchShooting = false
      // 自然跑完才清除标记；被刷新/切换中断时保留，待下次载入该任务续跑
      if (flagKey && !interrupted()) localStorage.removeItem(flagKey)
    }
  },

  /** 等待某行视频生成落定（done/failed），切换子任务可立即打断；超时兜底防止等待态重建失败时卡死后续派发 */
  async _awaitShotSettled(line: ScriptLine, signal?: AbortSignal) {
    for (
      let tick = 0;
      tick < 300 && line.shot.status === 'generating' && !signal?.aborted;
      tick += 1
    ) {
      await abortableSleep(2000, signal)
    }
  },
} satisfies ThisType<ProjectContext>
