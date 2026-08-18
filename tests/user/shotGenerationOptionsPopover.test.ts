import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ShotGenerationOptionsPopover from '../../src/components/ShotGenerationOptionsPopover.vue'
import type { ShotGenOptions } from '../../src/types'

const options: ShotGenOptions = {
  resolution: '480p',
  duration: 5,
  ratio: '16:9',
  imageModel: 'gpt-image-2',
  videoModel: 'doubao-seedance-2.0',
}

describe('ShotGenerationOptionsPopover', () => {
  it('summarizes video options and emits changed segmented choices', async () => {
    const wrapper = mount(ShotGenerationOptionsPopover, {
      props: { modelValue: options, mode: 'shot' },
    })

    expect(wrapper.get('[aria-label="调整生成参数"]').text()).toContain('16:9 · 480P · 5s')
    expect(wrapper.get('[aria-label="调整生成参数"]').text()).toContain('SD2.0')
    await wrapper.get('[aria-label="调整生成参数"]').trigger('click')
    expect(wrapper.get('[aria-label="调整生成参数"]').attributes('aria-expanded')).toBe('true')
    expect(document.querySelector('[aria-label="视频模型"]')).not.toBeNull()
    expect(document.querySelector('[aria-label="图片模型"]')).toBeNull()
    expect(document.body.textContent).toContain('生成背景音')
    expect(document.body.textContent).toContain('添加水印')

    ;(document.querySelector('button[aria-pressed="false"]') as HTMLButtonElement).click()
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()

    const overlay = document.querySelector('.options-overlay') as HTMLElement
    expect(overlay).not.toBeNull()
    overlay.click()
    await wrapper.vm.$nextTick()
    expect(document.querySelector('.options-overlay')).toBeNull()
    wrapper.unmount()
  })

  it('hides video-only duration and model controls in scene mode', async () => {
    const wrapper = mount(ShotGenerationOptionsPopover, {
      props: { modelValue: options, mode: 'scene' },
    })

    expect(wrapper.get('[aria-label="调整生成参数"]').text()).toContain('16:9 · 480P')
    expect(wrapper.get('[aria-label="调整生成参数"]').text()).toContain('Img2')
    expect(wrapper.get('[aria-label="调整生成参数"]').text()).not.toContain('5s')
    await wrapper.get('[aria-label="调整生成参数"]').trigger('click')

    expect(document.body.textContent).not.toContain('选择时长')
    expect(document.body.textContent).not.toContain('视频模型')
    expect(document.body.textContent).toContain('图片模型')
    expect(document.querySelector('[aria-label="图片模型"]')).not.toBeNull()
    expect(document.body.textContent).not.toContain('生成背景音')
    expect(document.body.textContent).not.toContain('添加水印')
    wrapper.unmount()
  })
})
