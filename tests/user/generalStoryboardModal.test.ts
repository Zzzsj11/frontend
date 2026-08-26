import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import GeneralStoryboardModal from '../../src/components/GeneralStoryboardModal.vue'
import { DEFAULT_SHOT_OPTIONS, useProjectStore } from '../../src/stores/project'
import * as apiClient from '../../src/api/client'
import * as confirmDialogModule from '../../src/composables/useConfirmDialog'

describe('general storyboard defaults', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('pins the shot-level default resolution to 480p', () => {
    expect(DEFAULT_SHOT_OPTIONS.resolution).toBe('480p')
    expect(DEFAULT_SHOT_OPTIONS.ratio).toBe('16:9')
  })

  it('defaults the modal resolution select to 720p', async () => {
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
    expect(resolutionSelect!.value).toBe('720p')
    const videoModelSelect = document.body.querySelector(
      'select[aria-label="视频模型"]',
    ) as HTMLSelectElement
    expect(videoModelSelect).toBeTruthy()
    expect(videoModelSelect.disabled).toBe(false)
    wrapper.unmount()
  })

  it('defaults the generation scale to 4+13 shots over 210 seconds', async () => {
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
      expect(document.body.querySelectorAll('input[type="number"]').length).toBe(4),
    )

    const numbers = Array.from(
      document.body.querySelectorAll('input[type="number"]'),
    ) as HTMLInputElement[]
    // 空镜数量 / 人物镜数量 / 总时长（秒）/ 生成组数
    expect(numbers.map((el) => el.value)).toEqual(['4', '13', '210', '1'])
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

  it('does not carry the active task cast into a newly opened form', async () => {
    const store = useProjectStore()
    store.castIds = ['dh-1']
    store.digitalHumans = [
      {
        id: 'dh-1',
        name: '测试人物',
        style: '写实',
        avatar: 'https://example.test/avatar.jpg',
        description: '',
      },
    ]
    store.generalStoryboardOptions = {
      genres: [{ value: 'pop', label: '流行歌曲' }],
      seasons: ['秋'],
      ageGroups: ['青年'],
      visualStyles: ['电影写实'],
      ratios: ['16:9'],
    }
    store.generalStoryboardOpen = true
    const wrapper = mount(GeneralStoryboardModal, { attachTo: document.body })
    await vi.waitFor(() => expect(document.body.querySelector('.cast-item')).not.toBeNull())
    expect(document.body.querySelectorAll('.cast-item.active')).toHaveLength(0)
    wrapper.unmount()
  })

  it('requires a manual cast only when the selected category policy requires it', async () => {
    const store = useProjectStore()
    store.generalStoryboardOptions = {
      genres: [
        {
          value: 'pop',
          label: '流行歌曲',
          children: [{ value: 'love', label: '爱情积极', castPolicy: 'required' }],
        },
      ],
      seasons: ['秋'],
      ageGroups: ['青年'],
      visualStyles: ['电影写实'],
      ratios: ['16:9'],
    }
    store.generalStoryboardOpen = true
    const wrapper = mount(GeneralStoryboardModal, { attachTo: document.body })
    await vi.waitFor(() =>
      expect(document.body.querySelector('.modal h4')?.textContent).toContain('音乐属性'),
    )
    const submit = document.body.querySelector('.modal-footer .btn-primary') as HTMLButtonElement
    expect(document.body.textContent).toContain('当前分类必须手动选择至少一位人物')
    expect(submit.disabled).toBe(true)
    wrapper.unmount()
  })

  it('random mode keeps music and 3+17 shot scale but removes visual and cast fields', async () => {
    const store = useProjectStore()
    store.generalStoryboardOptions = {
      genres: [{ value: 'pop', label: '流行歌曲' }],
      seasons: ['秋'],
      ageGroups: ['青年'],
      visualStyles: ['电影写实'],
      ratios: ['16:9'],
    }
    store.randomGeneralStoryboardOpen = true
    const wrapper = mount(GeneralStoryboardModal, {
      props: { random: true },
      attachTo: document.body,
    })
    await vi.waitFor(() => expect(document.body.textContent).toContain('随机通用分镜'))

    expect(document.body.textContent).toContain('音乐属性')
    expect(document.body.textContent).toContain('生成规模')
    expect(document.body.textContent).toContain('空镜数量')
    expect(document.body.textContent).toContain('人物镜数量')
    expect(document.body.textContent).not.toContain('视觉与人物设定')
    expect(document.body.textContent).not.toContain('人物素材')
    expect(document.body.textContent).not.toContain('图片模型')
    const numbers = Array.from(
      document.body.querySelectorAll('input[type="number"]'),
    ) as HTMLInputElement[]
    expect(numbers.map((input) => input.value)).toEqual(['3', '14', '210', '1'])
    wrapper.unmount()
  })

  it('随机批量生成会展示费用和 Key 余额，确认后才提交', async () => {
    const store = useProjectStore()
    store.generalStoryboardOptions = {
      genres: [{ value: 'pop', label: '流行歌曲' }],
      seasons: ['秋'],
      ageGroups: ['青年'],
      visualStyles: ['电影写实'],
      ratios: ['16:9'],
    }
    store.randomGeneralStoryboardOpen = true
    const run = vi.spyOn(store, 'runRandomGeneralStoryboard').mockResolvedValue()
    vi.spyOn(apiClient, 'apiRequest').mockImplementation((path: string) => {
      if (path.startsWith('/account/balance')) {
        return Promise.resolve({
          available: true,
          balance: '500',
          balanceDisplay: '500.00',
          currency: 'CNY',
          updatedAt: '',
          key: {
            keyMasked: 'yh-test***',
            keyName: '视频子账号',
            quotaAmt: 500,
            usedAmt: 100,
            remaining: 400,
            remainingDisplay: '400.00',
          },
        })
      }
      return Promise.resolve([])
    })
    const confirm = vi.spyOn(confirmDialogModule, 'confirmDialog').mockResolvedValue(true)
    const wrapper = mount(GeneralStoryboardModal, {
      props: { random: true },
      attachTo: document.body,
    })
    ;(document.body.querySelector('.modal-footer .btn-primary') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(confirm).toHaveBeenCalled())
    expect(confirm.mock.calls[0][0]).toMatchObject({ title: '确认批量生成视频' })
    expect(String((confirm.mock.calls[0][0] as { message: string }).message)).toContain(
      '本次预估费用：¥174.30',
    )
    expect(run).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('Key 剩余额度不足时阻止创建项目和视频任务', async () => {
    const store = useProjectStore()
    store.generalStoryboardOptions = {
      genres: [{ value: 'pop', label: '流行歌曲' }],
      seasons: ['秋'],
      ageGroups: ['青年'],
      visualStyles: ['电影写实'],
      ratios: ['16:9'],
    }
    store.randomGeneralStoryboardOpen = true
    const run = vi.spyOn(store, 'runRandomGeneralStoryboard').mockResolvedValue()
    vi.spyOn(apiClient, 'apiRequest').mockResolvedValue({
      available: true,
      balance: '100',
      balanceDisplay: '100.00',
      currency: 'CNY',
      updatedAt: '',
      key: {
        keyMasked: 'yh-low***',
        keyName: '低额度 Key',
        quotaAmt: 100,
        usedAmt: 90,
        remaining: 10,
        remainingDisplay: '10.00',
      },
    })
    const confirm = vi.spyOn(confirmDialogModule, 'confirmDialog').mockResolvedValue(false)
    const wrapper = mount(GeneralStoryboardModal, {
      props: { random: true },
      attachTo: document.body,
    })
    ;(document.body.querySelector('.modal-footer .btn-primary') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(confirm).toHaveBeenCalled())
    expect(confirm.mock.calls[0][0]).toMatchObject({ title: '余额额度不足', danger: true })
    expect(run).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
