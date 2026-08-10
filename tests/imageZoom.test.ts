import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import ImageZoom from '../src/components/ImageZoom.vue'

describe('ImageZoom', () => {
  it('only opens the original image after the zoom button is clicked', async () => {
    const wrapper = mount(ImageZoom, {
      props: { src: 'https://example.com/original.jpg', alt: '角色原图' },
      attachTo: document.body,
    })

    expect(document.querySelector('[role="dialog"]')).toBeNull()
    await wrapper.get('button[aria-label="查看大图"]').trigger('click')
    await nextTick()

    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog).not.toBeNull()
    expect(dialog?.querySelector('img')?.getAttribute('src')).toBe('https://example.com/original.jpg')

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    wrapper.unmount()
  })
})
