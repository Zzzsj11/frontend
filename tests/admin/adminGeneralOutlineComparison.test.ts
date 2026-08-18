import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  fetchChatComparisonModels,
  runGeneralOutlineComparison,
} from '../../src/api/adminChatComparison'
import AdminGeneralOutlineComparisonPanel from '../../src/components/AdminGeneralOutlineComparisonPanel.vue'

vi.mock('../../src/api/adminChatComparison', () => ({
  fetchChatComparisonModels: vi.fn(),
  runGeneralOutlineComparison: vi.fn(),
}))

describe('admin general outline comparison panel', () => {
  beforeEach(() => {
    vi.mocked(fetchChatComparisonModels).mockReset()
    vi.mocked(runGeneralOutlineComparison).mockReset()
    vi.mocked(fetchChatComparisonModels).mockResolvedValue([
      { code: 'gpt-5.5', name: 'GPT 5.5', protocol: 'openai' },
      { code: 'gpt-5.6-sol', name: 'GPT 5.6 Sol', protocol: 'openai' },
      { code: 'claude-opus-4-8', name: 'Claude Opus 4.8', protocol: 'anthropic' },
    ])
  })

  it('submits manual production-shaped configuration and renders validated shots', async () => {
    vi.mocked(runGeneralOutlineComparison).mockResolvedValue({
      results: [
        {
          model: 'gpt-5.5',
          name: 'GPT 5.5',
          protocol: 'openai',
          status: 'ok',
          error: '',
          totalDurationMs: 35000,
          attempts: 1,
          callMetrics: [{ operation: 'general_story_outline', status: 'ok', durationMs: 34900 }],
          usage: { inputTokens: 700, outputTokens: 1200, cachedInputTokens: 0, totalTokens: 1900 },
          shots: [
            {
              index: 0,
              shotType: 'empty',
              outlineScene: '黄昏海岸',
              outlineShot: '缓慢横移',
              requiredCharacterIds: [],
              intent: '建立环境',
              characterAction: '无人物',
              emotionalFocus: '孤独',
              cameraPurpose: '开场',
            },
          ],
        },
      ],
    })
    const wrapper = mount(AdminGeneralOutlineComparisonPanel)
    await vi.waitFor(() => expect(wrapper.text()).toContain('claude-opus-4-8'))
    await wrapper.find('.run-button').trigger('click')
    await vi.waitFor(() => expect(runGeneralOutlineComparison).toHaveBeenCalled())
    expect(runGeneralOutlineComparison).toHaveBeenCalledWith(
      expect.objectContaining({
        models: ['gpt-5.5', 'gpt-5.6-sol', 'claude-opus-4-8'],
        empty_shot_count: 4,
        character_shot_count: 17,
        total_duration: 210,
      }),
    )
    expect(wrapper.text()).toContain('总耗时 35.00s')
    expect(wrapper.text()).toContain('黄昏海岸')
    expect(wrapper.text()).toContain('校验通过')
  })
})
