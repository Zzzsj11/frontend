import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import GeneralStoryboardModal from '../../src/components/GeneralStoryboardModal.vue'
import { DEFAULT_SHOT_OPTIONS, useProjectStore } from '../../src/stores/project'

describe('general storyboard defaults', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('pins the shot-level default resolution to 480p', () => {
    expect(DEFAULT_SHOT_OPTIONS.resolution).toBe('480p')
    expect(DEFAULT_SHOT_OPTIONS.ratio).toBe('16:9')
  })

  it('defaults the modal resolution select to 480p', async () => {
    // loadGenerationModels 拉取失败会静默回退内置默认模型，无需 mock fetch
    const store = useProjectStore()
    // 模板里的 select 依赖 generalStoryboardOptions 渲染，直接注入最小选项集
    store.generalStoryboardOptions = {
      genres: [{ value: 'pop', label: '流行歌曲' }],
      seasons: ['春', '夏', '秋', '冬'],
      ageGroups: ['青年'],
      visualStyles: ['电影写实'],
      ratios: ['16:9'],
    }
    const wrapper = mount(GeneralStoryboardModal, { attachTo: document.body })
    store.generalStoryboardOpen = true
    // BaseModal Teleport 到 body，等 watch(reset) 与弹层渲染完成
    await vi.waitFor(() =>
      expect(document.body.querySelectorAll('select').length).toBeGreaterThan(0),
    )

    const selects = Array.from(document.body.querySelectorAll('select'))
    const resolutionSelect = selects.find((select) => select.querySelector('option[value="1080p"]'))
    expect(resolutionSelect, '未找到清晰度下拉框').toBeDefined()
    expect(resolutionSelect!.value).toBe('480p')
    wrapper.unmount()
  })

  it('defaults the generation scale to 1+1 shots over 8 seconds', async () => {
    const store = useProjectStore()
    store.generalStoryboardOptions = {
      genres: [{ value: 'pop', label: '流行歌曲' }],
      seasons: ['秋'],
      ageGroups: ['青年'],
      visualStyles: ['电影写实'],
      ratios: ['16:9'],
    }
    const wrapper = mount(GeneralStoryboardModal, { attachTo: document.body })
    store.generalStoryboardOpen = true
    await vi.waitFor(() =>
      expect(document.body.querySelectorAll('input[type="number"]').length).toBe(3),
    )

    const numbers = Array.from(
      document.body.querySelectorAll('input[type="number"]'),
    ) as HTMLInputElement[]
    // 空镜数量 / 人物镜数量 / 总时长（秒）
    expect(numbers.map((el) => el.value)).toEqual(['1', '1', '8'])
    wrapper.unmount()
  })

  it('allows submitting when the genre has no secondary category (戏曲/中文喊麦)', async () => {
    const store = useProjectStore()
    // 戏曲无下级分类：secondary 下拉为空，不要求选择
    store.generalStoryboardOptions = {
      genres: [{ value: 'xiqu', label: '戏曲' }],
      seasons: ['通用'],
      ageGroups: ['青年'],
      visualStyles: ['国风'],
      ratios: ['16:9'],
    }
    const wrapper = mount(GeneralStoryboardModal, { attachTo: document.body })
    store.generalStoryboardOpen = true
    await vi.waitFor(() => expect(document.body.querySelector('.btn-primary')).not.toBeNull())

    const submit = document.body.querySelector('.btn-primary') as HTMLButtonElement
    expect(submit.disabled).toBe(false)
    wrapper.unmount()
  })
})
