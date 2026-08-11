import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useProjectStore } from '../src/stores/project'
import type { MaterialExport, ScriptLine } from '../src/types'

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
      // 重新拉取任务脚本，行数据带上了新资产
      {
        cast: [],
        storyboardType: '',
        status: '',
        lines: [
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
