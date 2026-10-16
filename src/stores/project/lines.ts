import type { CreativeReferenceMedia, ScriptLine, ShotGenOptions } from '../../types'
import * as api from '../../api/domain'
import { nextId } from '../../utils/id'
import { normalizeShotOptions } from '../../mediaConstraints'
import { DEFAULT_SHOT_OPTIONS } from './shared'
import type { ProjectContext } from './contracts'

export const linesActions = {
  // ---------- 分镜行编辑 ----------
  addLine() {
    const defaults = this.activeStoryboardConfig.videoModelDefaults as
      Partial<ShotGenOptions> | undefined
    const line: ScriptLine = {
      id: nextId(),
      source: 'manual',
      lyrics: '',
      scenePrompt: '',
      shotPrompt: '',
      digitalHumanIds: [],
      voice: { status: 'none' },
      scene: { status: 'none' },
      shot: { status: 'none', assets: [] },
      manual: true,
      shotOptions: normalizeShotOptions({ ...DEFAULT_SHOT_OPTIONS, ...defaults }),
    }
    this.lines.push(line)
    this.selectedLineId = line.id
    if (this.activeTaskId)
      void api
        .createStoryboardLine(this.activeTaskId, {
          source: 'manual',
          lyrics: '',
          scene_prompt: '',
          shot_prompt: '',
          digital_human_ids: [],
          shot_options: line.shotOptions,
        })
        .then((saved) => {
          line.id = saved.id
          this.selectedLineId = saved.id
        })
  },

  async addCreativeLine(input: {
    originalPrompt: string
    optimizedPrompt: string
    referenceMedia: CreativeReferenceMedia[]
    optimizerProvider: 'gemini' | 'minimax'
    optimizationTaskId?: string
    options: ShotGenOptions
  }) {
    if (!this.activeTaskId) throw new Error('请先选择一个项目')
    const saved = await api.createStoryboardLine(this.activeTaskId, {
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
    const line = saved
    line.manual = true
    this.lines.push(line)
    this.selectedLineId = line.id
    this.creativeOpen = false
    return line
  },

  removeLine(lineId: string) {
    const idx = this.lines.findIndex((l) => l.id === lineId)
    if (idx < 0) return
    // 脚本生成的分镜不允许删除，仅手动添加的分镜可删
    if (!this.lines[idx].manual) return
    void api.deleteStoryboardLine(lineId)
    this.lines.splice(idx, 1)
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
    const result = await api.changeTaskVideoModel(plan.taskId, plan.model, plan.previewToken)
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
