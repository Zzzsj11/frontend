import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { isRemoteRunRequested, targetBaseURL } from '../../e2e/env'

beforeEach(() => {
  for (const name of [
    'REMOTE_FRONTEND_E2E',
    'REMOTE_API_E2E',
    'ADMIN_API_E2E',
    'ADMIN_CONSOLE_E2E',
    'REMOTE_API_BASE_URL',
    'PLAYWRIGHT_BASE_URL',
  ])
    vi.stubEnv(name, undefined)
})
afterEach(() => vi.unstubAllEnvs())

it('未开启远程验收时使用本机目标，0 不被当作开启', () => {
  vi.stubEnv('REMOTE_API_E2E', '0')
  expect(isRemoteRunRequested()).toBe(false)
  expect(targetBaseURL()).toBe('http://127.0.0.1:4173')
})
it('显式开启远程验收时必须提供目标，不隐式命中本机', () => {
  vi.stubEnv('REMOTE_API_E2E', '1')
  expect(() => targetBaseURL()).toThrow('必须显式设置')
  vi.stubEnv('REMOTE_API_BASE_URL', 'https://review.example.test')
  expect(targetBaseURL()).toBe('https://review.example.test')
})
