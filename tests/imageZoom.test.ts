import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import ImageZoom from '../src/components/ImageZoom.vue'

describe('ImageZoom', () => {
  it('never shows a hover preview and opens the full image only via the trigger button', async () => {
    const wrapper = mount(ImageZoom, {
      props: { src: 'https://example.com/original.jpg', alt: '角色原图' },
      attachTo: document.body,
    })

    expect(document.querySelector('[role="dialog"]')).toBeNull()
    // hover 不再直接弹出大图：组件不提供任何 hover 预览浮层
    expect(document.querySelector('.image-hover-preview')).toBeNull()

    const trigger = wrapper.get('button[aria-label="查看大图"]')
    trigger.element.parentElement?.dispatchEvent(new MouseEvent('mouseenter'))
    await nextTick()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    expect(document.querySelector('.image-hover-preview')).toBeNull()

    await trigger.trigger('click')
    await nextTick()

    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog).not.toBeNull()
    expect(dialog?.querySelector('img')?.getAttribute('src')).toBe(
      'https://example.com/original.jpg',
    )

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    wrapper.unmount()
  })

  it('does not render the trigger without a src', () => {
    const wrapper = mount(ImageZoom, { props: { src: undefined } })
    expect(wrapper.find('button[aria-label="查看大图"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
