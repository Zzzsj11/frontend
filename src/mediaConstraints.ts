import type { ShotGenOptions } from './types'
import { DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL, videoDurationChoices } from './generationModels'

export const MIN_VIDEO_DURATION = 4
export const MAX_VIDEO_DURATION = 15
export const DEFAULT_VIDEO_DURATION = 5
export const DEFAULT_H3_MODE: NonNullable<ShotGenOptions['h3Mode']> = 'auto'
export const VIDEO_DURATION_CHOICES = Array.from(
  { length: MAX_VIDEO_DURATION - MIN_VIDEO_DURATION + 1 },
  (_, index) => MIN_VIDEO_DURATION + index,
)

export const normalizeVideoDuration = (value?: number, model?: string): number => {
  const rounded = Number.isFinite(value) ? Math.round(value as number) : DEFAULT_VIDEO_DURATION
  const allowed = videoDurationChoices(model)
  if (allowed.length)
    return [...allowed].sort((a, b) => Math.abs(a - rounded) - Math.abs(b - rounded) || b - a)[0]!
  return Math.min(MAX_VIDEO_DURATION, Math.max(MIN_VIDEO_DURATION, rounded))
}

export const normalizeShotOptions = (options: ShotGenOptions): ShotGenOptions => ({
  ...options,
  duration: normalizeVideoDuration(options.duration, options.videoModel),
  imageModel: options.imageModel || DEFAULT_IMAGE_MODEL,
  imageResolution: options.imageResolution ?? '1K',
  videoModel: options.videoModel || DEFAULT_VIDEO_MODEL,
  generateAudio: options.generateAudio ?? false,
  watermark: options.watermark ?? false,
  h3Mode: options.h3Mode ?? DEFAULT_H3_MODE,
  h3FirstFrameUrl: options.h3FirstFrameUrl?.trim() || undefined,
  h3LastFrameUrl: options.h3LastFrameUrl?.trim() || undefined,
  referenceImageUrls: (options.referenceImageUrls ?? []).filter(Boolean),
  referenceVideoUrls: (options.referenceVideoUrls ?? []).filter(Boolean),
  referenceAudioUrls: (options.referenceAudioUrls ?? []).filter(Boolean),
  h3AudioUsage: options.h3AudioUsage ?? 'reference',
})
