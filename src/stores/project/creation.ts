import type {
  GeneralStoryboardRequest,
  RandomGeneralStoryboardRequest,
  ScriptLine,
  StoryBible,
} from '../../types'
import * as api from '../../api/domain'
import { nextId } from '../../utils/id'
import { normalizeShotOptions } from '../../mediaConstraints'
import { cancelTaskWatchers } from '../../utils/generationPoller'
import { mapGeneralStoryboardLines, DEFAULT_SHOT_OPTIONS } from './shared'
import type { ProjectContext } from './contracts'

export const creationActions = {
  // ---------- Mock API 联动 ----------
  openMagic() {
    this.magicError = null
    this.magicOpen = true
  },

  closeMagic() {
    this.magicOpen = false
  },

  openCreative() {
    this.creativeOpen = true
  },

  closeCreative() {
    this.creativeOpen = false
  },

  async openGeneralStoryboard() {
    this.generalStoryboardOpen = true
    this.generalStoryboardError = null
    if (!this.generalStoryboardOptions) {
      try {
        this.generalStoryboardOptions = await api.fetchGeneralStoryboardOptions()
      } catch (err) {
        this.generalStoryboardError = err instanceof Error ? err.message : '加载选项失败'
      }
    }
  },

  closeGeneralStoryboard() {
    if (!this.generalStoryboardLoading) this.generalStoryboardOpen = false
  },

  async openRandomGeneralStoryboard() {
    this.randomGeneralStoryboardOpen = true
    this.randomGeneralStoryboardError = null
    if (!this.generalStoryboardOptions) {
      try {
        this.generalStoryboardOptions = await api.fetchGeneralStoryboardOptions()
      } catch (err) {
        this.randomGeneralStoryboardError = err instanceof Error ? err.message : '加载选项失败'
      }
    }
  },

  closeRandomGeneralStoryboard() {
    if (!this.randomGeneralStoryboardLoading) this.randomGeneralStoryboardOpen = false
  },

  /** 按曲风、人物与镜头规模生成无歌词的通用分镜脚本 */
  async runGeneralStoryboard(req: GeneralStoryboardRequest) {
    if (this.generalStoryboardLoading) return
    this.generalStoryboardLoading = true
    this.generalStoryboardError = null
    try {
      // 全新状态直接点「定制通用分镜」：自动创建未命名项目承载本次生成
      await this.ensureSongProjectForGeneration()
      const response = await api.generateGeneralStoryboard({
        ...req,
        projectId: this.activeSongId,
      })
      const results = response.tasks?.length ? response.tasks : [response]
      const result = results[0]
      const toLines = (items: typeof result.lines): ScriptLine[] =>
        mapGeneralStoryboardLines(items, 'general', (item) => ({
          ...DEFAULT_SHOT_OPTIONS,
          duration: item.plannedDuration ?? DEFAULT_SHOT_OPTIONS.duration,
          ratio: req.ratio,
          resolution: req.resolution,
          imageModel: req.imageModel,
          videoModel: req.videoModel,
        }))
      const lines = toLines(result.lines)
      this._cacheCurrentTask()
      let song = this.songProjects.find((s) => s.id === this.activeSongId)
      if (!song) {
        song = {
          id: nextId('song'),
          name: [req.genre, req.secondaryCategory].filter(Boolean).join('·') || '未命名歌曲',
          tasks: [],
        }
        this.songProjects.push(song)
        this.activeSongId = song.id
      }
      const task = {
        id: result.taskId,
        title: result.title,
        updatedAt: '刚刚',
        status: 'parsed',
        storyboardType: 'general',
      }
      song.tasks.push(task)
      for (const sibling of results.slice(1)) {
        song.tasks.push({
          id: sibling.taskId,
          title: sibling.title,
          updatedAt: '刚刚',
          status: 'parsed',
          storyboardType: 'general',
        })
        this.taskScripts[sibling.taskId] = {
          cast: [...sibling.cast],
          lines: toLines(sibling.lines),
        }
      }
      // P1：切到新子项目前停止旧任务的轮询/SSE
      if (this.activeTaskId && this.activeTaskId !== task.id) cancelTaskWatchers(this.activeTaskId)
      this.stop()
      this.editingLineId = null
      this.castIds = [...result.cast]
      this.lines = lines
      this.taskScripts[task.id] = { cast: this.castIds, lines: this.lines }
      this.activeTaskId = task.id
      this.activeStoryBible =
        (result as typeof result & { storyboardConfig?: { storyBible?: StoryBible } })
          .storyboardConfig?.storyBible ?? null
      this.activeStoryboardType = 'general'
      this.activeTaskStatus = 'parsed'
      this.activeStoryboardConfig = { audioTrackVisible: false, audioOffsetSeconds: 0 }
      this.audioTrackVisible = false
      this.audioOffsetSeconds = 0
      this.selectedLineId = this.lines[0]?.id ?? null
      this.currentTime = 0
      this.generalStoryboardOpen = false
      // 异步触发大纲生成：复用 ASS 的 SSE 订阅 + 僵尸恢复 + 完成后自动接续逐句生成
      void Promise.allSettled(
        results.slice(1).map((item) => this._runSiblingGeneralStoryboard(item.taskId)),
      )
      void this.runOutlineGeneration(task.id)
    } catch (err) {
      this.generalStoryboardError = err instanceof Error ? err.message : '定制通用分镜生成失败'
    } finally {
      this.generalStoryboardLoading = false
    }
  },

  /** 无大纲、无场景图：创建相同提示词的随机分镜并立即批量提交纯文本视频。 */
  async runRandomGeneralStoryboard(req: RandomGeneralStoryboardRequest) {
    if (this.randomGeneralStoryboardLoading) return
    this.randomGeneralStoryboardLoading = true
    this.randomGeneralStoryboardError = null
    try {
      await this.ensureSongProjectForGeneration()
      const response = await api.generateRandomGeneralStoryboard({
        ...req,
        projectId: this.activeSongId,
      })
      const results = response.tasks?.length ? response.tasks : [response]
      const result = results[0]
      const toLines = (items: typeof result.lines): ScriptLine[] =>
        mapGeneralStoryboardLines(items, 'general_random', () => DEFAULT_SHOT_OPTIONS)
      const lines = toLines(result.lines)
      this._cacheCurrentTask()
      const song = this.songProjects.find((item) => item.id === this.activeSongId)
      if (!song) throw new Error('项目不存在')
      const task = {
        id: result.taskId,
        title: result.title,
        updatedAt: '刚刚',
        status: 'ready',
        storyboardType: 'general_random',
      }
      song.tasks.push(task)
      const siblingBatches = results.slice(1).map((sibling) => {
        const siblingLines = toLines(sibling.lines)
        song.tasks.push({
          id: sibling.taskId,
          title: sibling.title,
          updatedAt: '刚刚',
          status: 'ready',
          storyboardType: 'general_random',
        })
        this.taskScripts[sibling.taskId] = { cast: [], lines: siblingLines }
        return { taskId: sibling.taskId, lines: siblingLines }
      })
      if (this.activeTaskId && this.activeTaskId !== task.id) cancelTaskWatchers(this.activeTaskId)
      this.stop()
      this.editingLineId = null
      this.castIds = []
      this.lines = lines
      this.taskScripts[task.id] = { cast: [], lines }
      this.activeTaskId = task.id
      this.activeStoryBible = null
      this.activeStoryboardType = 'general_random'
      this.activeTaskStatus = 'ready'
      this.activeStoryboardConfig = { audioTrackVisible: false, audioOffsetSeconds: 0 }
      this.audioTrackVisible = false
      this.audioOffsetSeconds = 0
      this.selectedLineId = lines[0]?.id ?? null
      this.currentTime = 0
      this.randomGeneralStoryboardOpen = false
      void Promise.all([
        this._generateRandomShotsBatch(task.id, lines),
        ...siblingBatches.map((item) => this._generateRandomShotsBatch(item.taskId, item.lines)),
      ])
    } catch (err) {
      this.randomGeneralStoryboardError =
        err instanceof Error ? err.message : '随机通用分镜生成失败'
    } finally {
      this.randomGeneralStoryboardLoading = false
    }
  },

  /** 随机通用没有图片/人物参考，创建任务后一次性把全部纯文本视频持久化入队。 */
  async _generateRandomShotsBatch(taskId: string, lines: ScriptLine[]) {
    const targets = lines.filter((line) => line.shot.status !== 'done')
    if (!targets.length) return
    for (const line of targets) {
      line.shot.status = 'generating'
      line.shot.error = undefined
    }
    try {
      const result = await api.submitVideoGenerationsBatch(
        targets.map((line) => {
          const options = normalizeShotOptions(line.shotOptions ?? DEFAULT_SHOT_OPTIONS)
          return {
            prompt: line.shotPrompt,
            duration: options.duration,
            ratio: options.ratio,
            resolution: options.resolution,
            model: options.videoModel,
            image_urls: [],
            video_urls: [],
            audio_urls: [],
            generate_audio: options.generateAudio ?? false,
            watermark: options.watermark ?? false,
            project_task_id: taskId,
            storyboard_line_id: line.id,
          }
        }),
      )
      await Promise.allSettled(
        result.jobs
          .map((item) => String(item.id || ''))
          .filter(Boolean)
          .map((jobId) => api.waitGenerationJob(jobId)),
      )
      const script = await api.fetchSongScript(taskId)
      if (this.activeTaskId === taskId) {
        this.taskScripts[taskId] = script
        this.lines = script.lines
        this.activeTaskStatus = script.status || this.activeTaskStatus
        this._cacheCurrentTask()
      }
    } catch (error) {
      for (const line of targets) {
        if (line.shot.status === 'generating') {
          line.shot.status = 'failed'
          line.shot.error = error instanceof Error ? error.message : '批量视频提交失败'
        }
      }
    }
  },

  /** 提交魔法脚本表单：生成成功后在当前歌曲目录下新建一个子项目(任务)并载入生成的脚本 */
  async runMagicScript(req?: api.MagicScriptRequest) {
    if (this.magicLoading) return
    this.magicLoading = true
    this.magicError = null
    try {
      if (!req) throw new Error('缺少 ASS 视频参数')
      // 全新状态直接点「ASS 视频」：自动创建未命名项目承载本次生成
      await this.ensureSongProjectForGeneration()
      const script = await api.generateMagicScript({ ...req, projectId: this.activeSongId })
      // 脚本自带统一的角色阵容
      const lines: ScriptLine[] = script.lines.map((item) => ({
        id: item.id || nextId(),
        source: 'ass',
        shotType: item.shotType,
        plannedDuration: item.plannedDuration,
        start: item.start,
        end: item.end,
        lyrics: item.lyrics,
        scenePrompt: item.scenePrompt,
        shotPrompt: item.shotPrompt,
        digitalHumanIds: [...item.digitalHumanIds],
        voice: { status: 'none' },
        scene: { status: 'none' },
        shot: { status: 'none', assets: [] },
        shotOptions: normalizeShotOptions(
          item.shotOptions ?? {
            ...DEFAULT_SHOT_OPTIONS,
            duration: item.plannedDuration ?? DEFAULT_SHOT_OPTIONS.duration,
            ratio: req.ratio,
            resolution: req.resolution,
            imageModel: req.imageModel,
            videoModel: req.videoModel,
          },
        ),
        generationStatus: item.generationStatus || 'pending',
      }))
      // 先缓存当前子项目编辑现场，避免被新脚本覆盖丢失
      this._cacheCurrentTask()
      // 在当前歌曲目录下创建一个新的子项目(任务)
      let song = this.songProjects.find((s) => s.id === this.activeSongId)
      if (!song) {
        song = { id: nextId('song'), name: '未命名歌曲', tasks: [] }
        this.songProjects.push(song)
        this.activeSongId = song.id
      }
      const task = {
        id: script.taskId,
        title: script.title,
        updatedAt: '刚刚',
        status: script.status || 'parsed',
        storyboardType: 'ass',
      }
      song.tasks.push(task)
      // P1：切到新子项目前停止旧任务的轮询/SSE
      if (this.activeTaskId && this.activeTaskId !== task.id) cancelTaskWatchers(this.activeTaskId)
      // 载入生成结果到新子项目
      this.stop()
      this.editingLineId = null
      this.castIds = [...script.cast]
      this.lines = lines
      this.taskScripts[task.id] = { cast: this.castIds, lines: this.lines }
      this.activeTaskId = task.id
      this.activeStoryBible =
        (script as typeof script & { storyBible?: StoryBible }).storyBible ?? null
      this.activeStoryboardType = 'ass'
      this.activeTaskStatus = script.status || 'parsed'
      this.activeStoryboardConfig = {
        audioTrackVisible: Boolean(script.projectAudio),
        audioOffsetSeconds: 0,
      }
      this.projectAudio = script.projectAudio ?? null
      this.audioTrackVisible = Boolean(script.projectAudio)
      this.audioOffsetSeconds = 0
      this.selectedLineId = this.lines[0]?.id ?? null
      this.currentTime = 0
      this.magicOpen = false
      // 两阶段流程：上传仅完成时间轴拆分（parsed），自动接续大纲生成；大纲成功后再启动逐句提示词生成
      void this.runOutlineGeneration(task.id)
    } catch (err) {
      this.magicError = err instanceof Error ? err.message : 'ASS 视频生成失败'
    } finally {
      this.magicLoading = false
    }
  },
} satisfies ThisType<ProjectContext>
