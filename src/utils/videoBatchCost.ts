export interface VideoCostItem {
  duration: number
  model?: string
}

export const SD20_ESTIMATE_PRICE_PER_SECOND = 0.83
export const H3_ESTIMATE_PRICE_PER_SECOND = 0.425
export const PPIO_SD20_ESTIMATE_PRICE_PER_SECOND = 0.8

export type VideoProviderCode = 'yinghe' | 'ppio'

export const videoProviderForModel = (model?: string): VideoProviderCode =>
  model?.endsWith('-ppio') ? 'ppio' : 'yinghe'

export const videoEstimateUnitPrice = (model?: string): number => {
  if (model?.startsWith('minimax-h3')) return H3_ESTIMATE_PRICE_PER_SECOND
  return videoProviderForModel(model) === 'ppio'
    ? PPIO_SD20_ESTIMATE_PRICE_PER_SECOND
    : SD20_ESTIMATE_PRICE_PER_SECOND
}

export const formatVideoEstimateUnitPrice = (price: number): string =>
  price.toFixed(3).replace(/0+$/, '').replace(/\.$/, '')

export const estimateVideoBatchCost = (items: VideoCostItem[]) => {
  const totalSeconds = items.reduce((sum, item) => sum + Math.max(0, item.duration), 0)
  const estimatedCost = items.reduce(
    (sum, item) => sum + Math.max(0, item.duration) * videoEstimateUnitPrice(item.model),
    0,
  )
  return {
    totalSeconds: Math.round(totalSeconds * 100) / 100,
    estimatedCost: Math.round(estimatedCost * 100) / 100,
  }
}

export const estimateVideoBatchCostByProvider = (items: VideoCostItem[]) =>
  items.reduce<Partial<Record<VideoProviderCode, number>>>((totals, item) => {
    const provider = videoProviderForModel(item.model)
    totals[provider] =
      Math.round(
        ((totals[provider] ?? 0) +
          Math.max(0, item.duration) * videoEstimateUnitPrice(item.model)) *
          100,
      ) / 100
    return totals
  }, {})
