export interface VideoCostItem {
  duration: number
  model?: string
}

export const videoEstimateUnitPrice = (model?: string): number =>
  model?.startsWith('minimax-h3') ? 0.5 : 1

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
