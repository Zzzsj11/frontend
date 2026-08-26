export const formatElapsedSeconds = (value?: number): string => {
  if (value == null || !Number.isFinite(value) || value < 0) return '-'
  const seconds = Math.round(value)
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return remainder ? `${minutes} 分 ${remainder} 秒` : `${minutes} 分钟`
}
