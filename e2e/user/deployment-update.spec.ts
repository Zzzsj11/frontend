import { expect, test } from '@playwright/test'

test('发现新版本后由用户点击版本条刷新页面', async ({ page }) => {
  let documentRequests = 0
  page.on('request', (request) => {
    if (request.resourceType() === 'document') documentRequests += 1
  })
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/auth/refresh')
      return route.fulfill({ status: 401, json: { detail: '未登录' } })
    if (path === '/api/auth/login')
      return route.fulfill({
        json: {
          accessToken: 'test-token',
          user: {
            id: 'user-update-e2e',
            username: 'admin',
            displayName: '管理员',
            role: 'admin',
            isSuperAdmin: true,
            permissions: [],
            mustChangePassword: false,
          },
        },
      })
    if (path === '/api/release')
      return route.fulfill({
        json: { version: 'git-next-release', deployedAt: '2026-09-06T08:45:00Z' },
      })
    if (
      path === '/api/projects' ||
      path === '/api/digital-humans' ||
      path === '/api/digital-human-styles'
    )
      return route.fulfill({ json: [] })
    if (path === '/api/model-options') return route.fulfill({ json: [] })
    if (path === '/api/account/balance')
      return route.fulfill({
        json: {
          available: false,
          balance: null,
          balanceDisplay: '--',
          currency: 'CNY',
          updatedAt: '',
        },
      })
    return route.fulfill({ status: 404, json: { detail: 'not mocked' } })
  })

  await page.goto('/login')
  await page.getByLabel('用户名').fill('admin')
  await page.getByLabel('密码').fill('123456')
  await page.getByRole('button', { name: '登录' }).click()

  const updateButton = page.getByRole('button', { name: '发现新版本，点击刷新页面' })
  await expect(updateButton).toBeVisible()
  await expect(updateButton).toHaveClass(/update-available/)
  await updateButton.click()
  await expect.poll(() => documentRequests).toBeGreaterThanOrEqual(2)
})
