import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ExportActions from '../../src/components/ExportActions.vue'
import { useProjectStore } from '../../src/stores/project'
import type { ProjectAudio, ScriptLine, MaterialExport } from '../../src/types'

describe('final video export eligibility', () => {
  beforeEach(() => setActivePinia(createPinia()))
  it('only offers merging for ASS projects with audio and requires all clips', async () => {
    const store = useProjectStore()
    const wrapper = mount(ExportActions)
    expect(wrapper.text()).not.toContain('合并并导出')
    store.activeStoryboardType = 'ass'
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).not.toContain('合并并导出')
    store.projectAudio = { id: 'audio' } as ProjectAudio
    store.lines = [{ id: 'line', shot: { assets: [] } }] as unknown as ScriptLine[]
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('还有 1 段视频未完成')
    expect(wrapper.find('button').attributes('disabled')).toBeDefined()
    store.lines[0].shot.assets = [
      { id: 'clip', videoUrl: 'https://test.tos/clip.mp4' },
    ] as ScriptLine['shot']['assets']
    store.lines[0].shot.currentAssetId = 'clip'
    await wrapper.vm.$nextTick()
    expect(wrapper.find('button').attributes('disabled')).toBeUndefined()
    store.activeStoryboardType = 'general'
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).not.toContain('合并并导出')
  })
})

describe('export progress dismissal', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
  })
  it('allows hiding without cancelling and reopens progress; a new job shows automatically', async () => {
    const store = useProjectStore()
    store.activeTaskId = 'notice-task'
    const item = {
      id: 'notice-1',
      kind: 'materials',
      status: 'running',
      progress: 42,
      stage: '下载中',
    } as MaterialExport
    store.exportsByTaskId['notice-task'] = [item]
    const wrapper = mount(ExportActions)
    await wrapper.get('button[aria-label="隐藏导出素材进度"]').trigger('click')
    expect(wrapper.find('progress').exists()).toBe(false)
    expect(store.exportsByTaskId['notice-task'][0].status).toBe('running')
    const show = wrapper.findAll('button').find((button) => button.text() === '查看进度')!
    await show.trigger('click')
    expect(wrapper.find('progress').exists()).toBe(true)
    await wrapper.get('button[aria-label="隐藏导出素材进度"]').trigger('click')
    wrapper.unmount()
    const restored = mount(ExportActions)
    expect(restored.find('progress').exists()).toBe(false)
    store.exportsByTaskId['notice-task'] = [{ ...item, id: 'notice-2' }]
    await restored.vm.$nextTick()
    expect(restored.find('progress').exists()).toBe(true)
    restored.unmount()
  })
  it('automatically hides completion after five seconds while keeping the download link', async () => {
    vi.useFakeTimers()
    const store = useProjectStore()
    store.activeTaskId = 'complete-task'
    store.exportsByTaskId['complete-task'] = [
      {
        id: 'complete-1',
        kind: 'materials',
        status: 'ready',
        progress: 100,
        stage: '导出完成',
        archiveUrl: '/materials.zip',
      } as MaterialExport,
    ]
    const wrapper = mount(ExportActions)
    try {
      expect(wrapper.text()).toContain('5 秒后自动隐藏')
      vi.advanceTimersByTime(5000)
      await wrapper.vm.$nextTick()
      expect(wrapper.find('progress').exists()).toBe(false)
      expect(wrapper.get('a').attributes('href')).toBe('/materials.zip')
      const show = wrapper.findAll('button').find((button) => button.text() === '查看进度')!
      await show.trigger('click')
      expect(wrapper.find('progress').exists()).toBe(true)
      vi.advanceTimersByTime(5000)
      await wrapper.vm.$nextTick()
      expect(wrapper.find('progress').exists()).toBe(false)
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })
})
