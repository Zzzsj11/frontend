import type { ShotGenOptions } from './types'

export const MIN_VIDEO_DURATION = 4
export const MAX_VIDEO_DURATION = 15
export const DEFAULT_VIDEO_DURATION = 5
export const VIDEO_DURATION_CHOICES = Array.from(
  { length: MAX_VIDEO_DURATION - MIN_VIDEO_DURATION + 1 },
  (_, index) => MIN_VIDEO_DURATION + index,
)

export const normalizeVideoDuration = (value?: number): number => {
  const rounded = Number.isFinite(value) ? Math.round(value as number) : DEFAULT_VIDEO_DURATION
  return Math.min(MAX_VIDEO_DURATION, Math.max(MIN_VIDEO_DURATION, rounded))
}

export const normalizeShotOptions = (options: ShotGenOptions): ShotGenOptions => ({
  ...options,
  duration: normalizeVideoDuration(options.duration),
})
