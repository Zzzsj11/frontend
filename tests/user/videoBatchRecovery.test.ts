import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { useProjectStore } from '../../src/stores/project'
import * as api from '../../src/api/domain'
import { GenerationObservationTimeout, cancelTaskWatchers } from '../../src/utils/generationPoller'
import type { ScriptLine } from '../../src/types'

const line = (id: string, done = false) =>
  ({
    id,
    shotPrompt: 'park',
    generationStatus: 'succeeded',
    digitalHumanIds: [],
    scene: { status: 'none' },
    voice: { status: 'none' },
    shot: {
      status: done ? 'done' : 'none',
      assets: done ? [{ id: 'asset-' + id, videoUrl: '/ready.mp4', duration: 5 }] : [],
    },
  }) as unknown as ScriptLine
const deferred = () => {
  let resolve!: () => void
  const promise = new Promise<void>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

describe('independent video result recovery', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => {
    cancelTaskWatchers('task-video')
    vi.restoreAllMocks()
  })
  it('shows a completed line while its sibling is still queued', async () => {
    const store = useProjectStore()
    store.activeTaskId = 'task-video'
    store.lines = [line('one'), line('two')]
    const one = deferred(),
      two = deferred()
    vi.spyOn(api, 'submitVideoGenerationsBatch').mockResolvedValue({
      count: 2,
      jobs: [{ id: 'job-one' }, { id: 'job-two' }],
    })
    vi.spyOn(api, 'waitGenerationJob').mockImplementation((id) =>
      id === 'job-one' ? one.promise : two.promise,
    )
    vi.spyOn(api, 'fetchStoryboardLine').mockImplementation(async (_task, id) => line(id, true))
    const pending = store._generateRandomShotsBatch('task-video', store.lines)
    await flushPromises()
    one.resolve()
    await flushPromises()
    expect(store.lines[0].shot.status).toBe('done')
    expect(store.lines[1].shot.status).toBe('generating')
    two.resolve()
    await pending
    expect(store.lines[1].shot.status).toBe('done')
  })
  it('does not let an old task completion overwrite a different open task', async () => {
    const store = useProjectStore()
    store.activeTaskId = 'task-video'
    store.lines = [line('one')]
    const ready = deferred()
    vi.spyOn(api, 'waitGenerationJob').mockReturnValue(ready.promise)
    vi.spyOn(api, 'fetchStoryboardLine').mockResolvedValue(line('one', true))
    const pending = store._watchGenerationJob('task-video', 'job-switch', 'one', 'video')
    store.taskScripts['task-video'] = { cast: [], lines: store.lines }
    store.activeTaskId = 'other'
    store.lines = [line('other')]
    ready.resolve()
    await pending
    expect(store.lines[0].id).toBe('other')
    expect(store.taskScripts['task-video'].lines[0].shot.status).toBe('done')
  })
  it('keeps an observation timeout in reconciliation instead of claiming generation failed', async () => {
    const store = useProjectStore()
    store.activeTaskId = 'task-video'
    store.lines = [line('one', true)]
    vi.spyOn(api, 'waitGenerationJob').mockRejectedValue(
      new GenerationObservationTimeout('waiting'),
    )
    await store._watchGenerationJob('task-video', 'job-timeout', 'one', 'video')
    expect(store.lines[0].shot.generationPhase).toBe('reconciling')
    expect(store.lines[0].shot.status).not.toBe('failed')
    expect(store.lines[0].shot.assets).toHaveLength(1)
  })
})

describe('reopening an interrupted video observer', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => {
    cancelTaskWatchers('task-video')
    vi.restoreAllMocks()
  })
  it('starts a new observer when the previous task watcher has already been aborted', async () => {
    const store = useProjectStore()
    store.activeTaskId = 'task-video'
    store.lines = [line('one')]
    const old = deferred(),
      fresh = deferred()
    const wait = vi
      .spyOn(api, 'waitGenerationJob')
      .mockReturnValueOnce(old.promise)
      .mockReturnValueOnce(fresh.promise)
    vi.spyOn(api, 'fetchStoryboardLine').mockResolvedValue(line('one', true))
    const first = store._watchGenerationJob('task-video', 'job-reopen', 'one', 'video')
    cancelTaskWatchers('task-video')
    const second = store._watchGenerationJob('task-video', 'job-reopen', 'one', 'video')
    expect(wait).toHaveBeenCalledTimes(2)
    old.resolve()
    await first
    fresh.resolve()
    await second
    expect(store.lines[0].shot.status).toBe('done')
  })
})
