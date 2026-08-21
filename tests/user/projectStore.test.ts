import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../../src/stores/auth'
import { useProjectStore } from '../../src/stores/project'
import { VIDEO_MODEL_OPTIONS } from '../../src/generationModels'
import type {
  DigitalHuman,
  MaterialExport,
  ScriptLine,
  SongProject,
  StoryBible,
} from '../../src/types'

describe('project user journey state', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('plays the full MV by default instead of limiting playback to one video', () => {
    const store = useProjectStore()
    expect(store.playMode.single).toBe(false)
  })

  it('selects a line, seeks to its clip start, and starts playback from a thumbnail', () => {
    const store = useProjectStore()
    store.lines = [
      {
        id: 'line-1',
        generationStatus: 'succeeded',
        digitalHumanIds: [],
        voice: { status: 'none' },
        scene: { status: 'none' },
        shot: {
          status: 'done',
          assets: [{ id: 'asset-1', videoUrl: '/one.mp4', duration: 4, isCurrent: true }],
          currentAssetId: 'asset-1',
        },
      },
      {
        id: 'line-2',
        generationStatus: 'succeeded',
        digitalHumanIds: [],
        voice: { status: 'none' },
        scene: { status: 'none' },
        shot: {
          status: 'done',
          assets: [{ id: 'asset-2', videoUrl: '/two.mp4', duration: 6, isCurrent: true }],
          currentAssetId: 'asset-2',
        },
      },
    ] as ScriptLine[]
    store.currentTime = 1

    store.playLineFromStart('line-2')

    expect(store.selectedLineId).toBe('line-2')
    expect(store.currentTime).toBe(4)
    expect(store.isPlaying).toBe(true)
    store.pause()
  })

  it('persists digital-human style changes through the API, not localStorage', async () => {
    const store = useProjectStore()
    const request = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id: 'style-private-1', name: '测试风格' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    store.addDhStyle('测试风格')
    await vi.waitFor(() => expect(request).toHaveBeenCalled())
    expect(store.dhStyles).toContain('测试风格')
    expect(localStorage.getItem('mv-dh-styles')).toBeNull()
    expect(request).toHaveBeenCalledWith(
      '/api/digital-human-styles',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('loads generated scene and video assets into a shot', async () => {
    const store = useProjectStore()
    const line: ScriptLine = {
      id: 'line-test',
      source: 'manual',
      lyrics: '',
      scenePrompt: '',
      shotPrompt: '',
      digitalHumanIds: [],
      voice: { status: 'none' },
      scene: { status: 'none' },
      shot: { status: 'none', assets: [] },
    }
    store.lines = [line]
    store.activeTaskId = 'task-test'
    line.scenePrompt = 'sunlit room'
    line.shotPrompt = 'slow push in'
    line.scene.imageUrl = undefined
    line.shot.assets = []

    const responses = [
      { id: 'image-job', status: 'queued', progress: 0 },
      { id: 'image-job', status: 'succeeded', progress: 100, result: { urls: ['/scene.png'] } },
      { id: 'video-job', status: 'queued', progress: 0 },
      {
        id: 'video-job',
        status: 'succeeded',
        progress: 100,
        result: { coverUrl: '/scene.png', videoUrl: '/shot.mp4', duration: 5 },
      },
    ]
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      async () =>
        new Response(JSON.stringify(responses.shift()), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    )

    await store.generateSceneFor(line.id)
    await store.generateShotFor(line.id)
    expect(line.scene.imageUrl).toBe('/scene.png')
    expect(line.shot.status).toBe('done')
    expect(line.shot.assets[0]?.videoUrl).toBe('/shot.mp4')
  })

  it('marks failed media generation with reason on the line and recovers on retry', async () => {
    const store = useProjectStore()
    const line: ScriptLine = {
      id: 'line-fail',
      source: 'manual',
      lyrics: '',
      scenePrompt: 'sunlit room',
      shotPrompt: 'slow push in',
      digitalHumanIds: [],
      voice: { status: 'none' },
      scene: { status: 'none' },
      shot: { status: 'none', assets: [] },
    }
    store.lines = [line]
    store.activeTaskId = 'task-test'

    // 轮询第一次直接返回终态，避免命中 waitForJob 的 3s 轮询间隔
    const responses = [
      { id: 'image-job-1', status: 'queued', progress: 0 },
      { id: 'image-job-1', status: 'failed', progress: 100, error: '图片供应商超时' },
      { id: 'image-job-2', status: 'queued', progress: 0 },
      { id: 'image-job-2', status: 'succeeded', progress: 100, result: { urls: ['/scene.png'] } },
      { id: 'video-job-1', status: 'queued', progress: 0 },
      { id: 'video-job-1', status: 'failed', progress: 100, error: '供应商已拒绝该请求' },
    ]
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      async () =>
        new Response(JSON.stringify(responses.shift()), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    )

    // 场景图失败：行内留下 failed 状态与失败原因（Promise 正常 resolve，不向外抛错）
    await store.generateSceneFor(line.id)
    expect(line.scene.status).toBe('failed')
    expect(line.scene.error).toContain('图片供应商超时')

    // 失败后可原地重试，成功恢复 done 并清除失败原因
    await store.generateSceneFor(line.id)
    expect(line.scene.status).toBe('done')
    expect(line.scene.imageUrl).toBe('/scene.png')
    expect(line.scene.error).toBeUndefined()

    // 视频失败：同样记录状态与原因
    await store.generateShotFor(line.id)
    expect(line.shot.status).toBe('failed')
    expect(line.shot.error).toContain('供应商已拒绝该请求')
  })

  it('keeps simultaneous material exports isolated by task', () => {
    const store = useProjectStore()
    const item = (id: string, taskId: string, progress: number): MaterialExport => ({
      id,
      taskId,
      jobId: `job-${id}`,
      status: 'running',
      progress,
      stage: `导出 ${progress}%`,
      totalAssets: 2,
      processedAssets: 1,
      totalBytes: 20,
      processedBytes: 10,
      createdAt: `2026-08-10T00:00:0${progress}Z`,
      // 动态时间戳：进度爬升按「当前时间 - updatedAt」折算，固定旧时间会被爬升污染
      updatedAt: new Date().toISOString(),
    })
    store._upsertMaterialExport(item('a', 'task-a', 35))
    store._upsertMaterialExport(item('b', 'task-b', 70))
    store.activeTaskId = 'task-a'
    expect(store.synthesis.progress).toBe(35) // 刚推送（updatedAt=现在）：停滞 0s，不爬升
    store.activeTaskId = 'task-b'
    expect(store.synthesis.progress).toBe(70)
    expect(store.exportsByTaskId['task-a'][0].id).toBe('a')
  })

  it('restores waiting state for in-flight media generation after a reload', async () => {
    const store = useProjectStore()
    const line: ScriptLine = {
      id: 'line-resume',
      source: 'manual',
      lyrics: '',
      scenePrompt: 'sunlit room',
      shotPrompt: 'slow push in',
      digitalHumanIds: [],
      voice: { status: 'none' },
      scene: { status: 'none' },
      shot: { status: 'none', assets: [] },
    }
    store.lines = [line]
    store.activeTaskId = 'task-resume'

    const responses = [
      // 刷新后先拉取仍在执行的生成任务
      [{ id: 'job-video-1', kind: 'video', storyboardLineId: 'line-resume', progress: 40 }],
      // 恢复轮询：任务已成功（后端已把资产落库）
      {
        id: 'job-video-1',
        status: 'succeeded',
        progress: 100,
        result: { coverUrl: '/cover.png', videoUrl: '/shot.mp4', duration: 5 },
      },
      // P2 增量合并：重新拉取该行（单行全量端点），行数据带上了新资产
      {
        id: 'line-resume',
        source: 'manual',
        lyrics: '',
        scenePrompt: 'sunlit room',
        shotPrompt: 'slow push in',
        digitalHumanIds: [],
        shotAssets: [
          {
            id: 'asset-1',
            coverUrl: '/cover.png',
            videoUrl: '/shot.mp4',
            duration: 5,
            isCurrent: true,
          },
        ],
      },
    ]
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      async () =>
        new Response(JSON.stringify(responses.shift()), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    )

    await store.resumeActiveGenerations('task-resume')
    expect(line.shot.status).toBe('generating')
    await vi.waitFor(() => expect(line.shot.status).toBe('done'))
    expect(line.shot.assets[0]?.videoUrl).toBe('/shot.mp4')
    expect(line.shot.currentAssetId).toBe('asset-1')
  })
})

describe('sidebar selection persistence (per user)', () => {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  const song = (id: string, taskIds: string[]): SongProject => ({
    id,
    name: id,
    tasks: taskIds.map((taskId) => ({
      id: taskId,
      title: taskId,
      updatedAt: '',
      status: 'ready',
      storyboardType: 'ass',
    })),
  })

  const projects = [song('song-a', ['task-a1']), song('song-b', ['task-b1', 'task-b2'])]

  const mockShellFetch = () =>
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url === '/api/projects') return json(projects)
      if (url === '/api/digital-humans') return json([])
      if (url === '/api/digital-human-styles') return json([])
      if (url.endsWith('/material-exports')) return json([])
      if (url.endsWith('/generations/active')) return json([])
      if (/^\/api\/tasks\/[^/]+$/.test(url))
        return json({
          cast: [],
          storyboardType: 'ass',
          status: 'ready',
          storyboardConfig: {},
          lines: [],
        })
      return json({}, 404)
    })

  beforeEach(() => {
    setActivePinia(createPinia())
    const auth = useAuthStore()
    auth.user = {
      id: 'u1',
      username: 'u1',
      displayName: 'U1',
      role: 'user',
      mustChangePassword: false,
    }
  })

  it('restores the persisted song and task selection for the current user', async () => {
    localStorage.setItem('mv_sidebar_song_u1', 'song-b')
    localStorage.setItem('mv_sidebar_task_u1', 'task-b2')
    mockShellFetch()
    const store = useProjectStore()

    await store.loadSongProjects()
    expect(store.activeSongId).toBe('song-b')
    expect(store.activeTaskId).toBe('task-b2')
    // 恢复后把选中态回写，保持 localStorage 与实际一致
    expect(localStorage.getItem('mv_sidebar_song_u1')).toBe('song-b')
    expect(localStorage.getItem('mv_sidebar_task_u1')).toBe('task-b2')
  })

  it('falls back to the first song and task when nothing is persisted', async () => {
    mockShellFetch()
    const store = useProjectStore()

    await store.loadSongProjects()
    expect(store.activeSongId).toBe('song-a')
    expect(store.activeTaskId).toBe('task-a1')
    expect(localStorage.getItem('mv_sidebar_song_u1')).toBe('song-a')
    expect(localStorage.getItem('mv_sidebar_task_u1')).toBe('task-a1')
  })

  it('ignores a stale persisted task id and falls back to the first task of the song', async () => {
    localStorage.setItem('mv_sidebar_song_u1', 'song-b')
    localStorage.setItem('mv_sidebar_task_u1', 'task-deleted')
    mockShellFetch()
    const store = useProjectStore()

    await store.loadSongProjects()
    expect(store.activeSongId).toBe('song-b')
    expect(store.activeTaskId).toBe('task-b1')
  })

  it("does not read another user's persisted selection", async () => {
    // 其它用户的记录不生效（key 按用户隔离）
    localStorage.setItem('mv_sidebar_song_other', 'song-b')
    localStorage.setItem('mv_sidebar_task_other', 'task-b2')
    mockShellFetch()
    const store = useProjectStore()

    await store.loadSongProjects()
    expect(store.activeSongId).toBe('song-a')
    expect(store.activeTaskId).toBe('task-a1')
  })

  it('invalidates the previous task before waiting for the new task payload', async () => {
    let resolveTask!: (response: Response) => void
    const pendingTask = new Promise<Response>((resolve) => {
      resolveTask = resolve
    })
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url === '/api/tasks/task-b1?history=0') return pendingTask
      if (url.endsWith('/material-exports') || url.endsWith('/generations/active')) return json([])
      return json({}, 404)
    })
    const store = useProjectStore()
    store.activeSongId = 'song-a'
    store.activeTaskId = 'task-a1'
    store.lines = [{ id: 'old-line' } as ScriptLine]

    const switching = store.selectSongTask('song-b', 'task-b1')

    expect(store.activeSongId).toBe('song-b')
    expect(store.activeTaskId).toBe('task-b1')
    expect(store.lines).toEqual([])
    expect(store.songSwitching).toBe(true)

    resolveTask(
      json({
        cast: [],
        storyboardType: 'ass',
        status: 'ready',
        storyboardConfig: {},
        lines: [],
      }),
    )
    await switching
    expect(store.songSwitching).toBe(false)
  })
})

