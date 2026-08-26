import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ScriptEditor from '../../src/components/ScriptEditor.vue'
import { useProjectStore } from '../../src/stores/project'
import type { ScriptLine } from '../../src/types'
import * as apiClient from '../../src/api/client'
import * as confirmDialogModule from '../../src/composables/useConfirmDialog'

const pendingLine = (id: string): ScriptLine =>
  ({
    id,
    generationStatus: 'succeeded',
    lyrics: '测试',
    scenePrompt: '',
    shotPrompt: '视频提示词',
    digitalHumanIds: [],
    shotOptions: {
      duration: 5,
      ratio: '16:9',
      resolution: '720p',
      videoModel: 'doubao-seedance-2.0',
    },
    voice: { status: 'none' },
    scene: { status: 'none' },
    shot: { status: 'none', assets: [] },
  }) as ScriptLine

describe('ScriptEditor batch generation confirmation', () => {
  beforeEach(() => setActivePinia(createPinia()))
  afterEach(() => vi.restoreAllMocks())

  it('汇总待生成条数、秒数和费用，确认后才批量生成', async () => {
    const store = useProjectStore()
    store.lines = [pendingLine('line-1'), pendingLine('line-2')]
    const generate = vi.spyOn(store, 'generateAllShots').mockResolvedValue()
    vi.spyOn(apiClient, 'apiRequest').mockResolvedValue({
      available: true,
      balance: '100',
      balanceDisplay: '100.00',
      currency: 'CNY',
      updatedAt: '',
      key: { remaining: 20, remainingDisplay: '20.00' },
    })
    const confirm = vi.spyOn(confirmDialogModule, 'confirmDialog').mockResolvedValue(true)
    const wrapper = mount(ScriptEditor)

    await wrapper.get('.header-actions .btn-outline').trigger('click')
    await vi.waitFor(() => expect(confirm).toHaveBeenCalled())
    const options = confirm.mock.calls[0][0] as { title: string; message: string }
    expect(options.title).toBe('确认批量生成视频')
    expect(options.message).toContain('本次将生成总计：2 条，共：10 秒')
    expect(options.message).toContain('预计总费用为：10.00 元')
    expect(options.message).toContain('当前子账号余额还有：20.00 元')
    expect(options.message).toContain('【余额充足，可以开始批量生成任务】')
    expect(generate).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('余额不足时提示联系负责人充值且不启动任务', async () => {
    const store = useProjectStore()
    store.lines = [pendingLine('line-1'), pendingLine('line-2')]
    const generate = vi.spyOn(store, 'generateAllShots').mockResolvedValue()
    vi.spyOn(apiClient, 'apiRequest').mockResolvedValue({
      available: true,
      balance: '5',
      balanceDisplay: '5.00',
      currency: 'CNY',
      updatedAt: '',
      key: { remaining: 5, remainingDisplay: '5.00' },
    })
    const confirm = vi.spyOn(confirmDialogModule, 'confirmDialog').mockResolvedValue(false)
    const wrapper = mount(ScriptEditor)

    await wrapper.get('.header-actions .btn-outline').trigger('click')
    await vi.waitFor(() => expect(confirm).toHaveBeenCalled())
    const options = confirm.mock.calls[0][0] as { title: string; message: string }
    expect(options.title).toBe('子账号余额不足')
    expect(options.message).toContain('【余额不足，请联系负责人进行充值】')
    expect(generate).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
