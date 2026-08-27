import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import TimelinePanel from '../../src/components/TimelinePanel.vue'
import { useProjectStore } from '../../src/stores/project'
import type { ScriptLine } from '../../src/types'

/** 带视频资产的分镜行：timelineClips 由资产时长推导 */
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

describe('TimelinePanel clip selection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('moves the playhead to the clip start when a segment card is clicked', async () => {
    const store = useProjectStore()
    store.lines = [vidLine('l1', 5), vidLine('l2', 5)]
    store.currentTime = 0

    const wrapper = mount(TimelinePanel)
    const clips = wrapper.findAll('.clip')
    expect(clips).toHaveLength(2)

    await clips[1].trigger('click')
    expect(store.selectedLineId).toBe('l2')
    // 游标对齐到第二个片段的起点（5s）
    expect(store.currentTime).toBe(5)

    await clips[0].trigger('click')
    expect(store.selectedLineId).toBe('l1')
    expect(store.currentTime).toBe(0)
  })

  it('aligns the playhead even when single-shot mode is off', async () => {
    const store = useProjectStore()
    store.lines = [vidLine('l1', 4), vidLine('l2', 6)]
    store.playMode.single = false
    store.currentTime = 0

    const wrapper = mount(TimelinePanel)
    await wrapper.findAll('.clip')[1].trigger('click')
    expect(store.currentTime).toBe(4)
  })

  it('shows one uncut project audio track and can hide it', async () => {
    const store = useProjectStore()
    store.lines = [vidLine('l1', 5), vidLine('l2', 5)]
    store.projectAudio = {
      id: 'audio-1',
      projectId: 'project-1',
      filename: 'song.mp3',
      url: 'https://tos.test/song.mp3',
      mimeType: 'audio/mpeg',
      fileSize: 1024,
      duration: 30,
    }
    store.audioTrackVisible = true
    store.audioOffsetSeconds = 2.5

    const wrapper = mount(TimelinePanel)
    expect(wrapper.findAll('.audio-clip')).toHaveLength(1)
    expect(wrapper.get('.audio-clip').text()).toContain('song.mp3')
    expect(wrapper.get('.audio-clip').text()).toContain('+2.5s')

    await wrapper.findAll('.audio-toggle').at(-1)!.trigger('click')
    expect(store.audioTrackVisible).toBe(false)
    expect(wrapper.find('.audio-clip').exists()).toBe(false)
  })
})
