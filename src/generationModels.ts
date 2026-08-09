export const IMAGE_MODEL_OPTIONS = [
  { value: 'gpt-image-2', label: 'Img2' },
] as const

export const VIDEO_MODEL_OPTIONS = [
  { value: 'doubao-seedance-2.0', label: 'sd2.0' },
] as const

export type ImageModelId = (typeof IMAGE_MODEL_OPTIONS)[number]['value']
export type VideoModelId = (typeof VIDEO_MODEL_OPTIONS)[number]['value']

export const DEFAULT_IMAGE_MODEL: ImageModelId = IMAGE_MODEL_OPTIONS[0].value
export const DEFAULT_VIDEO_MODEL: VideoModelId = VIDEO_MODEL_OPTIONS[0].value
