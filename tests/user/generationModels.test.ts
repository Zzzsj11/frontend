import { describe, expect, it } from 'vitest'

import {
  generationModelLabel,
  isH3VideoModel,
  sortVideoModelOptions,
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
    expect(isH3VideoModel('minimax-h3-ppio')).toBe(true)
    expect(isH3VideoModel('doubao-seedance-2.0')).toBe(false)
  })

  it('keeps the temporary RunningHub H3 option at the end', () => {
    expect(
      sortVideoModelOptions([
        { value: 'minimax-h3-runninghub', label: 'H3' },
        { value: 'doubao-seedance-2.0', label: 'SD2.0' },
        { value: 'minimax-h3', label: 'H3' },
      ]).map((option) => option.value),
    ).toEqual(['doubao-seedance-2.0', 'minimax-h3', 'minimax-h3-runninghub'])
  })
})
