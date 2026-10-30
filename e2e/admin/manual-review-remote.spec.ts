import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { agentTestHeaders } from '../env'
test.skip(!process.env.REVIEW_FIXTURE_FILE, 'Requires isolated test-server fixture')

test('test server: review survives reload, blocks retry, administrator releases with audit', async ({
  page,
  request,
}) => {
  expect(process.env.REMOTE_API_BASE_URL).toBe('https://mv-test.epaipix.com')
  const fixture = JSON.parse(readFileSync(process.env.REVIEW_FIXTURE_FILE!, 'utf8'))
  const headers = agentTestHeaders(fixture.runId)
  await page.route('**/api/**', (route) =>
    route.continue({ headers: { ...route.request().headers(), ...headers } }),
  )
  const login = await request.post('/api/auth/login', {
    headers,
    data: { username: fixture.username, password: fixture.password },
  })
  expect(login.ok()).toBeTruthy()
  const auth = { ...headers, Authorization: `Bearer ${(await login.json()).accessToken}` }
  await page.goto('/login')
  await page.getByLabel('用户名').fill(fixture.username)
  await page.getByLabel('密码').fill(fixture.password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/projects/)
  await page.getByText('待人工核对验收', { exact: true }).click()
  await expect(page.getByText('待人工核对 · 不能重新生成')).toBeVisible()
  await page.reload()
  await expect(page.getByText('待人工核对 · 不能重新生成')).toBeVisible()
  await expect(page.getByText(/1 个镜头待人工核对，已排除/)).toBeVisible()
  const blocked = await request.post('/api/generations/videos', {
    headers: auth,
    data: {
      model: 'doubao-seedance-2.0-all-in-one',
      prompt: '测试镜头',
      duration: 5,
      project_task_id: fixture.taskId,
      storyboard_line_id: fixture.lineId,
      request_id: fixture.runId,
    },
  })
  expect(blocked.status()).toBe(409)
  expect(await blocked.text()).toContain('待人工核对')
  await page.goto('/admin')
  await page.getByRole('button', { name: '生成任务', exact: true }).click()
  const row = page.getByRole('row').filter({ hasText: fixture.jobId })
  await row.getByRole('button', { name: '处理待人工核对' }).click()
  await row.getByLabel('核查依据').fill('合成验收工单：未调用平台，已确认未受理')
  await row.getByRole('checkbox').check()
  await row.getByRole('button', { name: '解除重试限制' }).click()
  await expect(row.getByRole('button', { name: '处理待人工核对' })).toHaveCount(0)
  const after = await request.get(`/api/generations/${fixture.jobId}`, { headers: auth })
  expect((await after.json()).retryAllowed).toBe(true)
  const audit = await request.get('/api/admin/audit-logs', { headers: auth })
  expect(
    (await audit.json()).items.some(
      (item: { action: string; targetId: string }) =>
        item.action === 'job.release_review' && item.targetId === fixture.jobId,
    ),
  ).toBe(true)
  await page.goto('/projects')
  await page.getByText('待人工核对验收', { exact: true }).click()
  await expect(page.getByText('待人工核对 · 不能重新生成')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /生成视频片段/ }).first()).toBeEnabled()
  await request.delete(`/api/projects/${fixture.projectId}`, { headers: auth })
})
