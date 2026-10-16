import type { MaterialExport } from '../../types'
import * as api from '../../api/domain'
import { reportApiError } from '../../errorBus'
import { registerTaskWatcher } from '../../utils/generationPoller'
import { exportStreams } from './shared'
import type { ProjectContext } from './contracts'

export const exportActions = {
  _upsertMaterialExport(item: MaterialExport) {
    const items = this.exportsByTaskId[item.taskId] || []
    const current = items.find((entry) => entry.id === item.id)
    // SSE 重连后的快照与连接末尾 GET 可能乱序到达；同一任务只接受更新的快照，且进度不得倒退。
    if (current && Date.parse(item.updatedAt) < Date.parse(current.updatedAt)) return
    const merged =
      current && ['queued', 'running'].includes(item.status) && item.progress < current.progress
        ? { ...item, progress: current.progress }
        : item
    const next = [merged, ...items.filter((entry) => entry.id !== item.id)]
    this.exportsByTaskId[item.taskId] = next.sort((left, right) =>
      right.createdAt.localeCompare(left.createdAt),
    )
  },

  async _watchMaterialExport(item: MaterialExport) {
    if (
      !item.jobId ||
      (exportStreams.has(item.id) && !exportStreams.get(item.id)!.signal.aborted) ||
      ['ready', 'failed'].includes(item.status)
    )
      return
    // 注册到任务 watcher：切换/删除子项目时导出进度 SSE 随任务取消
    const controller = registerTaskWatcher(item.taskId)
    exportStreams.set(item.id, controller)
    try {
      let failures = 0
      while (!controller.signal.aborted) {
        try {
          if (failures === 0) {
            await api.streamMaterialExport(
              item.id,
              (update) => {
                this.exportConnectionIssues[item.id] = false
                this._upsertMaterialExport(update)
              },
              controller.signal,
            )
          }
          if (controller.signal.aborted) return
          const latest = await api.fetchMaterialExport(item.id)
          this._upsertMaterialExport(latest)
          this.exportConnectionIssues[item.id] = false
          if (['ready', 'failed'].includes(latest.status)) {
            if (latest.jobId)
              await api.acknowledgeGenerationResults([latest.jobId]).catch(() => undefined)
            return
          }
          // SSE 不可用时保持轮询；周期性重试实时连接。
          failures = failures > 0 ? (failures + 1) % 12 : 0
        } catch {
          if (controller.signal.aborted) return
          failures += 1
          this.exportConnectionIssues[item.id] = true
        }
        await new Promise<void>((resolve) => {
          const finish = () => {
            clearTimeout(timer)
            controller.signal.removeEventListener('abort', finish)
            resolve()
          }
          const timer = setTimeout(finish, Math.min(10000, 2000 + failures * 500))
          controller.signal.addEventListener('abort', finish, { once: true })
        })
      }
    } finally {
      if (exportStreams.get(item.id) === controller) exportStreams.delete(item.id)
    }
  },

  async restoreMaterialExports(taskId: string) {
    try {
      const items = await api.fetchMaterialExports(taskId)
      this.exportsByTaskId[taskId] = items
      items
        .filter((item) => ['queued', 'running'].includes(item.status))
        .forEach((item) => void this._watchMaterialExport(item))
    } catch (error) {
      reportApiError(error, '导出任务恢复失败')
    }
  },

  async runSynthesize() {
    await this.runExport('materials')
  },

  async runExport(kind: 'materials' | 'video') {
    const taskId = this.activeTaskId
    if (!taskId) return
    const key = `${taskId}:${kind}`
    const active = this.exportsByTaskId[taskId]?.some(
      (item) => (item.kind || 'materials') === kind && ['queued', 'running'].includes(item.status),
    )
    if (active || this.exportSubmitting[key]) return
    this.exportSubmitting[key] = true
    try {
      const item =
        kind === 'video' ? await api.exportVideo(taskId) : await api.exportMaterials(taskId)
      this._upsertMaterialExport(item)
      void this._watchMaterialExport(item)
    } catch (error) {
      reportApiError(error, kind === 'video' ? '合并导出失败' : '导出素材失败')
    } finally {
      this.exportSubmitting[key] = false
    }
  },

  downloadLatestExport() {
    if (!this.synthesis.videoUrl) return
    const link = document.createElement('a')
    link.href = this.synthesis.videoUrl
    link.download = ''
    link.rel = 'noopener'
    link.click()
  },

  cancelExportStreams() {
    exportStreams.forEach((controller) => controller.abort())
    exportStreams.clear()
  },
} satisfies ThisType<ProjectContext>
