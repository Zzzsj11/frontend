import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import BaseModal from '../../src/components/base/BaseModal.vue'
import ImagePreviewOverlay from '../../src/components/ImagePreviewOverlay.vue'
import {
  closeImagePreview,
  openImageGallery,
  useImagePreview,
} from '../../src/composables/useImagePreview'

enableAutoUnmount(afterEach)
afterEach(async () => {
  closeImagePreview()
  await nextTick()
})
const click = async (label: string) => {
  const button = Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(
    (item) => item.textContent?.trim() === label || item.getAttribute('aria-label') === label,
  )!
  button.click()
  await nextTick()
}

describe('shared image preview interactions', () => {
  it('closes only the upper layer and preserves the editor draft and scroll lock', async () => {
    const editor = mount(BaseModal, {
      props: { open: true, title: '编辑' },
      slots: { default: '<textarea>未保存的场景描述</textarea>' },
      attachTo: document.body,
    })
    mount(ImagePreviewOverlay, { attachTo: document.body })
    openImageGallery([
      { src: '/scene-original.png', thumbnail: '/scene-thumb.png', alt: '场景图' },
      { src: '/portrait-original.png', thumbnail: '/portrait-thumb.png', alt: '人物参考图' },
    ])
    await nextTick()
    const preview = document.querySelector('[aria-label="图片大图预览"]')!
    preview.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    await nextTick()
    expect(useImagePreview().state.src).toBe('/portrait-original.png')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }))
    await nextTick()
    expect(editor.emitted('close')).toBeUndefined()
    expect(document.querySelector('textarea')?.value).toBe('未保存的场景描述')
    expect(document.querySelector('[aria-label="图片大图预览"]')).toBeNull()
    expect(document.body.style.overflow).toBe('hidden')
  })
  it('shows a retry action on load failure and resets the image for another attempt', async () => {
    mount(ImagePreviewOverlay, { attachTo: document.body })
    openImageGallery([{ src: '/original.png', alt: '原图' }])
    await nextTick()
    document.querySelector('.image-viewport img')!.dispatchEvent(new Event('error'))
    await nextTick()
    expect(document.body.textContent).toContain('原图加载失败')
    await click('重新加载')
    expect(document.querySelector('.image-viewport img')?.getAttribute('src')).toBe('/original.png')
    expect(document.body.textContent).not.toContain('原图加载失败')
    await flushPromises()
  })
})
