import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { agentTestHeaders } from '../env'

test.skip(!process.env.RECONCILE_FIXTURE_FILE, 'Requires isolated test-server fixture')
test('test server: original-video recovery and duplicate-submit guard', async ({
  page,
  request,
}) => {
  expect(process.env.REMOTE_API_BASE_URL).toBe('https://mv-test.epaipix.com')
  const f = JSON.parse(readFileSync(process.env.RECONCILE_FIXTURE_FILE!, 'utf8'))
  const headers = agentTestHeaders(f.runId)
  await page.route('**/api/**', (route) =>
    route.continue({ headers: { ...route.request().headers(), ...headers } }),
  )
  const login = await request.post('/api/auth/login', {
    headers,
    data: { username: f.username, password: f.password },
  })
  expect(login.ok()).toBeTruthy()
  const auth = { ...headers, Authorization: `Bearer ${(await login.json()).accessToken}` }
  await page.goto('/login')
  await page.getByLabel('用户名').fill(f.username)
  await page.getByLabel('密码').fill(f.password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/projects/)
  await page.getByText('待人工核对验收', { exact: true }).click()
  if (process.env.RECONCILE_PHASE === 'waiting') {
    await expect(page.getByText(/正在自动核对并恢复原视频/)).toBeVisible()
    await page.reload()
    await expect(page.getByText(/正在自动核对并恢复原视频/)).toBeVisible()
    for (let i = 0; i < 3; i++) {
      const retry = await request.post('/api/generations/videos', {
        headers: auth,
        data: {
          model: 'doubao-seedance-2.0-all-in-one',
          prompt: '测试镜头',
          duration: 5,
          project_task_id: f.taskId,
          storyboard_line_id: f.lineId,
          request_id: `${f.runId}-${i}`,
        },
      })
      expect(retry.status()).toBe(409)
      expect(await retry.text()).toContain('自动核对')
    }
  } else {
    await expect
      .poll(
        async () =>
          (await (await request.get(`/api/generations/${f.jobId}`, { headers: auth })).json())
            .status,
        { timeout: 120_000 },
      )
      .toBe('succeeded')
    const job = await (await request.get(`/api/generations/${f.jobId}`, { headers: auth })).json()
    expect(job.provider_task_id).toBe(f.platformId)
    expect(job.result.videoUrl).toBeTruthy()
    expect((await request.get(job.result.videoUrl)).ok()).toBeTruthy()
    expect((await request.get(job.result.coverUrl)).ok()).toBeTruthy()
    await page.reload()
    await expect(page.getByRole('button', { name: '重新生成视频片段', exact: true })).toBeVisible()
    for (let i = 0; i < 2; i++)
      expect(
        (await request.post(`/api/admin/jobs/${f.jobId}/sync`, { headers: auth })).ok(),
      ).toBeTruthy()
  }
})
