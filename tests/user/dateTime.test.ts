import { describe, expect, it } from 'vitest'
import { formatChinaDateTime, formatChinaTime } from '../../src/utils/dateTime'

describe('北京时间格式化', () => {
  it('不受浏览器本地时区影响，固定显示东八区', () => {
    const instant = '2026-08-25T14:16:22Z'
    expect(formatChinaDateTime(instant)).toContain('22:16:22')
    expect(formatChinaTime(instant)).toBe('22:16:22')
  })
})