describe('drag ordering with optimistic update', () => {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  const song = (id: string, taskIds: string[]): SongProject => ({
    id,
    name: id,
    tasks: taskIds.map((taskId) => ({ id: taskId, title: taskId, updatedAt: '' })),
  })

  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('keeps the optimistic project order when the reorder API succeeds', async () => {
    const store = useProjectStore()
    store.songProjects = [song('a', []), song('b', []), song('c', [])]
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async () => json({ ok: true }))

    await store.reorderSongProjects(['c', 'a', 'b'])
    expect(store.songProjects.map((item) => item.id)).toEqual(['c', 'a', 'b'])
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/projects/reorder')
    expect(fetchMock.mock.calls[0][1]?.method).toBe('PATCH')
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ order: ['c', 'a', 'b'] })
  })

  it('rolls back the project order when the reorder API fails', async () => {
    const store = useProjectStore()
    store.songProjects = [song('a', []), song('b', []), song('c', [])]
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => json({ detail: 'boom' }, 500))

    await store.reorderSongProjects(['c', 'a', 'b'])
    expect(store.songProjects.map((item) => item.id)).toEqual(['a', 'b', 'c'])
  })

  it('rolls back the task order within a song when the reorder API fails', async () => {
    const store = useProjectStore()
    store.songProjects = [song('song-1', ['t1', 't2', 't3'])]
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async () => json({ detail: 'boom' }, 500))

    await store.reorderSongTasks('song-1', ['t3', 't1', 't2'])
    expect(store.songProjects[0].tasks.map((task) => task.id)).toEqual(['t1', 't2', 't3'])
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/projects/song-1/tasks/reorder')
  })
})

