import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ShotGenerationOptionsPopover from '../../src/components/ShotGenerationOptionsPopover.vue'
import VideoModelSelect from '../../src/components/VideoModelSelect.vue'
import {
  DEFAULT_IMAGE_MODEL,
  DEFAULT_VIDEO_MODEL,
  IMAGE_MODEL_OPTIONS,
  VIDEO_MODEL_OPTIONS,
} from '../../src/generationModels'
import type { ShotGenOptions } from '../../src/types'

const options: ShotGenOptions = {
  resolution: '480p',
  duration: 5,
  ratio: '16:9',
  imageModel: DEFAULT_IMAGE_MODEL,
  videoModel: 'doubao-seedance-2.0-all-in-one',
}

describe('ShotGenerationOptionsPopover', () => {
  it('blocks incompatible references without losing the original mode or frames', async () => {
    VIDEO_MODEL_OPTIONS.push({
      value: 'minimax-h3-all-in-one',
      label: 'H3',
      capabilities: { h3Modes: ['auto', 'text', 'first_frame', 'first_last', 'reference'] },
    })
    VIDEO_MODEL_OPTIONS.push({
      value: 'gemini-omni-1.1-flash-preview-all-in-one',
      label: 'Gemini Omni',
      capabilities: {
        referenceModes: ['auto', 'text', 'first_frame', 'reference'],
        referenceVideo: { max: 0 },
        referenceAudio: { max: 0 },
        resolutions: ['720p'],
        durationOptions: [10],
      },
    })
    const original: ShotGenOptions = {
      ...options,
      videoModel: 'minimax-h3-all-in-one',
      h3Mode: 'first_last',
      h3FirstFrameUrl: 'https://tos.test/first.png',
      h3LastFrameUrl: 'https://tos.test/last.png',
    }
    const wrapper = mount(ShotGenerationOptionsPopover, {
      props: { modelValue: original, mode: 'shot' },
    })
    await wrapper.get('[aria-label="调整生成参数"]').trigger('click')
    wrapper
      .findComponent(VideoModelSelect)
      .vm.$emit('update:modelValue', 'gemini-omni-1.1-flash-preview-all-in-one')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(document.querySelector('[role="alert"]')?.textContent).toContain('原配置已保留')
    expect(document.querySelector('[aria-label="H3 生成模式"]')).not.toBeNull()
    expect(original.h3LastFrameUrl).toBe('https://tos.test/last.png')

    await wrapper.setProps({
      modelValue: {
        ...original,
        h3Mode: 'reference',
        referenceVideoUrls: ['https://tos.test/motion.mp4'],
      },
    })
    wrapper
      .findComponent(VideoModelSelect)
      .vm.$emit('update:modelValue', 'gemini-omni-1.1-flash-preview-all-in-one')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()

    await wrapper.setProps({
      modelValue: { ...options, videoModel: original.videoModel, h3Mode: 'first_last' },
    })
    wrapper
      .findComponent(VideoModelSelect)
      .vm.$emit('update:modelValue', 'gemini-omni-1.1-flash-preview-all-in-one')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      videoModel: 'gemini-omni-1.1-flash-preview-all-in-one',
      h3Mode: 'auto',
      resolution: '720p',
      duration: 10,
    })
    expect(document.querySelector('[role="alert"]')).toBeNull()
    wrapper.unmount()
  })

  it('keeps first-frame full HD when only multi-reference mode has a lower limit', async () => {
    VIDEO_MODEL_OPTIONS.push({
      value: 'grok-video-1.5-all-in-one',
      label: 'Grok Video 1.5',
      capabilities: {
        referenceModes: ['auto', 'text', 'first_frame', 'reference'],
        resolutions: ['480p', '720p', '1080p'],
        referenceResolutions: ['480p', '720p'],
      },
    })
    const wrapper = mount(ShotGenerationOptionsPopover, {
      props: {
        modelValue: { ...options, resolution: '1080p', h3Mode: 'first_frame' },
        mode: 'shot',
      },
    })
    await wrapper.get('[aria-label="调整生成参数"]').trigger('click')
    wrapper
      .findComponent(VideoModelSelect)
      .vm.$emit('update:modelValue', 'grok-video-1.5-all-in-one')
    expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      h3Mode: 'first_frame',
      resolution: '1080p',
    })
    wrapper.unmount()
  })
  afterEach(() => {
    IMAGE_MODEL_OPTIONS.splice(0, IMAGE_MODEL_OPTIONS.length, {
      value: DEFAULT_IMAGE_MODEL,
      label: 'Nano Banana 2.1',
    })
    VIDEO_MODEL_OPTIONS.splice(0, VIDEO_MODEL_OPTIONS.length, {
      value: 'doubao-seedance-2.0-all-in-one',
      label: 'SD2.0',
    })
  })
  it('moves a retired model to the first available project model when opened', async () => {
    VIDEO_MODEL_OPTIONS.splice(
      0,
      VIDEO_MODEL_OPTIONS.length,
      { value: 'doubao-seedance-2.0-all-in-one', label: 'SD2.0' },
      { value: 'veo-3.1', label: 'Veo 3.1' },
    )
    const wrapper = mount(ShotGenerationOptionsPopover, {
      props: { modelValue: { ...options, videoModel: 'veo-3.1' }, mode: 'shot' },
    })
    await wrapper.get('[aria-label="调整生成参数"]').trigger('click')

    expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({
      videoModel: 'doubao-seedance-2.0-all-in-one',
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
    const select = document.querySelector('[aria-label="图片模型"]') as HTMLButtonElement
    expect(select.tagName).toBe('BUTTON')
    expect(select.textContent).toContain('Nano Banana 2.1')
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
      videoModel: DEFAULT_VIDEO_MODEL,
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
    const select = document.querySelector('[aria-label="H3 生成模式"]') as HTMLButtonElement
    expect(select.dataset.value).toBe('auto')
    expect(select.textContent).toContain('自动推荐')
    expect(document.body.textContent).not.toContain('尾帧 L2VA')
    wrapper.unmount()
  })
})
