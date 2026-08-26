import { describe, expect, it } from 'vitest'

import {
  estimateVideoBatchCost,
  formatVideoEstimateUnitPrice,
  videoEstimateUnitPrice,
} from '../../src/utils/videoBatchCost'

describe('video batch estimate cost', () => {
  it('按 SD2.0 0.83 元/秒与 H3 0.425 元/秒混合估算', () => {
    expect(
      estimateVideoBatchCost([
        { duration: 10, model: 'doubao-seedance-2.0' },
        { duration: 10, model: 'minimax-h3' },
      ]),
    ).toEqual({ totalSeconds: 20, estimatedCost: 12.55 })
  })

  it('完整显示三位小数的 H3 单价', () => {
    expect(formatVideoEstimateUnitPrice(videoEstimateUnitPrice('doubao-seedance-2.0'))).toBe('0.83')
    expect(formatVideoEstimateUnitPrice(videoEstimateUnitPrice('minimax-h3'))).toBe('0.425')
  })

  it('PPIO SD2.0 按八折后的 0.8 元每秒估算', () => {
    expect(videoEstimateUnitPrice('doubao-seedance-2.0-ppio')).toBe(0.8)
    expect(videoEstimateUnitPrice('minimax-h3-ppio')).toBe(0.425)
  })
})