describe('outline segment retry polling', () => {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  const bible = (failedSegments: unknown[] = []): StoryBible =>
    ({
      failedSegments,
      shots: [],
      scenePlan: [],
      locations: [],
      motifs: [],
    }) as unknown as StoryBible

  const taskPayload = (config: Record<string, unknown>) => ({
    cast: [],
    storyboardType: 'ass',
    status: 'ready',
    storyboardConfig: config,
    lines: [],
  })

  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('waits for completion then refreshes the story bible', async () => {
    const store = useProjectStore()
    store.activeTaskId = 'task-1'
    store.activeStoryboardType = 'ass'
    store.activeStoryBible = bible([{ sceneIndex: 0, locationName: '街道', error: '模型超时' }])

    const refreshed = bible([])
    const taskUrls: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/segments/0/regenerate'))
        return json({ taskId: 'task-1', sceneIndex: 0, status: 'segment_retrying' })
      // 轮询与最终刷新都返回「无 outlineProgress」（后台已完成）
      if (url === '/api/tasks/task-1' || url.startsWith('/api/tasks/task-1?')) {
        taskUrls.push(url)
        return json(taskPayload({ storyBible: refreshed }))
      }
      return json({}, 404)
    })

    await store.retryOutlineSegment(0)
    expect(store.segmentRetrying[0]).toBe(false)
    expect(store.activeStoryBible).toEqual(refreshed)
    // P2 响应裁剪契约：脚本拉取固定带 history=0（只回当前选用资产）
    expect(taskUrls.every((url) => url === '/api/tasks/task-1?history=0')).toBe(true)
  })

  it('tolerates a 409 (already retrying) and still waits for completion', async () => {
    vi.useFakeTimers()
    try {
      const store = useProjectStore()
      store.activeTaskId = 'task-1'
      store.activeStoryboardType = 'ass'
      store.activeStoryBible = bible([{ sceneIndex: 0, locationName: '街道', error: '模型超时' }])

      let taskReads = 0
      vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
        const url = String(input)
        if (url.endsWith('/segments/0/regenerate'))
          return json({ detail: '该场景段正在重新生成中' }, 409)
        if (url === '/api/tasks/task-1' || url.startsWith('/api/tasks/task-1?')) {
          taskReads += 1
          // 第一次轮询：后台仍在跑；第二次：进度已清空（完成）
          if (taskReads === 1)
            return json(taskPayload({ outlineProgress: { phase: 'segment_retry', sceneIndex: 0 } }))
          return json(taskPayload({ storyBible: bible([]) }))
        }
        return json({}, 404)
      })

      const promise = store.retryOutlineSegment(0)
      await vi.runAllTimersAsync()
      await promise
      expect(store.segmentRetrying[0]).toBe(false)
      expect(taskReads).toBeGreaterThanOrEqual(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('resets the retrying flag and keeps the old bible when the background retry fails', async () => {
    const store = useProjectStore()
    store.activeTaskId = 'task-1'
    store.activeStoryboardType = 'ass'
    const original = bible([{ sceneIndex: 0, locationName: '街道', error: '模型超时' }])
    store.activeStoryBible = original

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/segments/0/regenerate'))
        return json({ taskId: 'task-1', sceneIndex: 0, status: 'segment_retrying' })
      if (url === '/api/tasks/task-1' || url.startsWith('/api/tasks/task-1?'))
        return json(
          taskPayload({
            outlineProgress: {
              phase: 'segment_retry_failed',
              sceneIndex: 0,
              error: 'LLM 持续超时',
            },
          }),
        )
      return json({}, 404)
    })

    // 失败经由 errorBus 上报，action 本身不向外抛
    await store.retryOutlineSegment(0)
    expect(store.segmentRetrying[0]).toBe(false)
    // storyBible 未被刷新（Pinia state 为 reactive 代理，用值比较）
    expect(store.activeStoryBible).toEqual(original)
  })
})

