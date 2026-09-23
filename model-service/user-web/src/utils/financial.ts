type Amount = string | number | null | undefined

// 直接处理十进制字符串，避免 1.005 等金额受到二进制浮点误差影响。
function display(value: Amount, places: number, round: boolean, shift = 0): string {
  if (value === null || value === undefined || value === '') return '—'
  const match = String(value)
    .trim()
    .match(/^([+-]?)(\d+)(?:\.(\d*))?(?:e([+-]?\d+))?$/i)
  if (!match) return '—'
  const exponent = Number(match[4] || 0) + shift
  if (!Number.isInteger(exponent) || Math.abs(exponent) > 100) return '—'
  const digits = match[2] + (match[3] || '')
  const cut = match[2].length + exponent + places
  let units = BigInt(cut > 0 ? digits.slice(0, cut).padEnd(cut, '0') : '0')
  if (round && cut >= 0 && Number(digits[cut] || '0') >= 5) units += 1n
  const text = units.toString().padStart(places + 1, '0')
  const integer = places ? text.slice(0, -places) : text
  const sign = match[1] === '-' && units !== 0n ? '-' : ''
  return sign + integer + (places ? '.' + text.slice(-places) : '')
}
export const points = (value: Amount) => display(value, 0, false)
export const moneyPoints = (value: Amount) => display(value, 0, false, 2)
export const money = (value: Amount) => display(value, 2, true)
export const signedPoints = (value: Amount) => {
  const formatted = points(value)
  return formatted !== '—' && formatted !== '0' && !formatted.startsWith('-')
    ? '+' + formatted
    : formatted
}
// 详情中的已知财务字段也只格式化副本；编辑器和 API 的原始数据不变。
export function financialDetails(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(financialDetails)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => {
      const scalar = typeof item === 'string' || typeof item === 'number'
      if (
        scalar &&
        /^(points|.*_points|monthly_balance|extra_balance|available_points|monthly_after|extra_after)$/.test(
          key,
        )
      )
        return [key, points(item)]
      if (scalar && /^(cny|usd|.*_cny|.*_usd|cny_per_unit|cny_balance|usd_cny)$/.test(key))
        return [key, money(item)]
      return [key, financialDetails(item)]
    }),
  )
}

export const prettyPoints = (value: Amount) => points(value).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
export const prettySignedPoints = (value: Amount) =>
  signedPoints(value).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
export function localDate(value: string) {
  const date = new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : value + 'Z')
  return Number.isNaN(date.getTime())
    ? '—'
    : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}
