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
})
