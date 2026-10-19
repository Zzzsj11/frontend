import { useAuthStore } from '../auth'
import type { OutlineProgress, ScriptLine, SongProject } from '../../types'
import * as api from '../../api/domain'
import { cancelAllTaskWatchers, cancelTaskWatchers } from '../../utils/generationPoller'
import { sidebarKeys, batchShotKey } from './shared'
import type { ProjectContext } from './contracts'

export const workspaceActions = {
  /** 载入歌曲项目列表（侧边栏挂载时调用） */
  async loadSongProjects() {
    if (this.songProjectsLoading) return
    // 账号切换兜底：属主变化时先清上一账号的工作区现场（主动登出已在 logout 清理，此处覆盖异常路径）
    const ownerUid = useAuthStore().user?.id || ''
    if (this.ownerUserId !== ownerUid) this.resetWorkspace()
    this.ownerUserId = ownerUid
    this.songProjectsLoading = true
    this.songProjectsError = null
    try {
      const [projects, humans, styles] = await Promise.all([
        api.fetchSongProjects(),
        api.fetchDigitalHumans(),
        api.fetchDigitalHumanStyles(),
      ])
      this.songProjects = projects
      this.digitalHumans = humans
      this.dhStyles = styles.map((item) => item.name)
      this.dhStyleIds = Object.fromEntries(styles.map((item) => [item.name, item.id]))
      this.systemDhStyles = styles.filter((item) => item.readOnly).map((item) => item.name)
      void this.resumePendingDigitalHuman()
      // 恢复上次选中的项目和子项目（按用户隔离），无记录则默认第一个
      const auth = useAuthStore()
      const userId = auth.user?.id || ''
      const savedSongId =
        !this.activeSongId && userId ? localStorage.getItem(sidebarKeys(userId).song) : null
      const savedTaskId =
        !this.activeTaskId && userId ? localStorage.getItem(sidebarKeys(userId).task) : null
      const song = savedSongId ? projects.find((p) => p.id === savedSongId) : projects[0]
      if (song) {
        const task = savedTaskId ? song.tasks.find((t) => t.id === savedTaskId) : song.tasks[0]
        if (task) await this._loadTask(song.id, task.id)
        else if (song.tasks[0]) await this._loadTask(song.id, song.tasks[0].id)
        else this.activeSongId = song.id
      }
    } catch (err) {
      this.songProjectsError = err instanceof Error ? err.message : '歌曲项目加载失败'
    } finally {
      this.songProjectsLoading = false
    }
  },

  /** 新建歌曲项目并加入列表 */
  async createSongProject(name: string): Promise<SongProject> {
    const song = await api.createSongProject(name)
    this.songProjects.push(song)
    // Creating a project is also a navigation action. Keep both operations in
    // one store transaction so a concurrent/finishing selection cannot leave
    // the editor attached to the previously active project.
    this._cacheCurrentTask()
    this.songSwitching = true
    try {
      await this._loadTask(song.id, null)
    } finally {
      this.songSwitching = false
    }
    return song
  },

  /** 生成类操作前置：未选中任何项目时自动创建「未命名项目」（每次新建，允许重名） */
  async ensureSongProjectForGeneration(): Promise<void> {
    if (this.activeSongId) return
    await this.createSongProject('未命名项目')
  },

  /** 登出/账号切换时清空工作区现场：取消全部轮询与 SSE 后重置状态，防止串号残留 */
  resetWorkspace() {
    cancelAllTaskWatchers()
    this.$reset()
  },

  /** 把当前子项目(任务)的编辑现场写入缓存 */
  _cacheCurrentTask() {
    if (this.activeTaskId) {
      this.taskScripts[this.activeTaskId] = { cast: this.castIds, lines: this.lines }
    }
  },

  /** 载入指定子项目(任务)的脚本到编辑区（不负责缓存当前，调用方自行处理） */
  async _loadTask(songId: string, taskId: string | null) {
    // 缓存最多保留最近 20 个子项目，避免长时间编辑累积所有脚本。
    const cachedTaskIds = Object.keys(this.taskScripts)
    for (const id of cachedTaskIds.slice(0, Math.max(0, cachedTaskIds.length - 20))) {
      if (id !== this.activeTaskId && id !== taskId) delete this.taskScripts[id]
    }
    const loadVersion = ++this.taskLoadVersion
    // P1 统一轮询调度：切走旧子项目时立即停止其全部轮询/SSE（后端任务照跑，切回后恢复）
    if (this.activeTaskId && this.activeTaskId !== taskId) cancelTaskWatchers(this.activeTaskId)
    // 在等待详情接口前立即切断旧任务上下文，避免已取消的旧 watcher 误判为超时并补发生成请求。
    this.stop()
    this.editingLineId = null
    this.activeSongId = songId
    this.activeTaskId = taskId
    this.activeStoryBible = null
    this.activeStoryboardType = null
    this.activeTaskStatus = null
    this.outlineProgress = null
    this.outlineError = null
    this.activeStoryboardConfig = {}
    this.projectAudio = null
    this.audioTrackVisible = false
    this.audioOffsetSeconds = 0
    this.castIds = []
    this.lines = []
    this.selectedLineId = null
    this.currentTime = 0
    const script = taskId
      ? await api.fetchSongScript(taskId)
      : {
          cast: [],
          lines: [] as ScriptLine[],
          storyboardType: '',
          storyBible: undefined,
          status: '',
        }
    if (loadVersion !== this.taskLoadVersion) return
    if (taskId) this.taskScripts[taskId] = script
    this.castIds = [...script.cast]
    this.lines = script.lines
    const auth = useAuthStore()
    if (songId && auth.user) localStorage.setItem(sidebarKeys(auth.user.id).song, songId)
    if (taskId && auth.user) localStorage.setItem(sidebarKeys(auth.user.id).task, taskId)
    this.activeStoryBible = script.storyBible ?? null
    this.activeStoryboardType = script.storyboardType || null
    this.activeTaskStatus = script.status || null
    this.outlineProgress = (script.outlineProgress as OutlineProgress | undefined) ?? null
    this.outlineError =
      script.status === 'outline_failed'
        ? String(script.outlineProgress?.error || '大纲生成失败，请重试')
        : null
    if (taskId && script.status) this._setTaskStatus(taskId, script.status)
    this.activeStoryboardConfig = script.storyboardConfig ?? {}
    this.projectAudio = script.projectAudio ?? null
    this.audioTrackVisible = Boolean(
      script.projectAudio &&
      (script.storyboardConfig?.audioTrackVisible ?? script.storyboardType === 'ass'),
    )
    this.audioOffsetSeconds = Number(script.storyboardConfig?.audioOffsetSeconds ?? 0)
    this.selectedLineId = this.lines[0]?.id ?? null
    this.currentTime = 0
    if (taskId) {
      void this.restoreMaterialExports(taskId)
      void this.resumeActiveGenerations(taskId)
      // 刷新/切走前批量生成未跑完：恢复进行中状态并续跑剩余行
      if (auth.user && localStorage.getItem(batchShotKey(auth.user.id, taskId)))
        void this.generateAllShots()
      if (
        (script.storyboardType === 'ass' || script.storyboardType === 'general') &&
        (script.status === 'parsed' || script.status === 'outlining')
      ) {
        // parsed：脚本仅完成拆分，自动接续大纲生成；outlining：切回后只恢复订阅
        void this.runOutlineGeneration(taskId)
      } else {
        const pending = this.lines
          .filter((line) => line.generationStatus === 'pending' && this._outlineReady(line))
          .map((line) => line.id)
        if (pending.length) void this._generateStoryboardBatch(taskId, pending)
      }
      // 刷新前仍在逐句生成的行：后端孤儿请求仍会跑完，轮询待其落定后合并
      if (this.lines.some((line) => line.generationStatus === 'running'))
        void this._watchRunningStoryboardLines(taskId)
      // 有失败的场景段：自动重试（后台任务可能还在跑，幂等保护由后端 409 兜底）
      const failedSegments = script.storyBible?.failedSegments ?? []
      if (failedSegments.length) {
        void (async () => {
          for (const seg of failedSegments) {
            if (this.activeTaskId !== taskId) break
            await this.retryOutlineSegment(seg.sceneIndex).catch(() => {})
          }
        })()
      }
    }
  },

  /** 切换到某歌曲的处理任务(子项目)：每个任务是独立脚本，当前编辑现场先写入缓存 */
  async selectSongTask(songId: string, taskId: string | null = null) {
    if (this.songSwitching) return
    // 已在该任务上无需切换（无 taskId 时仅按歌曲判断）
    if (taskId ? taskId === this.activeTaskId : songId === this.activeSongId) return
    this.songSwitching = true
    try {
      this._cacheCurrentTask()
      await this._loadTask(songId, taskId)
    } finally {
      this.songSwitching = false
    }
  },

  /** 重命名歌曲项目(目录) */
  renameSongProject(songId: string, name: string) {
    const song = this.songProjects.find((s) => s.id === songId)
    const trimmed = name.trim()
    if (!song || !trimmed) return
    song.name = trimmed
    void api.updateSongProject(songId, trimmed)
  },

  /** 删除歌曲项目(目录)：连同其下所有子项目与脚本缓存；删除激活项时切到其余首个任务 */
  async deleteSongProject(songId: string) {
    const idx = this.songProjects.findIndex((s) => s.id === songId)
    if (idx < 0) return
    const [removed] = this.songProjects.splice(idx, 1)
    await api.deleteSongProject(songId)
    removed.tasks.forEach((t) => {
      delete this.taskScripts[t.id]
      cancelTaskWatchers(t.id)
    })
    if (songId !== this.activeSongId) return
    // 删除的是当前激活歌曲：切到剩余首个歌曲的首个任务，否则清空编辑区
    const fallback = this.songProjects[0]
    this.songSwitching = true
    try {
      if (fallback) {
        await this._loadTask(fallback.id, fallback.tasks[0]?.id ?? null)
      } else {
        this.stop()
        this.editingLineId = null
        this.lines = []
        this.castIds = []
        this.activeSongId = ''
        this.activeTaskId = null
        this.selectedLineId = null
        this.currentTime = 0
      }
    } finally {
      this.songSwitching = false
    }
  },

  /** 拖拽排序：项目 */
  async reorderSongProjects(order: string[]) {
    const prev = [...this.songProjects]
    this.songProjects = order
      .map((id) => this.songProjects.find((s) => s.id === id)!)
      .filter(Boolean)
    try {
      await api.reorderProjects(order)
    } catch {
      this.songProjects = prev
    }
  },

  /** 拖拽排序：子项目 */
  async reorderSongTasks(songId: string, order: string[]) {
    const song = this.songProjects.find((s) => s.id === songId)
    if (!song) return
    const prev = [...song.tasks]
    song.tasks = order.map((id) => song.tasks.find((t) => t.id === id)!).filter(Boolean)
    try {
      await api.reorderProjectTasks(songId, order)
    } catch {
      song.tasks = prev
    }
  },

  /** 重命名子项目(任务) */
  renameSongTask(songId: string, taskId: string, title: string) {
    const song = this.songProjects.find((s) => s.id === songId)
    const task = song?.tasks.find((t) => t.id === taskId)
    const trimmed = title.trim()
    if (!task || !trimmed) return
    task.title = trimmed
    void api.updateSongTask(taskId, trimmed)
  },

  /** 删除子项目(任务)：删除激活任务时切到同歌曲相邻任务，否则清空编辑区 */
  async deleteSongTask(songId: string, taskId: string) {
    const song = this.songProjects.find((s) => s.id === songId)
    if (!song) return
    const idx = song.tasks.findIndex((t) => t.id === taskId)
    if (idx < 0) return
    song.tasks.splice(idx, 1)
    await api.deleteSongTask(taskId)
    delete this.taskScripts[taskId]
    cancelTaskWatchers(taskId)
    const auth = useAuthStore()
    if (auth.user) localStorage.removeItem(batchShotKey(auth.user.id, taskId))
    if (taskId !== this.activeTaskId) return
    const next = song.tasks[idx] ?? song.tasks[idx - 1]
    this.songSwitching = true
    try {
      if (next) {
        await this._loadTask(song.id, next.id)
      } else {
        this.stop()
        this.editingLineId = null
        this.lines = []
        this.castIds = []
        this.activeTaskId = null
        this.selectedLineId = null
        this.currentTime = 0
      }
    } finally {
      this.songSwitching = false
    }
  },
} satisfies ThisType<ProjectContext>
