import { describe, expect, it } from 'vitest'
import { shotTypeLabel } from '../../src/utils/shotLabel'

describe('shotTypeLabel', () => {
  it('uses structured character composition when available', () => {
    expect(
      shotTypeLabel({
        shotType: 'character',
        shotOptions: {
          characterComposition: {
            count: 2,
            countLabel: '双人',
            demographicLabel: '青年男性/青年女性',
            label: '人物镜*双人*青年男性/青年女性',
          },
        } as never,
      }),
    ).toBe('人物镜*双人*青年男性/青年女性')
  })

  it('keeps legacy fallback labels', () => {
    expect(shotTypeLabel({ shotType: 'character', shotOptions: undefined })).toBe('人物镜')
    expect(shotTypeLabel({ shotType: 'empty', shotOptions: undefined })).toBe('空镜')
    expect(shotTypeLabel({ shotType: 'creative', shotOptions: undefined })).toBe('创意分镜')
  })
})
