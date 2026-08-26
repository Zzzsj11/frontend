export interface VideoCostItem {
  duration: number
  model?: string
}

export const SD20_ESTIMATE_PRICE_PER_SECOND = 0.83
export const H3_ESTIMATE_PRICE_PER_SECOND = 0.425

export const videoEstimateUnitPrice = (model?: string): number =>
  model?.startsWith('minimax-h3') ? H3_ESTIMATE_PRICE_PER_SECOND : SD20_ESTIMATE_PRICE_PER_SECOND

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
