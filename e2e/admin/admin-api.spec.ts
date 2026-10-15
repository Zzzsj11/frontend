import { expect, test } from '@playwright/test'
import { agentTestHeaders, remoteCredentials, testRunId } from '../env'
test.skip(!process.env.ADMIN_API_E2E, 'set ADMIN_API_E2E=1')
test('admin API authorization and contracts', async ({ request }) => {
  const { username, password } = remoteCredentials()
  const runId = testRunId()
  const login = await request.post('/api/auth/login', {
    data: { username, password },
    headers: agentTestHeaders(runId),
  })
  expect(login.ok()).toBeTruthy()
  const token = (await login.json()).accessToken
  const headers = { Authorization: `Bearer ${token}`, ...agentTestHeaders(runId) }
  for (const path of [
    '/api/admin/dashboard',
    '/api/admin/users',
    '/api/admin/projects',
    '/api/admin/jobs',
    '/api/admin/usage',
    '/api/admin/video-billing?limit=1',
    '/api/admin/models',
    '/api/admin/api-errors',
    '/api/admin/audit-logs',
    '/api/admin/song-emotion-profiles?limit=1',
    '/api/admin/prompt-optimizer/status',
    '/api/admin/prompt-optimizer/tasks',
  ])
    expect((await request.get(path, { headers })).ok(), path).toBeTruthy()
  const options = await request.get('/api/model-options?modality=video', { headers })
  expect(options.ok()).toBeTruthy()
  const videos = await options.json()
  expect(videos).toHaveLength(12)
  expect(videos.every((item: { id: string }) => item.id.endsWith('-all-in-one'))).toBeTruthy()
  expect(
    (await options.json()).some((x: { id: string }) => x.id === 'doubao-seedance-2.0-all-in-one'),
  ).toBeTruthy()
  expect((await request.get('/api/admin/dashboard')).status()).toBe(401)
})
