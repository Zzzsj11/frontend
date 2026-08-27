import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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

  it('hides planned character chips for general MV lines', () => {
    const store = useProjectStore()
    store.digitalHumans = [
      {
        id: 'dh-general',
        name: '仅用于大纲的人物',
        avatar: '/human.png',
        source: 'system',
        scope: 'system',
      },
    ]
    const line = {
      ...videoLine,
      id: 'line-general',
      source: 'general',
      shotType: 'character',
      digitalHumanIds: ['dh-general'],
    } as ScriptLineType
    store.lines = [line]

    const wrapper = mount(ScriptLine, { props: { line, index: 0 } })

    expect(wrapper.find('.dh-chips').exists()).toBe(false)
    expect(wrapper.text()).toContain('人物镜')
    expect(wrapper.text()).not.toContain('仅用于大纲的人物')
  })

  it('opens the complete generation error and copies the diagnostic package', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    const line = {
      ...videoLine,
      id: 'line-failed',
      generationStatus: 'failed',
      generationErrorSummary: '系统并发写入冲突，可重新生成',
      generationError: 'DeadlockDetectedError: deadlock detected\nDETAIL: complete details',
      generationJobId: 'job-deadlock-1',
      generationFailedAt: '2026-08-27T01:37:13Z',
    } as ScriptLineType
    const wrapper = mount(ScriptLine, {
      attachTo: document.body,
      props: { line, index: 26 },
    })

    await wrapper.find('.error-detail-trigger').trigger('click')
    expect(document.body.textContent).toContain('生成失败详情')
    expect(document.body.textContent).toContain('第 27 条')
    expect(document.body.textContent).toContain('job-deadlock-1')
    expect(document.body.textContent).toContain('DETAIL: complete details')

    const copyButton = [...document.body.querySelectorAll('button')].find(
      (button) => button.textContent?.trim() === '复制完整信息',
    ) as HTMLButtonElement
    copyButton.click()
    await Promise.resolve()
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('工单ID：job-deadlock-1'))
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('DeadlockDetectedError'))
    wrapper.unmount()
  })
})
