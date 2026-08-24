import { describe, expect, it } from 'vitest'

import { generationModelLabel, isH3VideoModel } from '../../src/generationModels'

describe('generation model labels', () => {
  it('shows a finite model concurrency limit in every model picker', () => {
    expect(
      generationModelLabel({
        value: 'minimax-h3-runninghub',
        label: 'H3',
        capabilities: { executionConcurrency: 2 },
      }),
    ).toBe('H3（并发上限 2）')
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
})
