import { describe, expect, it } from 'vitest'
import {
  MAX_VIDEO_DURATION,
  MIN_VIDEO_DURATION,
  VIDEO_DURATION_CHOICES,
  normalizeShotOptions,
  normalizeVideoDuration,
} from '../src/mediaConstraints'
import { DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL } from '../src/generationModels'

describe('video duration constraints', () => {
  it('exposes every integer duration from 4 through 15 seconds', () => {
    expect(VIDEO_DURATION_CHOICES).toEqual([4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15])
  })

  it('normalizes legacy and planned durations before video generation', () => {
    expect(normalizeVideoDuration(2)).toBe(MIN_VIDEO_DURATION)
    expect(normalizeVideoDuration(9.6)).toBe(10)
    expect(normalizeVideoDuration(18)).toBe(MAX_VIDEO_DURATION)
    expect(normalizeShotOptions({ resolution: '1080p', duration: 3, ratio: '16:9', imageModel: DEFAULT_IMAGE_MODEL, videoModel: DEFAULT_VIDEO_MODEL }).duration).toBe(4)
  })
})
