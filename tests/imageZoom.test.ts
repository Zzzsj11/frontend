import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import ImagePreviewOverlay from '../src/components/ImagePreviewOverlay.vue'
import ImageZoom from '../src/components/ImageZoom.vue'
import { closeImagePreview } from '../src/composables/useImagePreview'

/** P3b 单例化后：ImageZoom 只是触发按钮，遮罩由全局唯一的 ImagePreviewOverlay 渲染 */
const mountPair = (props: { src?: string; alt?: string }) => {
  const overlay = mount(ImagePreviewOverlay, { attachTo: document.body })
  const trigger = mount(ImageZoom, { props, attachTo: document.body })
  return { overlay, trigger }
}

describe('ImageZoom（全局单例预览）', () => {
  afterEach(() => {
    closeImagePreview()
  })

  it('never shows a hover preview and opens the full image only via the trigger button', async () => {
    const { overlay, trigger } = mountPair({
      src: 'https://example.com/original.jpg',
      alt: '角色原图',
    })

    expect(document.querySelector('[role="dialog"]')).toBeNull()
    // hover 不再直接弹出大图：组件不提供任何 hover 预览浮层
    expect(document.querySelector('.image-hover-preview')).toBeNull()

    const button = trigger.get('button[aria-label="查看大图"]')
    button.element.parentElement?.dispatchEvent(new MouseEvent('mouseenter'))
    await nextTick()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    expect(document.querySelector('.image-hover-preview')).toBeNull()

    await button.trigger('click')
    await nextTick()

    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog).not.toBeNull()
    expect(dialog?.querySelector('img')?.getAttribute('src')).toBe(
      'https://example.com/original.jpg',
    )

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    trigger.unmount()
    overlay.unmount()
  })

  it('does not render the trigger without a src', () => {
    const { overlay, trigger } = mountPair({ src: undefined })
    expect(trigger.find('button[aria-label="查看大图"]').exists()).toBe(false)
    trigger.unmount()
    overlay.unmount()
  })

  it('shares one overlay across triggers: opening from another trigger swaps the image', async () => {
    const overlay = mount(ImagePreviewOverlay, { attachTo: document.body })
    const first = mount(ImageZoom, {
      props: { src: 'https://example.com/a.jpg', alt: '图 A' },
      attachTo: document.body,
    })
    const second = mount(ImageZoom, {
      props: { src: 'https://example.com/b.jpg', alt: '图 B' },
      attachTo: document.body,
    })

    await first.get('button').trigger('click')
    await nextTick()
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(1)
    expect(document.querySelector('[role="dialog"] img')?.getAttribute('src')).toBe(
      'https://example.com/a.jpg',
    )

    await second.get('button').trigger('click')
    await nextTick()
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(1)
    expect(document.querySelector('[role="dialog"] img')?.getAttribute('src')).toBe(
      'https://example.com/b.jpg',
    )

    first.unmount()
    second.unmount()
    overlay.unmount()
  })
})
