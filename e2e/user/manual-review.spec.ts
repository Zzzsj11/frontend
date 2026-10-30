import { expect, test } from '@playwright/test'

test('manual review explains blocked retry and admin release requires evidence', async ({
  page,
}) => {
  let released = 0
  let generated = 0
  await page.route('**/api/**', async (route) => {
    if (!new URL(route.request().url()).pathname.startsWith('/api/')) return route.continue()
    if (route.request().url().includes('/generations/videos')) generated++
    if (route.request().url().includes('/release-review')) {
      const body = route.request().postDataJSON()
      expect(body.confirmed_not_accepted).toBe(true)
      expect(body.reason).toBe('平台确认未受理测试工单')
      released++
    }
    await route.fulfill({ json: [] })
  })
  await page.route('**/review-fixture', (route) =>
    route.fulfill({
      contentType: 'text/html',
      body: '<div id="user"></div><div id="admin"></div>',
    }),
  )
  await page.goto('/review-fixture')
  await page.evaluate(async () => {
    const load = (path: string) => import(/* @vite-ignore */ path)
    const { createApp } = await load('/node_modules/.vite/deps/vue.js')
    const { createPinia } = await load('/node_modules/.vite/deps/pinia.js')
    const { useProjectStore } = await load('/src/stores/project.ts')
    const { default: notice } = await load('/src/components/ManualReviewNotice.vue')
    const { default: admin } = await load('/src/components/AdminJobRelease.vue')
    const store = useProjectStore(createPinia())
    store.lines = [
      { id: 'blocked', shot: { status: 'failed', generationPhase: 'manual_review', assets: [] } },
    ]
    await store.generateShotFor('blocked')
    createApp(notice, { jobId: 'review-job', lineNumber: 1 }).mount('#user')
    createApp(admin, { jobId: 'review-job' }).mount('#admin')
  })
  await expect(page.getByText('待人工核对 · 不能重新生成')).toBeVisible()
  await expect(page.getByText(/重复点击不会发起新任务/)).toBeVisible()
  expect(generated).toBe(0)
  await page.getByRole('button', { name: '处理待人工核对' }).click()
  const release = page.getByRole('button', { name: '解除重试限制' })
  await expect(release).toBeDisabled()
  await page.getByLabel('核查依据').fill('平台确认未受理测试工单')
  await expect(release).toBeDisabled()
  await page.getByRole('checkbox').check()
  await release.click()
  await expect(release).toHaveCount(0)
  expect(released).toBe(1)
  expect(generated).toBe(0)
})