describe('digital human generation with template reference', () => {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(async () => {
    // 复位模块级模板单例，避免污染其它测试
    const { setTemplateAvatar } = await import('../../src/api/imageGen')
    setTemplateAvatar('')
  })

  it('sends the system template sheet as the first reference image', async () => {
    const { setTemplateAvatar } = await import('../../src/api/imageGen')
    setTemplateAvatar('https://tos.test/system/template.png')

    const store = useProjectStore()
    store.dhStyleIds = { 古风: 'style-1' }
    const calls: { url: string; body?: Record<string, unknown> }[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : undefined
      calls.push({ url, body })
      if (url === '/api/generations/images')
        return json({
          id: 'job-dh',
          status: 'queued',
          progress: 0,
          prompt: '参照第一张参考图的构图版式。角色描述：青衣少女。画面风格：古风。',
        })
      if (url === '/api/generations/status')
        return json([
          {
            id: 'job-dh',
            status: 'succeeded',
            progress: 100,
            result: {
              urls: ['https://tos.test/dh.png'],
              thumbnailUrls: ['https://tos.test/dh-t.png'],
            },
          },
        ])
      if (url === '/api/generations/job-dh')
        return json({
          id: 'job-dh',
          status: 'succeeded',
          progress: 100,
          result: {
            urls: ['https://tos.test/dh.png'],
            thumbnailUrls: ['https://tos.test/dh-t.png'],
          },
        })
      // ensureDhStyle 对新风格做 fire-and-forget 登记（POST /digital-human-styles）
      if (url === '/api/digital-human-styles') return json({ id: 'style-1', name: '古风' })
      if (url === '/api/digital-humans')
        return json({
          id: 'dh-new',
          name: '小月',
          style: '古风',
          avatar: 'https://tos.test/dh-t.png',
          description: '青衣少女',
          scope: 'private',
        })
      return json({}, 404)
    })

    const dh = await store.generateDigitalHuman({
      name: '小月',
      style: '古风',
      description: '青衣少女',
      referenceImage: 'https://tos.test/user-photo.png',
    })
    expect(dh.id).toBe('dh-new')

    const creation = calls.find((call) => call.url === '/api/generations/images')
    expect(creation, '未发起生图请求').toBeDefined()
    // 模板三视图在前（prompt 中的「第一张参考图」），用户参考图在后
    expect(creation!.body?.images).toEqual([
      'https://tos.test/system/template.png',
      'https://tos.test/user-photo.png',
    ])
    // 提示词由后端注册中心模板拼装：前端只传原始 portrait 参数，prompt 留空
    expect(creation!.body?.prompt).toBe('')
    expect(creation!.body?.portrait).toEqual({ description: '青衣少女', style: '古风' })
    // 最终生效的 prompt 来自后端响应，随数字人落库 avatar_prompt
    const dhCreation = calls.find((call) => call.url === '/api/digital-humans')
    expect(String(dhCreation!.body?.avatar_prompt)).toContain('参照第一张参考图')
    // 任务创建后留了恢复草稿，完成后又清理掉
    expect(localStorage.getItem('mv:pending-dh')).toBeNull()
  })

  it('omits the images field when neither template nor user reference exists', async () => {
    const store = useProjectStore()
    store.dhStyleIds = { 古风: 'style-1' }
    store.digitalHumans = []
    const calls: { url: string; body?: Record<string, unknown> }[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : undefined
      calls.push({ url, body })
      if (url === '/api/generations/images')
        return json({ id: 'job-dh', status: 'queued', progress: 0 })
      if (url === '/api/generations/status')
        return json([
          {
            id: 'job-dh',
            status: 'succeeded',
            progress: 100,
            result: { urls: ['https://tos.test/dh.png'] },
          },
        ])
      if (url === '/api/generations/job-dh')
        return json({
          id: 'job-dh',
          status: 'succeeded',
          progress: 100,
          result: { urls: ['https://tos.test/dh.png'] },
        })
      if (url === '/api/digital-human-styles') return json({ id: 'style-1', name: '古风' })
      if (url === '/api/digital-humans')
        return json({
          id: 'dh-new',
          name: '小月',
          style: '古风',
          avatar: 'https://tos.test/dh.png',
          description: '',
          scope: 'private',
        })
      return json({}, 404)
    })

    await store.generateDigitalHuman({ name: '小月', style: '古风', description: '青衣少女' })
    const creation = calls.find((call) => call.url === '/api/generations/images')
    expect(creation!.body).not.toHaveProperty('images')
  })
})

describe('digital human avatar regeneration with template reference', () => {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  const dhFixture = (overrides: Record<string, unknown>) =>
    ({
      id: 'dh-1',
      name: '小月',
      style: '古风',
      description: '青衣少女',
      avatar: 'https://tos.test/old.png',
      avatarPrompt: '',
      scope: 'private',
      readOnly: false,
      ...overrides,
    }) as unknown as DigitalHuman

  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(async () => {
    // 复位模块级模板单例，避免污染其它测试
    const { setTemplateAvatar } = await import('../../src/api/imageGen')
    setTemplateAvatar('')
  })

  it('sends the template sheet before the current avatar and persists private humans', async () => {
    const { setTemplateAvatar } = await import('../../src/api/imageGen')
    setTemplateAvatar('https://tos.test/system/template.png')

    const store = useProjectStore()
    store.digitalHumans = [dhFixture({})]
    const calls: { url: string; method?: string; body?: Record<string, unknown> }[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : undefined
      calls.push({ url, method: init?.method, body })
      if (url === '/api/generations/images')
        return json({ id: 'job-re', status: 'queued', progress: 0 })
      if (url === '/api/generations/status')
        return json([
          {
            id: 'job-re',
            status: 'succeeded',
            progress: 100,
            result: {
              urls: ['https://tos.test/new.png'],
              thumbnailUrls: ['https://tos.test/new-t.png'],
            },
          },
        ])
      if (url === '/api/generations/job-re')
        return json({
          id: 'job-re',
          status: 'succeeded',
          progress: 100,
          result: {
            urls: ['https://tos.test/new.png'],
            thumbnailUrls: ['https://tos.test/new-t.png'],
          },
        })
      if (url === '/api/digital-humans/dh-1') return json({})
      return json({}, 404)
    })

    await store.regenerateDigitalHumanAvatar('dh-1')

    const creation = calls.find((call) => call.url === '/api/generations/images')
    // 模板三视图在前（prompt 中的「第一张参考图」），当前头像在后
    expect(creation!.body?.images).toEqual([
      'https://tos.test/system/template.png',
      'https://tos.test/old.png',
    ])
    const patch = calls.find((call) => call.url === '/api/digital-humans/dh-1')
    expect(patch?.method).toBe('PATCH')
    expect(patch?.body?.avatar_url).toBe('https://tos.test/new.png')
    // 本地状态同步：头像用缩略图，originalAvatar 用原图
    expect(store.digitalHumans[0].avatar).toBe('https://tos.test/new-t.png')
    expect(store.digitalHumans[0].originalAvatar).toBe('https://tos.test/new.png')
  })

  it('updates a system (readOnly) human locally without persisting to the backend', async () => {
    const store = useProjectStore()
    store.digitalHumans = [
      dhFixture({
        id: 'dh-system-001',
        scope: 'system',
        readOnly: true,
        avatar: 'https://tos.test/sys.png',
      }),
    ]
    const calls: { url: string; method?: string }[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      calls.push({ url, method: init?.method })
      if (url === '/api/generations/images')
        return json({ id: 'job-re', status: 'queued', progress: 0 })
      if (url === '/api/generations/status')
        return json([
          {
            id: 'job-re',
            status: 'succeeded',
            progress: 100,
            result: { urls: ['https://tos.test/new.png'] },
          },
        ])
      if (url === '/api/generations/job-re')
        return json({
          id: 'job-re',
          status: 'succeeded',
          progress: 100,
          result: { urls: ['https://tos.test/new.png'] },
        })
      return json({}, 404)
    })

    await store.regenerateDigitalHumanAvatar('dh-system-001')

    // 无缩略图时头像回落到原图
    expect(store.digitalHumans[0].avatar).toBe('https://tos.test/new.png')
    // 系统人物只读：不回写后端
    expect(calls.some((call) => call.url.includes('/api/digital-humans'))).toBe(false)
  })
})

