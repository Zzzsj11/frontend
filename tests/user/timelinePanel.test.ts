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
})
