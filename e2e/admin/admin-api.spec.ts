import { expect, test } from '@playwright/test'
import { remoteCredentials, testRunId } from '../env'
test.skip(!process.env.ADMIN_API_E2E, 'set ADMIN_API_E2E=1')
test('admin API authorization and contracts', async ({ request }) => {
  const { username, password } = remoteCredentials()
  const runId = testRunId()
  const login = await request.post('/api/auth/login', {
    data: { username, password },
    headers: { 'X-Test-Run-Id': runId },
  })
  expect(login.ok()).toBeTruthy()
  const token = (await login.json()).accessToken
  const headers = { Authorization: `Bearer ${token}`, 'X-Test-Run-Id': runId }
  for (const path of [
    '/api/admin/dashboard',
    '/api/admin/users',
    '/api/admin/projects',
    '/api/admin/jobs',
    '/api/admin/usage',
    '/api/admin/models',
    '/api/admin/api-errors',
    '/api/admin/audit-logs',
  ])
    expect((await request.get(path, { headers })).ok(), path).toBeTruthy()
  const options = await request.get('/api/model-options?modality=video', { headers })
  expect(options.ok()).toBeTruthy()
  expect(
    (await options.json()).some((x: { id: string }) => x.id === 'doubao-seedance-2.0'),
  ).toBeTruthy()
  expect((await request.get('/api/admin/dashboard')).status()).toBe(401)
})