describe('outline loading lock scoped to its own task', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('does not lock the outline modal of another task while one task is generating', () => {
    const store = useProjectStore()
    // 任务 A 正在生成大纲（全局 outlineLoading=true），当前编辑区已切到任务 B
    store.activeTaskId = 'task-B'
    store.activeStoryBible = { shots: [] } as unknown as StoryBible
    store.outlineLoading = true
    store.outlineTaskId = 'task-A'
    store.outlineOpen = true

    expect(store.outlineLocked).toBe(false)
    store.closeOutline()
    expect(store.outlineOpen).toBe(false) // B 的弹窗可正常关闭
  })

  it('keeps the modal locked only while its own task is generating', () => {
    const store = useProjectStore()
    store.activeTaskId = 'task-A'
    store.outlineLoading = true
    store.outlineTaskId = 'task-A'
    store.outlineOpen = true

    expect(store.outlineLocked).toBe(true)
    store.closeOutline()
    expect(store.outlineOpen).toBe(true) // 自身生成中：维持原锁定行为

    store.outlineLoading = false
    store.outlineTaskId = null
    store.closeOutline()
    expect(store.outlineOpen).toBe(false) // 生成结束即可关闭
  })
})

describe('batch storyboard line generation', () => {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  const batchLine = (id: string, generationStatus: string, outlineStatus?: string) =>
    ({
      id,
      generationStatus,
      generationAttempt: 1,
      scenePrompt: '',
      shotPrompt: '',
      digitalHumanIds: [],
      shotOptions: outlineStatus ? { outlineStatus } : {},
      voice: { status: 'none' },
      scene: { status: 'none' },
      shot: { status: 'none', assets: [] },
    }) as unknown as ScriptLine

  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('collects pending/failed outline-ready lines and skips the rest', async () => {
    const store = useProjectStore()
    store.activeTaskId = 'task-1'
    store.lines = [
      batchLine('l-pending', 'pending'),
      batchLine('l-failed', 'failed', 'ready'),
      batchLine('l-running', 'running'),
      batchLine('l-done', 'succeeded'),
      batchLine('l-no-outline', 'pending', 'pending'),
    ]
    const requested: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      requested.push(url)
      return json({ scenePrompt: 's', shotPrompt: 'p', digitalHumanIds: [], generationAttempt: 2 })
    })

    await store.generateAllPendingStoryboardLines()

    expect([...requested].sort()).toEqual([
      '/api/tasks/task-1/storyboard-lines/l-failed/generate',
      '/api/tasks/task-1/storyboard-lines/l-pending/generate',
    ])
    expect(store.lines.find((line) => line.id === 'l-pending')?.generationStatus).toBe('succeeded')
    expect(store.lines.find((line) => line.id === 'l-failed')?.generationStatus).toBe('succeeded')
    expect(store.lines.find((line) => line.id === 'l-running')?.generationStatus).toBe('running')
  })

  it('reverts lines to pending and stops dispatching on the 429 concurrency cap', async () => {
    const store = useProjectStore()
    store.activeTaskId = 'task-1'
    store.lines = ['a', 'b', 'c', 'd', 'e'].map((id) => batchLine(`l-${id}`, 'pending'))
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
      json({ detail: '同时进行的提示词生成已达上限（100 条），请等待部分完成后再试' }, 429),
    )

    await store.generateAllPendingStoryboardLines()

    // 未实际生成的行全部还原为 pending，不误标 failed
    expect(store.lines.every((line) => line.generationStatus === 'pending')).toBe(true)
  })
})

