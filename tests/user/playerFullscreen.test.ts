import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import PlayerPanel from '../../src/components/PlayerPanel.vue'
import { useProjectStore } from '../../src/stores/project'
import type { ScriptLine } from '../../src/types'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
afterEach(() => {
  vi.restoreAllMocks()
  Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: null })
})
it('uses the full timeline in fullscreen without resetting the current position and restores single mode', async () => {
  vi.useFakeTimers()
  const store = useProjectStore()
  store.lines = ['one', 'two'].map((id) => ({
    id,
    digitalHumanIds: [],
    voice: { status: 'none', duration: 5 },
    scene: { status: 'none' },
    shot: { status: 'none', assets: [] },
  })) as ScriptLine[]
  store.selectedLineId = 'one'
  store.currentTime = 3
  store.playMode.single = true
  const wrapper = mount(PlayerPanel, { attachTo: document.body })
  try {
    Object.defineProperty(document, 'fullscreenElement', {
      configurable: true,
      value: wrapper.get('.preview').element,
    })
    document.dispatchEvent(new Event('fullscreenchange'))
    await wrapper.vm.$nextTick()
    expect(store.playMode.single).toBe(false)
    expect(store.currentTime).toBe(3)
    expect(wrapper.get('.fs-time').text()).toBe('00:03 / 00:10')
    expect(store.playRange.end).toBe(10)
    const zone = wrapper.get('.fs-control-zone')
    await zone.trigger('pointerenter')
    vi.advanceTimersByTime(4000)
    await wrapper.vm.$nextTick()
    expect(wrapper.get('.fs-controls').isVisible()).toBe(true)
    await zone.trigger('pointerleave')
    vi.advanceTimersByTime(2000)
    await wrapper.vm.$nextTick()
    expect(wrapper.get('.fs-controls').isVisible()).toBe(true)
    vi.advanceTimersByTime(1000)
    await wrapper.vm.$nextTick()
    expect(wrapper.get('.fs-controls').isVisible()).toBe(false)
    await zone.trigger('pointerenter')
    expect(wrapper.get('.fs-controls').isVisible()).toBe(true)
    store.scrubbing = true
    await wrapper.vm.$nextTick()
    await zone.trigger('pointerleave')
    vi.advanceTimersByTime(4000)
    await wrapper.vm.$nextTick()
    expect(wrapper.get('.fs-controls').isVisible()).toBe(true)
    store.scrubbing = false
    await wrapper.vm.$nextTick()
    vi.advanceTimersByTime(3000)
    await wrapper.vm.$nextTick()
    expect(wrapper.get('.fs-controls').isVisible()).toBe(false)
    Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: null })
    document.dispatchEvent(new Event('fullscreenchange'))
    await wrapper.vm.$nextTick()
    expect(store.playMode.single).toBe(true)
    expect(wrapper.find('.fs-controls').exists()).toBe(false)
  } finally {
    wrapper.unmount()
    vi.useRealTimers()
  }
})
