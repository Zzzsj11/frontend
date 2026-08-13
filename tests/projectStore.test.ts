import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../src/stores/auth'
import { useProjectStore } from '../src/stores/project'
import type {
  DigitalHuman,
  MaterialExport,
  ScriptLine,
  SongProject,
  StoryBible,
} from '../src/types'

describe('project user journey state', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('plays the full MV by default instead of limiting playback to one video', () => {
    const store = useProjectStore()
    expect(store.playMode.single).toBe(false)
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
      updatedAt: '2026-08-10T00:00:00Z',
    })
    store._upsertMaterialExport(item('a', 'task-a', 35))
    store._upsertMaterialExport(item('b', 'task-b', 70))
    store.activeTaskId = 'task-a'
    expect(store.synthesis.progress).toBe(35)
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
    const { setTemplateAvatar } = await import('../src/api/imageGen')
    setTemplateAvatar('')
  })

  it('sends the system template sheet as the first reference image', async () => {
    const { setTemplateAvatar } = await import('../src/api/imageGen')
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
        return json({ id: 'job-dh', status: 'queued', progress: 0 })
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
    expect(String(creation!.body?.prompt)).toContain('参照第一张参考图')
    expect(String(creation!.body?.prompt)).toContain('青衣少女')
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
    const { setTemplateAvatar } = await import('../src/api/imageGen')
    setTemplateAvatar('')
  })

  it('sends the template sheet before the current avatar and persists private humans', async () => {
    const { setTemplateAvatar } = await import('../src/api/imageGen')
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