describe('batch shot video generation', () => {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  const shotLine = (id: string, generationStatus: string, shotStatus: string) =>
    ({
      id,
      generationStatus,
      scenePrompt: 's',
      shotPrompt: 'p',
      digitalHumanIds: [],
      shotOptions: {},
      voice: { status: 'none' },
      scene: { status: 'none' },
      shot:
        shotStatus === 'done'
          ? {
              status: 'done',
              assets: [{ id: `${id}-a`, videoUrl: '/v.mp4', duration: 5 }],
              currentAssetId: `${id}-a`,
            }
          : { status: shotStatus, assets: [] },
    }) as unknown as ScriptLine

  const succeededJob = () =>
    json({
      id: 'job-poll',
      status: 'succeeded',
      progress: 100,
      result: { coverUrl: '/c.png', videoUrl: '/v.mp4', duration: 5 },
    })

  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('dispatches videos only for prompt-ready lines whose shot is not done', async () => {
    const store = useProjectStore()
    store.activeTaskId = 'task-1'
    store.lines = [
      shotLine('l-new', 'succeeded', 'none'),
      shotLine('l-failed', 'succeeded', 'failed'),
      shotLine('l-done', 'succeeded', 'done'),
      shotLine('l-draft', 'pending', 'none'),
    ]
    const posted: string[] = []
    let jobSeq = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      if (String(input) === '/api/generations/videos') {
        posted.push(String(JSON.parse(String(init?.body)).storyboard_line_id))
        jobSeq += 1
        return json({ id: `job-${jobSeq}`, status: 'queued', progress: 0 })
      }
      return succeededJob()
    })

    await store.generateAllShots()

    // l-done 已有视频、l-draft 提示词未就绪：均跳过
    expect(posted).toEqual(['l-new', 'l-failed'])
    expect(store.lines.find((line) => line.id === 'l-new')?.shot.status).toBe('done')
    expect(store.lines.find((line) => line.id === 'l-failed')?.shot.status).toBe('done')
    expect(store.lines.find((line) => line.id === 'l-draft')?.shot.status).toBe('none')
  })

  it('does not submit digital-human reference images for general MV shots', async () => {
    const store = useProjectStore()
    store.activeTaskId = 'task-general'
    store.activeStoryboardType = 'general'
    store.digitalHumans = [
      {
        id: 'dh-1',
        name: '人物一',
        avatar: '/media/human.png',
        source: 'system',
        scope: 'system',
      },
    ]
    const line = shotLine('general-line', 'succeeded', 'none')
    line.source = 'general'
    line.digitalHumanIds = ['dh-1']
    line.scene = {
      status: 'done',
      imageUrl: '/media/scene.png',
      originalImageUrl: '/media/scene-original.png',
    }
    store.lines = [line]
    let submittedImages: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      if (String(input) === '/api/generations/videos') {
        submittedImages = JSON.parse(String(init?.body)).image_urls
        return json({ id: 'general-video-job', status: 'queued', progress: 0 })
      }
      return succeededJob()
    })

    await store.generateShotFor(line.id)

    expect(submittedImages).toEqual(['/media/scene.png'])
  })

  it('runs up to two hundred video generations concurrently', async () => {
    const store = useProjectStore()
    store.activeTaskId = 'task-1'
    store.lines = Array.from({ length: 201 }, (_, index) =>
      shotLine(`l-${index + 1}`, 'succeeded', 'none'),
    )
    let active = 0
    let peak = 0
    const releases: Array<() => void> = []
    vi.spyOn(store, 'generateShotFor').mockImplementation(async () => {
      active += 1
      peak = Math.max(peak, active)
      await new Promise<void>((resolve) => releases.push(resolve))
      active -= 1
    })

    const run = store.generateAllShots()
    await vi.waitFor(() => expect(active).toBe(200))
    expect(peak).toBe(200)
    expect(releases).toHaveLength(200)

    releases.shift()?.()
    await vi.waitFor(() => expect(releases).toHaveLength(200))
    expect(peak).toBe(200)
    releases.splice(0).forEach((release) => release())
    await run
    expect(store.batchShooting).toBe(false)
  })

  it('limits H3 batch dispatch to its registered model concurrency', async () => {
    const previous = [...VIDEO_MODEL_OPTIONS]
    VIDEO_MODEL_OPTIONS.splice(0, VIDEO_MODEL_OPTIONS.length, {
      value: 'minimax-h3-runninghub',
      label: 'MiniMax H3',
      capabilities: { executionConcurrency: 2 },
    })
    try {
      const store = useProjectStore()
      store.activeTaskId = 'task-1'
      store.lines = Array.from({ length: 3 }, (_, index) => ({
        ...shotLine(`h3-${index + 1}`, 'succeeded', 'none'),
        shotOptions: {
          resolution: '720p' as const,
          duration: 5,
          ratio: '16:9' as const,
          imageModel: 'gpt-image-2',
          videoModel: 'minimax-h3-runninghub',
        },
      }))
      let active = 0
      let peak = 0
      const releases: Array<() => void> = []
      vi.spyOn(store, 'generateShotFor').mockImplementation(async () => {
        active += 1
        peak = Math.max(peak, active)
        await new Promise<void>((resolve) => releases.push(resolve))
        active -= 1
      })

      const run = store.generateAllShots()
      await vi.waitFor(() => expect(active).toBe(2))
      expect(peak).toBe(2)
      releases.shift()?.()
      await vi.waitFor(() => expect(releases).toHaveLength(2))
      releases.splice(0).forEach((release) => release())
      await run
    } finally {
      VIDEO_MODEL_OPTIONS.splice(0, VIDEO_MODEL_OPTIONS.length, ...previous)
    }
  })

  it('keeps dispatching after a line hits the 429 concurrency cap', async () => {
    const store = useProjectStore()
    store.activeTaskId = 'task-1'
    store.lines = [shotLine('l-a', 'succeeded', 'none'), shotLine('l-b', 'succeeded', 'none')]
    const posted: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      if (String(input) === '/api/generations/videos') {
        const lineId = String(JSON.parse(String(init?.body)).storyboard_line_id)
        posted.push(lineId)
        if (lineId === 'l-a') return json({ detail: '单账号视频生成上限' }, 429)
        return json({ id: 'job-1', status: 'queued', progress: 0 })
      }
      return succeededJob()
    })

    await store.generateAllShots()

    // 429 行标失败入错误状态，不中断后续行派发
    expect(posted).toEqual(['l-a', 'l-b'])
    expect(store.lines.find((line) => line.id === 'l-a')?.shot.status).toBe('failed')
    expect(store.lines.find((line) => line.id === 'l-b')?.shot.status).toBe('done')
  })

  it('clears the persisted batch flag after the batch finishes naturally', async () => {
    const auth = useAuthStore()
    auth.user = {
      id: 'u-1',
      username: 'u-1',
      displayName: 'U',
      role: 'user',
      mustChangePassword: false,
    }
    const store = useProjectStore()
    store.activeTaskId = 'task-1'
    store.lines = [shotLine('l-a', 'succeeded', 'none')]
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      if (String(input) === '/api/generations/videos')
        return json({ id: 'job-1', status: 'queued', progress: 0 })
      return succeededJob()
    })

    await store.generateAllShots()

    // 自然跑完：标记清除，刷新后不会误续跑
    expect(localStorage.getItem('mv_batch_shot_u-1_task-1')).toBeNull()
    expect(store.batchShooting).toBe(false)
  })

  it('keeps the persisted batch flag when switching tasks interrupts the batch', async () => {
    const auth = useAuthStore()
    auth.user = {
      id: 'u-1',
      username: 'u-1',
      displayName: 'U',
      role: 'user',
      mustChangePassword: false,
    }
    const store = useProjectStore()
    store.activeTaskId = 'task-1'
    store.lines = [shotLine('l-a', 'succeeded', 'none'), shotLine('l-b', 'succeeded', 'none')]
    const posted: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      if (String(input) === '/api/generations/videos') {
        const lineId = String(JSON.parse(String(init?.body)).storyboard_line_id)
        posted.push(lineId)
        // 模拟派发第一行期间用户切走子任务：批量循环应在第二行前中断
        if (lineId === 'l-a') store.activeTaskId = 'task-2'
        return json({ id: 'job-1', status: 'queued', progress: 0 })
      }
      return succeededJob()
    })

    await store.generateAllShots()

    expect(posted).toEqual(['l-a'])
    // 中断不清标记：切回/刷新后由 _loadTask 检测标记续跑
    expect(localStorage.getItem('mv_batch_shot_u-1_task-1')).toBe('1')
    expect(store.batchShooting).toBe(false)
  })

  it('resume waits for a restored generating line to settle before dispatching the next', async () => {
    vi.useFakeTimers()
    try {
      const auth = useAuthStore()
      auth.user = {
        id: 'u-1',
        username: 'u-1',
        displayName: 'U',
        role: 'user',
        mustChangePassword: false,
      }
      const store = useProjectStore()
      store.activeTaskId = 'task-1'
      const generating = shotLine('l-busy', 'succeeded', 'generating')
      const idle = shotLine('l-idle', 'succeeded', 'none')
      store.lines = [generating, idle]
      // 模拟刷新前已点批量：标记仍在，由 _loadTask 触发续跑
      localStorage.setItem('mv_batch_shot_u-1_task-1', '1')
      const posted: string[] = []
      vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
        if (String(input) === '/api/generations/videos') {
          posted.push(String(JSON.parse(String(init?.body)).storyboard_line_id))
          return json({ id: 'job-1', status: 'queued', progress: 0 })
        }
        return succeededJob()
      })

      const run = store.generateAllShots()
      await vi.advanceTimersByTimeAsync(2000)
      // 恢复中的行占用一个 worker，空闲 worker 立即派发下一行。
      expect(posted).toEqual(['l-idle'])
      expect(store.batchShooting).toBe(true)
      // 等待态 watcher 把在途行更新为完成后，整个批次才结束。
      generating.shot.status = 'done'
      await vi.advanceTimersByTimeAsync(30000)
      await run

      expect(posted).toEqual(['l-idle'])
      expect(localStorage.getItem('mv_batch_shot_u-1_task-1')).toBeNull()
      expect(store.batchShooting).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('workspace owner guard on account switch', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('clears the previous account workspace when loadSongProjects detects an account switch', async () => {
    const auth = useAuthStore()
    const store = useProjectStore()
    // 老账号遗留的工作区现场（例如登出未走清理的异常路径）
    store.ownerUserId = 'u-old'
    store.songProjects = [{ id: 'song-old', name: '老账号项目', tasks: [] } as SongProject]
    store.lines = [{ id: 'l1' } as ScriptLine]
    store.activeSongId = 'song-old'
    store.activeTaskId = 'task-old'
    auth.user = {
      id: 'u-new',
      username: 'u-new',
      displayName: 'New',
      role: 'user',
      mustChangePassword: false,
    }
    // 新账号没有任何项目/角色/分类
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      async () =>
        new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )

    await store.loadSongProjects()

    expect(store.ownerUserId).toBe('u-new')
    expect(store.songProjects).toEqual([])
    expect(store.lines).toEqual([])
    expect(store.activeSongId).toBe('')
    expect(store.activeTaskId).toBeNull()
  })
})

