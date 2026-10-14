import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ShotGenerationOptionsPopover from '../../src/components/ShotGenerationOptionsPopover.vue'
import {
  DEFAULT_IMAGE_MODEL,
  IMAGE_MODEL_OPTIONS,
  VIDEO_MODEL_OPTIONS,
} from '../../src/generationModels'
import type { ShotGenOptions } from '../../src/types'

const options: ShotGenOptions = {
  resolution: '480p',
  duration: 5,
  ratio: '16:9',
  imageModel: DEFAULT_IMAGE_MODEL,
  videoModel: 'doubao-seedance-2.0',
}

describe('ShotGenerationOptionsPopover', () => {
  afterEach(() => {
    IMAGE_MODEL_OPTIONS.splice(0, IMAGE_MODEL_OPTIONS.length, {
      value: DEFAULT_IMAGE_MODEL,
      label: 'Nano Banana 2.1',
    })
    VIDEO_MODEL_OPTIONS.splice(0, VIDEO_MODEL_OPTIONS.length, {
      value: 'doubao-seedance-2.0',
      label: 'SD2.0',
    })
  })
  it('moves a retired model to the first available project model when opened', async () => {
    VIDEO_MODEL_OPTIONS.splice(
      0,
      VIDEO_MODEL_OPTIONS.length,
      { value: 'doubao-seedance-2.0', label: 'SD2.0' },
      { value: 'veo-3.1', label: 'Veo 3.1' },
    )
    const wrapper = mount(ShotGenerationOptionsPopover, {
      props: { modelValue: { ...options, videoModel: 'veo-3.1' }, mode: 'shot' },
    })
    await wrapper.get('[aria-label="调整生成参数"]').trigger('click')

    expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      videoModel: 'doubao-seedance-2.0',
    })
    wrapper.unmount()
  })
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

    expect(wrapper.get('[aria-label="调整生成参数"]').text()).toContain('16:9 · 1K')
    expect(wrapper.get('[aria-label="调整生成参数"]').text()).toContain('Nano Banana 2.1')
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

  it('shows the unified image model and image-only resolution choices', async () => {
    const wrapper = mount(ShotGenerationOptionsPopover, {
      props: {
        modelValue: { ...options, imageModel: DEFAULT_IMAGE_MODEL },
        mode: 'scene',
      },
    })

    await wrapper.get('[aria-label="调整生成参数"]').trigger('click')
    const select = document.querySelector('[aria-label="图片模型"]') as HTMLSelectElement
    expect(Array.from(select.options).map((option) => [option.value, option.text])).toEqual([
      [DEFAULT_IMAGE_MODEL, 'Nano Banana 2.1'],
    ])
    expect(document.body.textContent).toContain('1K')
    expect(document.body.textContent).toContain('2K')
    expect(document.body.textContent).toContain('4K')
    wrapper.unmount()
  })

  it('restores shot defaults and closes when confirmed', async () => {
    const wrapper = mount(ShotGenerationOptionsPopover, {
      props: {
        modelValue: {
          ...options,
          ratio: '9:16',
          resolution: '1080p',
          duration: 12,
          videoModel: 'minimax-h3-runninghub',
          generateAudio: true,
          watermark: true,
        },
        mode: 'shot',
      },
    })

    await wrapper.get('[aria-label="调整生成参数"]').trigger('click')
    const restore = Array.from(document.querySelectorAll('button')).find(
      (button) => button.textContent?.trim() === '恢复默认',
    ) as HTMLButtonElement
    restore.click()
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      ratio: '16:9',
      resolution: '480p',
      duration: 5,
      videoModel: 'doubao-seedance-2.0',
      generateAudio: false,
      watermark: false,
    })

    const confirm = Array.from(document.querySelectorAll('button')).find(
      (button) => button.textContent?.trim() === '确定',
    ) as HTMLButtonElement
    confirm.click()
    await wrapper.vm.$nextTick()
    expect(document.querySelector('.options-overlay')).toBeNull()
    wrapper.unmount()
  })

  it('shows the four supported H3 modes without a tail-frame-only option', async () => {
    const wrapper = mount(ShotGenerationOptionsPopover, {
      props: {
        modelValue: { ...options, videoModel: 'minimax-h3-runninghub' },
        mode: 'shot',
      },
    })
    await wrapper.get('[aria-label="调整生成参数"]').trigger('click')
    const select = document.querySelector('[aria-label="H3 生成模式"]') as HTMLSelectElement
    expect(select.value).toBe('auto')
    expect(Array.from(select.options).map((option) => option.value)).toEqual([
      'auto',
      'text',
      'first_frame',
      'first_last',
      'reference',
    ])
    expect(document.body.textContent).not.toContain('尾帧 L2VA')
    wrapper.unmount()
  })
})
