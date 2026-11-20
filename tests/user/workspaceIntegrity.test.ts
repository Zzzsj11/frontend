import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as creative from '../../src/api/creative'
import * as models from '../../src/generationModels'
import CreativeVideoModal from '../../src/components/CreativeVideoModal.vue'
import * as api from '../../src/api/domain'
import { resetAuthState } from '../../src/api/client'
import { ApiError } from '../../src/errorBus'
import { useProjectStore } from '../../src/stores/project'
import { useAuthStore } from '../../src/stores/auth'
import SongSidebar from '../../src/components/SongSidebar.vue'
import ShotDetailModal from '../../src/components/ShotDetailModal.vue'
import type { ScriptLine, SongProject } from '../../src/types'

function line(id: string): ScriptLine {
  return {
    id,
    manual: true,
    lyrics: '',
    scenePrompt: '街景',
    shotPrompt: '镜头',
    digitalHumanIds: [],
    voice: { status: 'none' },
    scene: { status: 'none' },
    shot: { status: 'none', assets: [] },
    generationStatus: 'succeeded',
  }
}

describe('workspace integrity', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => {
    vi.restoreAllMocks()
    resetAuthState()
  })

  it('late project and character lists from the previous user cannot populate the new workspace', async () => {
    const store = useProjectStore()
    const owner = useAuthStore()
    const user = {
      id: 'former',
      username: 'former',
      displayName: '',
      role: 'user' as const,
      mustChangePassword: false,
    }
    owner.user = user
    let finish!: (projects: SongProject[]) => void
    vi.spyOn(api, 'fetchSongProjects')
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve
          }),
      )
      .mockResolvedValue([{ id: 'new-project', name: 'new', tasks: [] }])
    vi.spyOn(api, 'fetchDigitalHumans').mockResolvedValue([])
    vi.spyOn(api, 'fetchDigitalHumanStyles')
      .mockResolvedValueOnce([{ id: 'old', name: 'old', readOnly: false, scope: 'private' }])
      .mockResolvedValue([])
    const before = store.loadSongProjects()
    resetAuthState()
    owner.user = { ...user, id: 'current' }
    await store.loadSongProjects()
    finish([{ id: 'private-old-project', name: 'former', tasks: [] }])
    await before
    expect(store.ownerUserId).toBe('current')
    expect(store.songProjects.map((song) => song.id)).toEqual(['new-project'])
    expect(store.dhStyles).toEqual([])
  })

  it('does not release the current task switch when a previous session finishes its selection', async () => {
    const store = useProjectStore()
    const resolvers: Array<() => void> = []
    vi.spyOn(store, '_loadTask').mockImplementation(
      () => new Promise((resolve) => resolvers.push(resolve)),
    )
    const former = store.selectSongTask('song-a', 'old')
    resetAuthState()
    store.resetWorkspace()
    const current = store.selectSongTask('song-b', 'new')
    resolvers[0]()
    await former
    expect(store.songSwitching).toBe(true)
    resolvers[1]()
    await current
    expect(store.songSwitching).toBe(false)
  })

  it('does not attach a late creative line to another project or start its video there', async () => {
    const store = useProjectStore()
    store.activeTaskId = 'former-task'
    let finish!: (saved: ScriptLine) => void
    vi.spyOn(api, 'createStoryboardLine').mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    const pending = store.addCreativeLine({
      originalPrompt: '原提示词',
      optimizedPrompt: '分镜',
      referenceMedia: [],
      optimizerProvider: 'gemini',
      options: { duration: 5, ratio: '16:9', resolution: '720p' },
    })
    store.activeTaskId = 'new-task'
    store.lines = [line('current-line')]
    finish(line('former-line'))
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    expect(store.lines.map((line) => line.id)).toEqual(['current-line'])
  })

  it('explicit batch quota rejection releases all generate controls without querying nonexistent jobs', async () => {
    const store = useProjectStore()
    store.activeTaskId = 'task'
    store.lines = [line('first'), line('second')]
    vi.spyOn(api, 'submitVideoGenerationsBatch').mockRejectedValue(new ApiError('余额不足', 402))
    const observe = vi.spyOn(store, 'resumeActiveGenerations').mockResolvedValue()
    await store._generateRandomShotsBatch('task', store.lines)
    expect(observe).not.toHaveBeenCalled()
    for (const item of store.lines) {
      expect(item.shot.status).toBe('failed')
      expect(item.shot.generationPhase).toBeUndefined()
      expect(item.shot.error).toBe('余额不足')
    }
  })

  it('clicking the original task recovers after its first detail load fails', async () => {
    const store = useProjectStore()
    const load = vi
      .spyOn(api, 'fetchSongScript')
      .mockRejectedValueOnce(new ApiError('unavailable', 503))
      .mockResolvedValue({
        cast: [],
        lines: [line('saved')],
        storyboardType: 'manual',
        status: 'ready',
      })
    vi.spyOn(store, 'restoreMaterialExports').mockResolvedValue()
    vi.spyOn(store, 'resumeActiveGenerations').mockResolvedValue()
    await expect(store.selectSongTask('song', 'task')).rejects.toThrow('unavailable')
    expect(store.activeTaskId).toBeNull()
    await store.selectSongTask('song', 'task')
    expect(load).toHaveBeenCalledTimes(2)
    expect(store.selectedLineId).toBe('saved')
  })

  it('submits all unique prompt IDs in batches of up to 100', async () => {
    const store = useProjectStore()
    store.activeTaskId = 'task'
    const ids = Array.from({ length: 205 }, (_, n) => String(n))
    const send = vi
      .spyOn(api, 'generateStoryboardLinesBatch')
      .mockResolvedValue({ taskId: 'task', jobs: [], count: 0 })
    vi.spyOn(api, 'fetchSongScript').mockResolvedValue({
      cast: [],
      lines: [],
      storyboardType: 'ass',
      status: 'ready',
    })
    await store._generateStoryboardBatch('task', [...ids, '204'])
    const groups = send.mock.calls.map(([, batch]) => batch)
    expect(groups.map((batch) => batch.length)).toEqual([100, 100, 5])
    expect(groups.flat()).toEqual(ids)
  })

  it('preserves the active project, task and line when their deletion is rejected', async () => {
    const store = useProjectStore()
    store.songProjects = [
      { id: 'song', name: '歌曲', tasks: [{ id: 'task', title: '分镜', updatedAt: '' }] },
    ]
    store.activeSongId = 'song'
    store.activeTaskId = 'task'
    store.lines = [line('keep')]
    for (const fn of ['deleteSongProject', 'deleteSongTask', 'deleteStoryboardLine'] as const)
      vi.spyOn(api, fn).mockRejectedValue(new Error('offline'))
    await expect(store.deleteSongProject('song')).rejects.toThrow('offline')
    await expect(store.deleteSongTask('song', 'task')).rejects.toThrow('offline')
    await expect(store.removeLine('keep')).rejects.toThrow('offline')
    expect(store.songProjects[0].tasks[0].id).toBe(store.activeTaskId)
    expect(store.lines[0].id).toBe('keep')
  })

  it('uses ASS transition times and the offset audio endpoint regardless of video lengths', () => {
    const store = useProjectStore()
    store.activeStoryboardType = 'ass'
    store.projectAudio = {
      id: 'audio',
      projectId: 'song',
      filename: 'demo.mp3',
      url: '/demo.mp3',
      mimeType: 'audio/mpeg',
      fileSize: 10,
      duration: 15,
    }
    store.audioOffsetSeconds = -2
    store.lines = [0, 6, 10, 17].map((start, index) => ({
      ...line(String(index)),
      start,
      voice: { status: 'done', duration: 3 },
    }))
    expect(store.timelineClips.map((clip) => [clip.start, clip.duration])).toEqual([
      [0, 6],
      [6, 4],
      [10, 3],
    ])
    expect(store.totalDuration).toBe(13)
  })

  it('drops projects and tasks at the chosen nonzero destination', async () => {
    const store = useProjectStore()
    vi.spyOn(store, 'loadSongProjects').mockResolvedValue()
    store.songProjects = ['a', 'b', 'c'].map((id) => ({
      id,
      name: id,
      tasks: id === 'a' ? ['1', '2', '3'].map((id) => ({ id, title: id, updatedAt: '' })) : [],
    }))
    const songs = vi.spyOn(store, 'reorderSongProjects').mockResolvedValue()
    const tasks = vi.spyOn(store, 'reorderSongTasks').mockResolvedValue()
    const wrapper = mount(SongSidebar)
    const dataTransfer = { setData: vi.fn(), getData: () => '1' }
    for (const selector of ['.song-folder', '.task-item']) {
      const rows = wrapper.findAll(selector)
      await rows[0].trigger('dragstart', { dataTransfer })
      await rows[2].trigger('dragover', { dataTransfer })
      await rows[2].trigger('drop', { dataTransfer })
    }
    expect(songs).toHaveBeenCalledWith(['b', 'c', 'a'])
    expect(tasks).toHaveBeenCalledWith('a', ['2', '3', '1'])
    wrapper.unmount()
  })

  it('blocks repeat optimization while the original queued job is being observed', async () => {
    const store = useProjectStore()
    store.creativeOpen = true
    vi.spyOn(models, 'loadGenerationModels').mockResolvedValue()
    vi.spyOn(creative, 'fetchCreativeStatus').mockResolvedValue({
      providers: {
        gemini: { configured: true, model: 'fixture' },
        minimax: { configured: false, model: '' },
      },
      limits: { images: 9, videos: 3, audios: 3, audioSeconds: 15, videoSeconds: 15 },
      durationRange: [4, 15],
      ratios: ['16:9'],
    })
    const submit = vi.spyOn(creative, 'optimizeCreativePrompt').mockResolvedValue({
      id: 'waiting',
      provider: 'gemini',
      model: 'fixture',
      status: 'queued',
      inputPrompt: '一个镜头',
      outputPrompt: '',
      duration: 15,
      ratio: '16:9',
      media: [],
      error: '',
    })
    const wrapper = mount(CreativeVideoModal, {
      attachTo: document.body,
      global: { stubs: { TextModelSelect: true, VideoModelSelect: true, BaseSelect: true } },
    })
    try {
      await flushPromises()
      const prompt = document.querySelector<HTMLTextAreaElement>('.creative-body textarea')!
      prompt.value = '一个镜头'
      prompt.dispatchEvent(new Event('input'))
      await flushPromises()
      const button = document.querySelector<HTMLButtonElement>('.creative-body .primary')!
      expect(button.disabled).toBe(false)
      button.click()
      await flushPromises()
      expect(button.disabled).toBe(true)
      button.click()
      expect(submit).toHaveBeenCalledOnce()
      expect(submit.mock.calls[0][0].request_id).toEqual(expect.any(String))
    } finally {
      wrapper.unmount()
    }
  })

  it('retains a creative draft after a failed single PATCH and closes only on a successful retry', async () => {
    const store = useProjectStore()
    store.lines = [
      {
        ...line('edited'),
        source: 'creative',
        originalPrompt: '原提示词',
        optimizedPrompt: '镜头',
      },
    ]
    store.editingLineId = 'edited'
    const patch = vi
      .spyOn(api, 'updateStoryboardLine')
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue({ generationStatus: 'succeeded' })
    const wrapper = mount(ShotDetailModal, { attachTo: document.body })
    await flushPromises()
    const save =
      document.querySelector<HTMLButtonElement>('.modal-footer .btn-primary') ??
      [...document.querySelectorAll<HTMLButtonElement>('button')].find(
        (button) => button.textContent?.trim() === '保存',
      )
    expect(save).toBeDefined()
    save!.click()
    await flushPromises()
    expect(store.editingLineId).toBe('edited')
    expect(patch).toHaveBeenCalledTimes(1)
    expect(patch.mock.calls[0][1]).toMatchObject({
      original_prompt: '原提示词',
      optimized_prompt: '镜头',
      shot_prompt: '镜头',
      scene_prompt: '街景',
      lyrics: '',
    })
    save!.click()
    await flushPromises()
    expect(store.editingLineId).toBeNull()
    expect(patch).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
})
