export const CHINA_TIME_ZONE = 'Asia/Shanghai'

type DateValue = string | number | Date

const toDate = (value: DateValue) => (value instanceof Date ? value : new Date(value))

const dateTime = new Intl.DateTimeFormat('zh-CN', {
  timeZone: CHINA_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
})

export const formatChinaDateTime = (value: DateValue) => {
  const date = toDate(value)
  return Number.isFinite(date.getTime()) ? dateTime.format(date) : '—'
}

function formatTimestamp(value: unknown) {
  if (
    typeof value === 'string' &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
  )
    return formatChinaDateTime(value)
  return value
}

export const formatAdminJson = (value: unknown, indent?: number) =>
  JSON.stringify(value, (_, item) => formatTimestamp(item), indent)

export function formatAdminCell(value: unknown) {
  return typeof value === 'object' ? formatAdminJson(value) : formatTimestamp(value)
}

export const formatChinaTime = (value: DateValue) =>
  toDate(value).toLocaleTimeString('zh-CN', { timeZone: CHINA_TIME_ZONE, hour12: false })
