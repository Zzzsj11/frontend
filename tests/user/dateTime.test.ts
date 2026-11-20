import { describe, expect, it } from 'vitest'
import {
  formatAdminCell,
  formatAdminJson,
  formatChinaDateTime,
  formatChinaTime,
} from '../../src/utils/dateTime'

describe('北京时间格式化', () => {
  it('不受浏览器本地时区影响，固定显示东八区', () => {
    const instant = '2026-08-25T14:16:22Z'
    expect(formatChinaDateTime(instant)).toBe('2026/08/25 22:16:22')
    expect(formatChinaTime(instant)).toBe('22:16:22')
  })
})

it('formats nested admin timestamps across midnight and preserves date-only values', () => {
  const row = { events: [{ at: '2026-11-15T16:59:26.714276Z' }], day: '2026-11-15' }
  expect(JSON.parse(formatAdminJson(row))).toEqual({
    events: [{ at: '2026/11/16 00:59:26' }],
    day: '2026-11-15',
  })
  expect(formatAdminCell(row.events[0].at)).toBe('2026/11/16 00:59:26')
})