describe('material export progress display', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('keeps the persisted progress while the backend is stalled', () => {
    const store = useProjectStore()
    store.activeTaskId = 'task-1'
    store._upsertMaterialExport({
      id: 'exp-1',
      taskId: 'task-1',
      jobId: 'job-exp-1',
      status: 'running',
      progress: 40,
      stage: '正在下载素材',
      totalAssets: 2,
      processedAssets: 1,
      totalBytes: 20,
      processedBytes: 10,
      createdAt: new Date(Date.now() - 30_000).toISOString(),
      // 即使 25 秒未收到后端推送，也不虚构进度，避免下一次真实快照到达时数字倒退。
      updatedAt: new Date(Date.now() - 25_000).toISOString(),
    })
    expect(store.synthesis.progress).toBe(40)
  })

  it('does not move backwards when an older or lower progress snapshot arrives', () => {
    const store = useProjectStore()
    store.activeTaskId = 'task-1'
    const snapshot = (progress: number, updatedAt: string): MaterialExport => ({
      id: 'exp-monotonic',
      taskId: 'task-1',
      jobId: 'job-exp-monotonic',
      status: 'running',
      progress,
      stage: '正在下载素材',
      totalAssets: 19,
      processedAssets: 8,
      totalBytes: 74_000_000,
      processedBytes: 32_000_000,
      createdAt: '2026-08-17T09:13:34Z',
      updatedAt,
    })

    store._upsertMaterialExport(snapshot(58, '2026-08-17T09:14:10Z'))
    store._upsertMaterialExport(snapshot(42, '2026-08-17T09:14:09Z'))
    expect(store.synthesis.progress).toBe(58)

    store._upsertMaterialExport(snapshot(45, '2026-08-17T09:14:11Z'))
    expect(store.synthesis.progress).toBe(58)
  })

  it('does not creep a finished export', () => {
    const store = useProjectStore()
    store.activeTaskId = 'task-1'
    store._upsertMaterialExport({
      id: 'exp-2',
      taskId: 'task-1',
      jobId: 'job-exp-2',
      status: 'ready',
      progress: 100,
      stage: '导出完成',
      totalAssets: 2,
      processedAssets: 2,
      totalBytes: 20,
      processedBytes: 20,
      createdAt: new Date(Date.now() - 60_000).toISOString(),
      updatedAt: new Date(Date.now() - 60_000).toISOString(),
      archiveUrl: 'https://tos.test/export.zip',
    })
    expect(store.synthesis.progress).toBe(100)
    expect(store.synthesis.videoUrl).toBe('https://tos.test/export.zip')
  })
})

