import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import ExportActions from '../../src/components/ExportActions.vue'
import { useProjectStore } from '../../src/stores/project'
import type { ProjectAudio, ScriptLine } from '../../src/types'

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
