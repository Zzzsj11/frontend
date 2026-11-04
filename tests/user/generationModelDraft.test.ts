import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import GenerationModelSelect from '../../src/components/GenerationModelSelect.vue'
import { useGenerationPreferences } from '../../src/stores/generationPreferences'

beforeEach(() => setActivePinia(createPinia()))

it('keeps preview selection local until the parent confirms and preserves the global preference on cancel', async () => {
  const preferences = useGenerationPreferences()
  preferences.selections.video = { model: 'current', channel: 'original' }
  preferences.channels.target = [
    {
      channel: 'channel-b',
      name: 'Channel B',
      priority: 1,
      available: true,
      unavailable_reason: null,
    },
  ]
  vi.spyOn(preferences, 'loadChannels').mockResolvedValue()
  const save = vi.spyOn(preferences, 'save')
  const wrapper = mount(GenerationModelSelect, {
    props: {
      modelValue: 'current',
      channel: 'original',
      modality: 'video',
      persistPreference: false,
      groups: [
        {
          label: 'Models',
          items: [
            { value: 'current', label: 'Current' },
            { value: 'target', label: 'Target' },
          ],
        },
      ],
    },
    global: {
      stubs: {
        PopoverPortal: { template: '<div><slot /></div>' },
        PopoverContent: { template: '<div><slot /></div>' },
      },
    },
  })
  await wrapper.get('[aria-label="Target渠道"]').trigger('click')
  await flushPromises()
  const channel = wrapper.findAll('button').find((button) => button.text() === 'Channel B')!
  await channel.trigger('click')
  expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['target'])
  expect(wrapper.emitted('update:channel')?.at(-1)).toEqual(['channel-b'])
  expect(save).not.toHaveBeenCalled()
  wrapper.unmount()
  expect(preferences.selections.video).toEqual({ model: 'current', channel: 'original' })
})
