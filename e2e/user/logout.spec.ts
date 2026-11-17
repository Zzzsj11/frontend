import { expect, test, type Route } from '@playwright/test'

test.use({ baseURL: 'http://127.0.0.1:4173', serviceWorkers: 'block' })

test('退出等待确认，失败保留账号，再次退出成功', async ({ page }) => {
  const user = {
    id: 'logout-test',
    username: 'logout-test',
    displayName: '退出测试用户',
    mustChangePassword: true,
    role: 'user',
  }
  await page.route('http://127.0.0.1:4173/api/**', (route) => route.fulfill({ json: {} }))
  await page.route('**/api/auth/refresh', (route) =>
    route.fulfill({ json: { accessToken: 'test' } }),
  )
  await page.route('**/api/auth/me', (route) => route.fulfill({ json: user }))
  let capture!: (route: Route) => void
  const pending = new Promise<Route>((resolve) => {
    capture = resolve
  })
  await page.route('**/api/auth/logout', capture, { times: 1 })
  await page.goto('/account/password')
  const menu = page.getByRole('button', { name: /退出测试用户/ })
  await menu.click()
  await page.getByRole('menuitem', { name: '退出登录' }).click()
  await expect(page.getByRole('menuitem', { name: '正在退出登录…' })).toBeDisabled()
  await (await pending).abort('internetdisconnected')
  await expect(page.getByText('退出登录失败，请再次尝试')).toBeVisible()
  await page.getByRole('button', { name: '我知道了' }).click()
  await expect(page).toHaveURL(/account\/password/)
  await expect(menu).toBeVisible()
  await page.route('**/api/auth/logout', (route) => route.fulfill({ json: { ok: true } }))
  if ((await menu.getAttribute('aria-expanded')) !== 'true') await menu.click()
  await page.getByRole('menuitem', { name: '退出登录' }).click()
  await expect(page).toHaveURL(/\/login$/)
})
