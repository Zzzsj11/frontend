import { describe, expect, it } from 'vitest'

import {
  VIDEO_MODEL_OPTIONS,
  generationModelLabel,
  isH3VideoModel,
  sortVideoModelOptions,
  videoResolutionLabel,
} from '../../src/generationModels'

describe('generation model labels', () => {
  it('shows a finite model concurrency limit in every model picker', () => {
    expect(
      generationModelLabel({
        value: 'minimax-h3-runninghub',
        label: 'H3',
        capabilities: { executionConcurrency: 2 },
      }),
    ).toBe('H3（RunningHub，2并发，仅测试时用）')
  })

  it('does not annotate the effectively unlimited default pool', () => {
    expect(
      generationModelLabel({
        value: 'doubao-seedance-2.0',
        label: 'SD2.0',
        capabilities: { executionConcurrency: 200 },
      }),
    ).toBe('SD2.0')
  })

  it('recognizes both the retained RunningHub model and direct H3 model', () => {
    expect(isH3VideoModel('minimax-h3-runninghub')).toBe(true)
    expect(isH3VideoModel('minimax-h3')).toBe(true)
    expect(isH3VideoModel('doubao-seedance-2.0')).toBe(false)
  })

  it('sorts video models by Yinghe, ToAPIs, RunningHub, then other providers', () => {
    expect(
      sortVideoModelOptions([
        {
          value: 'veo-3.1-generate-preview',
          label: 'Veo 3.1（英和海外）',
          capabilities: { providerCode: 'yseeai' },
        },
        {
          value: 'minimax-h3-runninghub',
          label: 'H3',
          capabilities: { providerCode: 'runninghub' },
        },
        { value: 'viduq3-pro', label: 'Vidu Q3 Pro', capabilities: { providerCode: 'toapis' } },
        {
          value: 'doubao-seedance-2.0',
          label: 'SD2.0',
          capabilities: { providerCode: 'yinghe' },
        },
      ]).map((option) => option.value),
    ).toEqual([
      'doubao-seedance-2.0',
      'viduq3-pro',
      'minimax-h3-runninghub',
      'veo-3.1-generate-preview',
    ])
  })

  it('uses each provider real H3 output tier as the resolution label', () => {
    const original = [...VIDEO_MODEL_OPTIONS]
    VIDEO_MODEL_OPTIONS.splice(
      0,
      VIDEO_MODEL_OPTIONS.length,
      {
        value: 'minimax-h3',
        label: 'H3（英和）',
        capabilities: { resolutionLabels: { '720p': '768P' } },
      },
      {
        value: 'minimax-h3-runninghub',
        label: 'H3（RunningHub）',
        capabilities: { resolutionLabels: { '720p': '736P' } },
      },
    )
    try {
      expect(videoResolutionLabel('minimax-h3', '720p')).toBe('768P')
      expect(videoResolutionLabel('minimax-h3-runninghub', '720p')).toBe('736P')
      expect(videoResolutionLabel('minimax-h3', '480p')).toBe('480P')
    } finally {
      VIDEO_MODEL_OPTIONS.splice(0, VIDEO_MODEL_OPTIONS.length, ...original)
    }
  })
})
