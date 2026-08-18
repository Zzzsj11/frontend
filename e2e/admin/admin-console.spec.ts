import { expect, test } from '@playwright/test'
import { remoteCredentials, testRunId } from '../env'
test.skip(!process.env.ADMIN_CONSOLE_E2E, 'set ADMIN_CONSOLE_E2E=1')
const { username, password } = remoteCredentials()
const runId = testRunId()
test('administrator can inspect dashboard, models, errors and audit logs', async ({ page }) => {
  await page.route('**/api/**', (route) =>
    route.continue({ headers: { ...route.request().headers(), 'x-test-run-id': runId } }),
  )
  await page.goto('/login')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password)
  const login = page.waitForResponse(
    (r) => r.url().includes('/api/auth/login') && r.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '登录' }).click()
  expect((await login).ok()).toBeTruthy()
  await expect(page).toHaveURL(/\/projects/)
  await page.goto('/admin')
  await expect(page.locator('.app-header')).toHaveCount(0)
  await expect(page.locator('.admin-topbar')).toBeVisible()
  await expect(page.getByRole('link', { name: '返回工作台' })).toHaveAttribute('href', '/projects')
  await expect(page.getByRole('heading', { name: '仪表盘' })).toBeVisible()
  await expect(page.getByText('累计 Token')).toBeVisible()
  await page.getByRole('button', { name: '用户' }).click()
  await expect(page.getByText('Chat/日').first()).toBeVisible()
  await expect(page.getByRole('button', { name: '保存日限额' }).first()).toBeVisible()
  await page.getByRole('button', { name: '模型管理' }).click()
  await expect(
    page.locator('tbody').getByText('gpt-image-2', { exact: true }).first(),
  ).toBeVisible()
  await expect(
    page.locator('tbody').getByText('doubao-seedance-2.0', { exact: true }).first(),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Chat 模型对比' }).click()
  await expect(page.getByRole('heading', { name: '通用 MV 大纲对比' })).toBeVisible()
  await expect(page.getByText('gpt-5.5', { exact: true })).toBeVisible()
  await expect(page.getByText('claude-opus-4-8', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '开始业务对比' })).toBeEnabled()
  await page.getByRole('button', { name: '自由提示词' }).click()
  await expect(page.getByRole('heading', { name: '同提示词多模型对比' })).toBeVisible()
  await page.getByRole('button', { name: '歌曲情感库' }).click()
  await expect(page.getByRole('heading', { name: '歌曲情感库' })).toBeVisible()
  await expect(page.getByLabel('搜索歌曲情感库')).toBeVisible()
  await expect(page.getByRole('button', { name: '新增歌曲' })).toBeVisible()
  await page.getByRole('button', { name: '费用用量' }).click()
  await expect(page.getByRole('heading', { name: '费用用量' })).toBeVisible()
  await page.getByRole('button', { name: '错误日志' }).click()
  await expect(page.getByRole('heading', { name: '错误日志' })).toBeVisible()
  await page.getByRole('button', { name: '操作审计' }).click()
  await expect(page.getByRole('heading', { name: '操作审计' })).toBeVisible()
  await page.getByRole('button', { name: '服务器监控' }).click()
  await expect(page.getByRole('heading', { name: '服务器资源监控' })).toBeVisible()
  await expect(page.getByText('月流量仅统计公网出站 · 自然月 300 GiB')).toBeVisible()
})

test('content administrator only sees and operates content configuration', async ({
  page,
  request,
}) => {
  const adminLogin = await request.post('/api/auth/login', {
    data: { username, password },
  })
  const adminHeaders = { Authorization: `Bearer ${(await adminLogin.json()).accessToken}` }
  const assUsername = `ass-admin-${Date.now()}`
  const assPassword = 'secure-pass-123'
  const created = await request.post('/api/admin/users', {
    headers: adminHeaders,
    data: { username: assUsername, password: assPassword },
  })
  const assUser = await created.json()
  await request.put(`/api/admin/users/${assUser.id}/admin-role`, {
    headers: adminHeaders,
    data: { admin_role_code: 'ass_admin' },
  })
  try {
    await page.goto('/login')
    await page.getByLabel('用户名').fill(assUsername)
    await page.getByLabel('密码').fill(assPassword)
    await page.getByRole('button', { name: '登录' }).click()
    await expect(page).toHaveURL(/\/projects/)
    await page.locator('.user-trigger').click()
    await expect(page.getByRole('menuitem', { name: '管理后台' })).toBeVisible()
    await page.getByRole('menuitem', { name: '管理后台' }).click()
    await expect(page).toHaveURL(/\/admin/)
    await expect(page.getByRole('heading', { name: '歌曲情感库' })).toBeVisible()
    await expect(page.getByRole('button', { name: '通用分类' })).toBeVisible()
    await expect(page.getByRole('button', { name: '歌曲情感库' })).toBeVisible()
    await expect(page.getByRole('button', { name: '仪表盘' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '用户' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '新增歌曲' })).toBeVisible()
    const assLogin = await request.post('/api/auth/login', {
      data: { username: assUsername, password: assPassword },
    })
    const assHeaders = { Authorization: `Bearer ${(await assLogin.json()).accessToken}` }
    expect((await request.get('/api/admin/dashboard', { headers: assHeaders })).status()).toBe(403)
  } finally {
    await request.delete(`/api/admin/users/${assUser.id}`, { headers: adminHeaders })
  }
})
