import { expect, test } from '@playwright/test'
import { selectDropdown } from '../select'
import videoCatalog from '../../backend/app/data/all_in_one_video_models_20261015.json' with { type: 'json' }

test('admin comparisons isolate channels and optimizer exposes text/video preferences', async ({
  page,
}) => {
  const gemini = 'gemini-3.8-flash-all-in-one'
  const seed = 'doubao-seed-2-1-pro-260915-all-in-one'
  const prefs: Record<string, unknown> = {}
  const submitted: Array<{ path: string; body: { channels: Record<string, string | null> } }> = []
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/api/**', async (route) => {
    const req = route.request(),
      url = new URL(req.url()),
      path = url.pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path === '/api/auth/refresh' || path === '/api/auth/login')
      return route.fulfill({
        json: {
          accessToken: 'mock',
          user: {
            id: 'channel-admin',
            username: 'mock',
            displayName: '管理员',
            role: 'admin',
            isSuperAdmin: true,
            permissions: [],
            mustChangePassword: false,
          },
        },
      })
    if (path === '/api/auth/me')
      return route.fulfill({
        json: {
          id: 'channel-admin',
          username: 'mock',
          displayName: '管理员',
          role: 'admin',
          isSuperAdmin: true,
          permissions: [],
          mustChangePassword: false,
        },
      })
    if (path === '/api/release') return route.fulfill({ json: { version: 'test' } })
    if (path.startsWith('/api/generation-preferences')) {
      if (req.method() === 'PUT') prefs[path.split('/').pop()!] = req.postDataJSON()
      return route.fulfill({ json: prefs })
    }
    if (path.endsWith('/channels'))
      return route.fulfill({
        json: {
          channels: [{ channel: 'test-route', name: '测试渠道', available: true, priority: 1 }],
        },
      })
    if (path === '/api/model-options')
      return route.fulfill({
        json: url.searchParams.has('modality')
          ? [{ id: gemini, name: 'Gemini 3.8 Flash' }]
          : videoCatalog.map((m) => ({
              id: m.code,
              name: m.name,
              modality: m.modality,
              capabilities: m.capabilities,
            })),
      })
    if (path === '/api/admin/chat-comparison/models')
      return route.fulfill({
        json: [
          { code: gemini, name: 'Gemini 3.8 Flash', protocol: 'openai' },
          { code: seed, name: 'Doubao', protocol: 'openai' },
        ],
      })
    if (path.startsWith('/api/admin/chat-comparison/') && req.method() === 'POST') {
      submitted.push({ path, body: req.postDataJSON() })
      return route.fulfill({ json: { results: [] } })
    }
    if (path === '/api/admin/prompt-optimizer/status')
      return route.fulfill({
        json: {
          providers: {
            gemini: { configured: true, model: gemini },
            minimax: { configured: false, model: '已停用' },
          },
          limits: { images: 9, videos: 3, audios: 3, videoSeconds: 15, audioSeconds: 15 },
          ratios: ['16:9', '9:16'],
          durationRange: [4, 15],
        },
      })
    if (req.method() !== 'GET') throw new Error('Unexpected mutation: ' + path)
    return route.fulfill({ json: { items: [], total: 0 } })
  })
  await page.goto('/admin')
  await page.getByRole('button', { name: 'Chat 模型对比', exact: true }).click()
  await selectDropdown(page.getByLabel('Gemini 3.8 Flash渠道', { exact: true }), '测试渠道')
  await page.getByRole('button', { name: '开始业务对比', exact: true }).click()
  await expect.poll(() => submitted.length).toBe(1)
  expect(submitted[0]!.body.channels).toEqual({ [gemini]: 'test-route', [seed]: null })
  await page.getByRole('button', { name: '自由提示词', exact: true }).click()
  await page.locator('textarea[placeholder]').fill('mock only')
  await selectDropdown(page.getByLabel('Doubao渠道', { exact: true }), '测试渠道')
  await page.getByRole('button', { name: '开始对比', exact: true }).click()
  await expect.poll(() => submitted.length).toBe(2)
  expect(submitted[1]!.body.channels).toEqual({ [gemini]: null, [seed]: 'test-route' })
  await page.getByRole('button', { name: '多参考提示词优化', exact: true }).click()
  await page.getByLabel('文本模型', { exact: true }).click()
  await page.getByRole('button', { name: 'Gemini 3.8 Flash渠道', exact: true }).click()
  await page.getByRole('button', { name: '测试渠道', exact: true }).click()
  expect(prefs.text).toEqual({ model: gemini, channel: 'test-route' })
  await page.getByLabel('视频模型', { exact: true }).click()
  await page.getByRole('button', { name: 'H3渠道', exact: true }).click()
  await page.getByRole('button', { name: '测试渠道', exact: true }).click()
  expect(prefs.video).toEqual({ model: 'minimax-h3-all-in-one', channel: 'test-route' })
  await selectDropdown(page.getByLabel('视频模型', { exact: true }), 'SD2.0')
  await expect(page.getByText('本实验页仅支持 H3 的生成参数，请主动选择 H3 后生成。')).toBeVisible()
  await expect(page.getByRole('button', { name: '使用 H3 生成视频', exact: true })).toBeDisabled()
  expect(errors).toEqual([])
})
