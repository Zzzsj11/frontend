import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import ScriptLine from '../../src/components/ScriptLine.vue'
import { useProjectStore } from '../../src/stores/project'
import type { ScriptLine as ScriptLineType } from '../../src/types'

const videoLine = {
  id: 'line-video',
  source: 'manual',
  generationStatus: 'succeeded',
  lyrics: '测试提示词',
  digitalHumanIds: [],
  voice: { status: 'none' },
  scene: { status: 'done', imageUrl: '/scene.jpg' },
  shot: {
    status: 'done',
    assets: [{ id: 'asset-video', videoUrl: '/video.mp4', duration: 5, isCurrent: true }],
    currentAssetId: 'asset-video',
  },
} as ScriptLineType

describe('ScriptLine thumbnail playback', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('selects and plays the timeline clip without opening the editor', async () => {
    const store = useProjectStore()
    store.lines = [videoLine]
    const wrapper = mount(ScriptLine, { props: { line: videoLine, index: 0 } })

    await wrapper.find('.shot-thumb').trigger('click')

    expect(store.selectedLineId).toBe(videoLine.id)
    expect(store.currentTime).toBe(0)
    expect(store.isPlaying).toBe(true)
    expect(store.editingLineId).toBeNull()
    expect(wrapper.find('.image-zoom-trigger').exists()).toBe(false)
    store.pause()
  })
})