describe('unnamed project auto-creation before generation', () => {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('auto-creates an unnamed project when generating without any project', async () => {
    const store = useProjectStore()
    expect(store.activeSongId).toBeFalsy() // 尚无选中项目
    const calls: { url: string; body?: Record<string, unknown> }[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      calls.push({
        url,
        body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined,
      })
      if (url === '/api/projects')
        return json({ id: 'song-new', name: '未命名项目', tasks: [] }, 201)
      throw new Error(`unexpected request: ${url}`)
    })

    await store.ensureSongProjectForGeneration()

    expect(calls).toEqual([{ url: '/api/projects', body: { name: '未命名项目' } }])
    expect(store.activeSongId).toBe('song-new')
  })

  it('reuses the active project instead of creating a new one when one exists', async () => {
    const store = useProjectStore()
    store.activeSongId = 'song-existing'
    const spy = vi.spyOn(globalThis, 'fetch')

    await store.ensureSongProjectForGeneration()

    expect(spy).not.toHaveBeenCalled()
    expect(store.activeSongId).toBe('song-existing')
  })
})

describe('outline phase unified for general storyboards', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('exposes the outline phase for general tasks, not only ASS', () => {
    const store = useProjectStore()
    store.activeStoryboardType = 'general'
    store.activeTaskStatus = 'parsed'
    expect(store.outlinePhase).toBe('pending')

    store.activeTaskStatus = 'outlining'
    expect(store.outlinePhase).toBe('outlining')

    store.activeTaskStatus = 'outline_failed'
    expect(store.outlinePhase).toBe('failed')

    store.activeTaskStatus = 'generating'
    expect(store.outlinePhase).toBe('none')
  })

  it('still returns none for unsupported storyboard types', () => {
    const store = useProjectStore()
    store.activeStoryboardType = null
    store.activeTaskStatus = 'outlining'
    expect(store.outlinePhase).toBe('none')
  })

  it('counts per-line generation progress for general lines (outline-ready only)', () => {
    const store = useProjectStore()
    store.lines = [
      { id: 'l1', generationStatus: 'succeeded', shotOptions: {} },
      { id: 'l2', generationStatus: 'failed', shotOptions: {} },
      { id: 'l3', generationStatus: 'running', shotOptions: {} },
      { id: 'l4', generationStatus: 'pending', shotOptions: { outlineStatus: 'pending' } },
    ] as unknown as ScriptLine[]
    // 大纲未就绪的 l4 不参与统计
    expect(store.storyboardProgress).toEqual({ total: 3, completed: 1, failed: 1, active: true })
  })

  it('treats leftover pending lines as inactive so the batch entry stays available', () => {
    const store = useProjectStore()
    store.lines = [
      { id: 'l1', generationStatus: 'succeeded', shotOptions: {} },
      { id: 'l2', generationStatus: 'pending', shotOptions: {} },
    ] as unknown as ScriptLine[]
    // 队列已终止（无 running）：残留 pending 行不锁死批量生成入口（429/切任务场景的手动恢复）
    expect(store.storyboardProgress.active).toBe(false)
  })
})

describe('playback clock driven by the registered video element', () => {
  const vidLine = (id: string, duration: number) =>
    ({
      id,
      generationStatus: 'succeeded',
      digitalHumanIds: [],
      shotOptions: {},
      voice: { status: 'none' },
      scene: { status: 'none' },
      shot: {
        status: 'done',
        assets: [{ id: `${id}-a`, videoUrl: 'https://tos.test/v.mp4', duration, isCurrent: true }],
        currentAssetId: `${id}-a`,
      },
    }) as unknown as ScriptLine

  let rafQueue: FrameRequestCallback[]

  beforeEach(() => {
    setActivePinia(createPinia())
    rafQueue = []
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      rafQueue.push(cb)
      return rafQueue.length
    })
    vi.stubGlobal('cancelAnimationFrame', () => {})
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const tickOnce = (now: number) => rafQueue.shift()?.(now)

  it('writes back the store clock from the video element while playing', () => {
    const store = useProjectStore()
    store.lines = [vidLine('l1', 5), vidLine('l2', 5)]
    const video = { currentTime: 2, paused: false, readyState: 2 } as HTMLVideoElement
    store.registerVideoEl(video)
    store.play()
    expect(store.isPlaying).toBe(true)

    tickOnce(performance.now())
    expect(store.currentTime).toBeCloseTo(2, 1) // clip.start(0) + video.currentTime(2)

    video.currentTime = 4.8
    tickOnce(performance.now() + 16)
    expect(store.currentTime).toBeCloseTo(4.8, 1)
    store.pause()
    store.registerVideoEl(null)
  })

  it('crosses the clip boundary on the video clock and stops at range end', () => {
    const store = useProjectStore()
    store.lines = [vidLine('l1', 5), vidLine('l2', 5)]
    const video = { currentTime: 4.9, paused: false, readyState: 2 } as HTMLVideoElement
    store.registerVideoEl(video)
    store.play()

    tickOnce(performance.now())
    expect(store.currentTime).toBeCloseTo(4.9, 1)
    // 视频播过片段末尾：下一帧换算 t=5.2，currentClip 切换到 l2
    video.currentTime = 5.2
    tickOnce(performance.now() + 16)
    expect(store.currentTime).toBeCloseTo(5.2, 1)
    // l2(start=5) 上视频时钟换算 5+5.2=10.2，越过全程末尾：停播并钳到 totalDuration
    tickOnce(performance.now() + 32)
    expect(store.isPlaying).toBe(false)
    expect(store.currentTime).toBe(10)
    store.registerVideoEl(null)
  })

  it('ignores the video clock while scrubbing so the dragged position sticks', () => {
    const store = useProjectStore()
    store.lines = [vidLine('l1', 5), vidLine('l2', 5)]
    const video = { currentTime: 2, paused: false, readyState: 2 } as HTMLVideoElement
    store.registerVideoEl(video)
    store.play()

    tickOnce(performance.now())
    expect(store.currentTime).toBeCloseTo(2, 1)

    // 拖动到第二个片段：scrubbing 期间不回写，位置不被视频弹回
    store.scrubbing = true
    store.seek(7)
    tickOnce(performance.now() + 32)
    expect(store.currentTime).toBeGreaterThan(6.9)
    expect(store.currentTime).toBeLessThan(7.5)

    // 松手后恢复视频时钟回写（当前片段 l2，start=5）
    store.scrubbing = false
    video.currentTime = 2.1
    tickOnce(performance.now() + 48)
    expect(store.currentTime).toBeCloseTo(7.1, 1)
    store.pause()
    store.registerVideoEl(null)
  })
})
