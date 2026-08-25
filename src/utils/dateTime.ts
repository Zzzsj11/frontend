export const CHINA_TIME_ZONE = 'Asia/Shanghai'

type DateValue = string | number | Date

const toDate = (value: DateValue) => (value instanceof Date ? value : new Date(value))

export const formatChinaDateTime = (value: DateValue) =>
  toDate(value).toLocaleString('zh-CN', { timeZone: CHINA_TIME_ZONE, hour12: false })

export const formatChinaTime = (value: DateValue) =>
  toDate(value).toLocaleTimeString('zh-CN', { timeZone: CHINA_TIME_ZONE, hour12: false })
