import { useGenerationPreferences } from '../generationPreferences'
import type { CreativeReferenceMedia, ShotGenOptions } from '../../types'
import * as api from '../../api/domain'
import { normalizeShotOptions } from '../../mediaConstraints'
import { DEFAULT_SHOT_OPTIONS } from './shared'
import type { ProjectContext } from './contracts'

export const linesActions = {
  // ---------- 分镜行编辑 ----------
  async addLine() {
    const taskId = this.activeTaskId
    if (!taskId) return
    const defaults = this.activeStoryboardConfig.videoModelDefaults as
      Partial<ShotGenOptions> | undefined
    const saved = await api.createStoryboardLine(taskId, {
      source: 'manual',
      lyrics: '',
      scene_prompt: '',
      shot_prompt: '',
      digital_human_ids: [],
      shot_options: normalizeShotOptions({ ...DEFAULT_SHOT_OPTIONS, ...defaults }),
    })
    if (this.activeTaskId !== taskId) return
    saved.manual = true
    this.lines.push(saved)
    this.selectedLineId = saved.id
  },

  async addCreativeLine(input: {
    originalPrompt: string
    optimizedPrompt: string
    referenceMedia: CreativeReferenceMedia[]
    optimizerProvider: 'gemini' | 'minimax'
    optimizationTaskId?: string
    options: ShotGenOptions
  }) {
    const taskId = this.activeTaskId
    if (!taskId) throw new Error('请先选择一个项目')
    const saved = await api.createStoryboardLine(taskId, {
      source: 'creative',
      shot_type: 'creative',
      planned_duration: input.options.duration,
      lyrics: '',
      scene_prompt: '',
      shot_prompt: input.optimizedPrompt,
      original_prompt: input.originalPrompt,
      optimized_prompt: input.optimizedPrompt,
      reference_media: input.referenceMedia,
      optimizer_provider: input.optimizerProvider,
      optimization_task_id: input.optimizationTaskId,
      shot_options: input.options,
      digital_human_ids: [],
    })
    if (this.activeTaskId !== taskId) throw new DOMException('已切换子项目', 'AbortError')
    const line = saved
    line.manual = true
    this.lines.push(line)
    this.selectedLineId = line.id
    this.creativeOpen = false
    return line
  },

  async removeLine(lineId: string) {
    const idx = this.lines.findIndex((l) => l.id === lineId)
    if (idx < 0) return
    // 脚本生成的分镜不允许删除，仅手动添加的分镜可删
    if (!this.lines[idx].manual) return
    await api.deleteStoryboardLine(lineId)
    const current = this.lines.findIndex((line) => line.id === lineId)
    if (current < 0) return
    this.lines.splice(current, 1)
    if (this.selectedLineId === lineId) {
      this.selectedLineId = this.lines[Math.min(idx, this.lines.length - 1)]?.id ?? null
    }
    this.clampCurrentTime()
  },

  updateLyrics(lineId: string, lyrics: string) {
    const line = this.lines.find((l) => l.id === lineId)
    if (line) {
      line.lyrics = lyrics
      void api.updateStoryboardLine(lineId, { lyrics })
    }
  },

  updateScenePrompt(lineId: string, scenePrompt: string) {
    const line = this.lines.find((l) => l.id === lineId)
    if (line) {
      line.scenePrompt = scenePrompt
      void this.persistManualPrompt(lineId, { scene_prompt: scenePrompt })
    }
  },

  updateShotPrompt(lineId: string, shotPrompt: string) {
    const line = this.lines.find((l) => l.id === lineId)
    if (line) {
      line.shotPrompt = shotPrompt
      void this.persistManualPrompt(lineId, { shot_prompt: shotPrompt })
    }
  },

  async persistManualPrompt(lineId: string, input: Record<string, unknown>) {
    const saved = await api.updateStoryboardLine(lineId, input)
    const line = this.lines.find((item) => item.id === lineId)
    if (line?.generationStatus === 'failed' && saved.generationStatus === 'succeeded') {
      line.generationStatus = 'succeeded'
      line.generationError = undefined
      line.generationErrorSummary = undefined
      line.generationFailedAt = undefined
    }
  },

  updateCreativePrompts(lineId: string, originalPrompt: string, optimizedPrompt: string) {
    const line = this.lines.find((item) => item.id === lineId)
    if (!line || line.source !== 'creative') return
    line.originalPrompt = originalPrompt
    line.optimizedPrompt = optimizedPrompt
    line.shotPrompt = optimizedPrompt
    void api.updateStoryboardLine(lineId, {
      original_prompt: originalPrompt,
      optimized_prompt: optimizedPrompt,
      shot_prompt: optimizedPrompt,
    })
  },

  /** 更新分镜视频生成参数（清晰度 / 时长 / 画幅） */
  updateShotOptions(lineId: string, options: ShotGenOptions) {
    const line = this.lines.find((l) => l.id === lineId)
    if (line) {
      const normalized = normalizeShotOptions(options)
      line.shotOptions = normalized
      void api.updateStoryboardLine(lineId, { shot_options: normalized })
    }
  },

  async applyTaskVideoModel(plan: api.TaskVideoModelPlan) {
    const owner = this.ownerUserId
    const result = await api.changeTaskVideoModel(
      plan.taskId,
      plan.model,
      plan.previewToken,
      plan.channel ?? null,
    )
    if (this.ownerUserId !== owner) return result
    if (result.generationPreferences)
      useGenerationPreferences().selections = result.generationPreferences
    if (this.activeTaskId === plan.taskId) {
      for (const item of result.lines) {
        const line = this.lines.find((line) => line.id === item.id)
        if (line) line.shotOptions = normalizeShotOptions(item.shotOptions)
      }
      this.activeStoryboardConfig = result.task?.storyboardConfig ?? this.activeStoryboardConfig
      this.taskScripts[plan.taskId] = { cast: [...this.castIds], lines: this.lines }
    } else {
      delete this.taskScripts[plan.taskId]
    }
    return result
  },

  /** 切换某分镜的出演角色（只能选全局阵容内的数字人，可多选/可全不选） */
  toggleLineHuman(lineId: string, digitalHumanId: string) {
    const line = this.lines.find((l) => l.id === lineId)
    if (!line || !this.castIds.includes(digitalHumanId)) return
    const idx = line.digitalHumanIds.indexOf(digitalHumanId)
    idx >= 0 ? line.digitalHumanIds.splice(idx, 1) : line.digitalHumanIds.push(digitalHumanId)
    void api.updateStoryboardLine(lineId, { digital_human_ids: line.digitalHumanIds })
  },

  moveLine(fromIndex: number, toIndex: number) {
    if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0) return
    const [moved] = this.lines.splice(fromIndex, 1)
    this.lines.splice(toIndex, 0, moved)
    if (this.activeTaskId)
      void api.reorderStoryboardLines(
        this.activeTaskId,
        this.lines.map((line) => line.id),
      )
  },

  selectLine(lineId: string) {
    this.selectedLineId = lineId
    // 单个分镜模式下，选中后把指针移到片段起点
    const clip = this.timelineClips.find((c) => c.lineId === lineId)
    if (clip && this.playMode.single) this.seek(clip.start)
  },

  /** 从提示词缩略图定位对应时间轴片段，并立即从片段起点播放。 */
  playLineFromStart(lineId: string) {
    this.selectLine(lineId)
    const clip = this.timelineClips.find((item) => item.lineId === lineId)
    if (!clip) return
    this.seek(clip.start)
    this.play()
  },

  openEditor(lineId: string, tab: 'cast' | 'shot' | 'scene' | null = null) {
    this.selectLine(lineId)
    this.editingTab = tab
    this.editingLineId = lineId
  },

  closeEditor() {
    this.editingLineId = null
    this.editingTab = null
  },

  // ---------- 资产库 / 全局角色阵容 ----------
  openLibrary() {
    this.libraryOpen = true
  },

  closeLibrary() {
    this.libraryOpen = false
  },
} satisfies ThisType<ProjectContext>
