import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchChatComparisonModels, runChatComparison } from '../../src/api/adminChatComparison'
import AdminChatComparisonPanel from '../../src/components/AdminChatComparisonPanel.vue'

vi.mock('../../src/api/adminChatComparison', () => ({
  fetchChatComparisonModels: vi.fn(),
  runChatComparison: vi.fn(),
}))

const models = [
  { code: 'gpt-5.5', name: 'GPT 5.5', protocol: 'openai' as const },
  { code: 'gpt-5.6-sol', name: 'GPT 5.6 Sol', protocol: 'openai' as const },
  { code: 'claude-opus-4-8', name: 'Claude Opus 4.8', protocol: 'anthropic' as const },
]

describe('admin chat comparison panel', () => {
  beforeEach(() => {
    vi.mocked(fetchChatComparisonModels).mockReset()
    vi.mocked(runChatComparison).mockReset()
    vi.mocked(fetchChatComparisonModels).mockResolvedValue(models)
  })

  it('sends one prompt to selected models and renders independent results', async () => {
    vi.mocked(runChatComparison).mockResolvedValue({
      results: [
        {
          model: 'gpt-5.5',
          name: 'GPT 5.5',
          protocol: 'openai',
          status: 'ok',
          text: 'GPT 的回答',
          error: '',
          durationMs: 1200,
          usage: { inputTokens: 10, outputTokens: 20, cachedInputTokens: 0, totalTokens: 30 },
        },
        {
          model: 'claude-opus-4-8',
          name: 'Claude Opus 4.8',
          protocol: 'anthropic',
          status: 'error',
          text: '',
          error: '供应商超时',
          durationMs: 2200,
          usage: { inputTokens: 0, outputTokens: 0, cachedInputTokens: 0, totalTokens: 0 },
        },
      ],
    })
    const wrapper = mount(AdminChatComparisonPanel)
    await vi.waitFor(() => expect(fetchChatComparisonModels).toHaveBeenCalled())
    await wrapper.find('textarea[placeholder]').setValue('同一个问题')
    await wrapper.find('.run-button').trigger('click')
    await vi.waitFor(() => expect(runChatComparison).toHaveBeenCalled())

    expect(runChatComparison).toHaveBeenCalledWith(
      expect.objectContaining({
        prompt: '同一个问题',
        models: ['gpt-5.5', 'gpt-5.6-sol', 'claude-opus-4-8'],
        temperature: 0.2,
        maxTokens: 2048,
      }),
    )
    expect(wrapper.text()).toContain('GPT 的回答')
    expect(wrapper.text()).toContain('供应商超时')
    expect(wrapper.text()).toContain('输入 10')
  })

  it('keeps GPT 5.5 selected by default and does not expose a default-switch action', async () => {
    const wrapper = mount(AdminChatComparisonPanel)
    await vi.waitFor(() => expect(wrapper.findAll('.model-option')).toHaveLength(3))
    const gpt = wrapper.findAll('.model-option').find((item) => item.text().includes('gpt-5.5'))
    expect(gpt?.attributes('aria-pressed')).toBe('true')
    expect(wrapper.text()).not.toContain('设为默认')
  })
})
