import type { CreativeReferenceMedia } from '../types'

export type CreativeGenerationMode = 'text' | 'first_frame' | 'first_last' | 'reference'

export const creativeModeReady = (
  mode: CreativeGenerationMode,
  media: CreativeReferenceMedia[],
): boolean => {
  const images = media.filter((item) => item.kind === 'image').length
  const videos = media.filter((item) => item.kind === 'video').length
  const audios = media.filter((item) => item.kind === 'audio').length
  if (mode === 'text') return true
  if (mode === 'first_frame') return images === 1 && videos === 0 && audios === 0
  if (mode === 'first_last') return images === 2 && videos === 0 && audios === 0
  return media.length > 0 && images <= 6 && videos <= 1 && audios <= 3 && media.length <= 10
}

export const creativeReferences = (
  mode: CreativeGenerationMode,
  media: CreativeReferenceMedia[],
) => {
  const images = media.filter((item) => item.kind === 'image').map((item) => item.url)
  return {
    firstFrameUrl: mode === 'first_frame' || mode === 'first_last' ? images[0] : undefined,
    lastFrameUrl: mode === 'first_last' ? images[1] : undefined,
    imageUrls: mode === 'reference' ? images : [],
    videoUrls:
      mode === 'reference'
        ? media.filter((item) => item.kind === 'video').map((item) => item.url)
        : [],
    audioUrls:
      mode === 'reference'
        ? media.filter((item) => item.kind === 'audio').map((item) => item.url)
        : [],
  }
}
