import { describe, expect, it } from 'vitest'
import { creativeModeReady, creativeReferences } from '../../src/utils/creativeVideo'
import type { CreativeReferenceMedia } from '../../src/types'

const item = (kind: CreativeReferenceMedia['kind'], url: string): CreativeReferenceMedia => ({
  kind,
  url,
  name: url,
  mimeType: `${kind}/test`,
  role: 'reference',
})

describe('creative video generation contracts', () => {
  it('requires exact media for first and first-last frame modes', () => {
    const one = [item('image', 'i1')]
    const two = [...one, item('image', 'i2')]
    expect(creativeModeReady('first_frame', one)).toBe(true)
    expect(creativeModeReady('first_frame', two)).toBe(false)
    expect(creativeModeReady('first_last', two)).toBe(true)
    expect(creativeModeReady('first_last', [...two, item('audio', 'a1')])).toBe(false)
  })

  it('only forwards mixed references in reference mode', () => {
    const media = [item('image', 'i1'), item('video', 'v1'), item('audio', 'a1')]
    expect(creativeReferences('text', media)).toMatchObject({
      imageUrls: [],
      videoUrls: [],
      audioUrls: [],
    })
    expect(creativeReferences('reference', media)).toMatchObject({
      imageUrls: ['i1'],
      videoUrls: ['v1'],
      audioUrls: ['a1'],
    })
  })
})
