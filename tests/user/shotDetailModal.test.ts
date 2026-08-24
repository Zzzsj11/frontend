import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ShotDetailModal from '../../src/components/ShotDetailModal.vue'
import { useProjectStore } from '../../src/stores/project'
import type { ScriptLine } from '../../src/types'

describe('ShotDetailModal general MV character controls', () => {
  beforeEach(() => setActivePinia(createPinia()))

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('hides character preview and cast editing for general lines', async () => {
    const store = useProjectStore()
    const line = {
      id: 'general-character-line',
      source: 'general',
      shotType: 'character',
      plannedDuration: 5,
      lyrics: '',
      scenePrompt: '城市夜景',
      shotPrompt: '年轻女性走过街道',
      digitalHumanIds: ['dh-planned'],
      voice: { status: 'none' },
      scene: { status: 'none' },
      shot: { status: 'none', assets: [] },
      generationStatus: 'succeeded',
    } as ScriptLine
    store.lines = [line]
    store.editingLineId = line.id
    store.editingTab = 'cast'

    const wrapper = mount(ShotDetailModal, { attachTo: document.body })
    await wrapper.vm.$nextTick()

    expect(document.body.querySelectorAll('.preview-cards .pcard')).toHaveLength(2)
    expect(document.body.querySelector('.pcard-avatars')).toBeNull()
    expect(document.body.querySelector('.cast-row')).toBeNull()
    expect(document.body.textContent).toContain('选择视频或场景，调整对应内容')
    expect(document.body.textContent).not.toContain('管理阵容')
  })

  it('shows server-based elapsed seconds while video is generating', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-24T12:00:12Z'))
    const store = useProjectStore()
    const line = {
      id: 'generating-line',
      source: 'general',
      shotType: 'character',
      plannedDuration: 5,
      lyrics: '',
      scenePrompt: '城市夜景',
      shotPrompt: '人物行走',
      digitalHumanIds: [],
      voice: { status: 'none' },
      scene: { status: 'none' },
      shot: {
        status: 'generating',
        assets: [],
        generationSubmittedAt: '2026-08-24T12:00:00Z',
      },
      generationStatus: 'succeeded',
    } as ScriptLine
    store.lines = [line]
    store.editingLineId = line.id
    store.editingTab = 'shot'

    const wrapper = mount(ShotDetailModal, { attachTo: document.body })
    await wrapper.vm.$nextTick()
    expect(document.body.textContent).toContain('视频已提交生成 12 秒')

    await vi.advanceTimersByTimeAsync(2000)
    expect(document.body.textContent).toContain('视频已提交生成 14 秒')
    wrapper.unmount()
    vi.useRealTimers()
  })
})
