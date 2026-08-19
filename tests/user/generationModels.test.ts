import { describe, expect, it } from 'vitest'

import { generationModelLabel } from '../../src/generationModels'

describe('generation model labels', () => {
  it('shows a finite model concurrency limit in every model picker', () => {
    expect(
      generationModelLabel({
        value: 'minimax-h3-runninghub',
        label: 'MiniMax H3',
        capabilities: { executionConcurrency: 2 },
      }),
    ).toBe('MiniMax H3（并发上限 2）')
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
})
