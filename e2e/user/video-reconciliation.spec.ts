import { expect, test } from '@playwright/test'

test('automatic recovery keeps observing original job and blocks creation', async ({ page }) => {
  let generated = 0
  await page.route('**/api/**', async (route) => {
    if (!new URL(route.request().url()).pathname.startsWith('/api/')) return route.continue()
    if (route.request().url().includes('/generations/videos')) generated++
    await route.fulfill({ json: [] })
  })
  await page.route('**/recovery-fixture', (route) =>
    route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' }),
  )
  await page.goto('/recovery-fixture')
  await page.evaluate(async () => {
    const load = (path: string) => import(/* @vite-ignore */ path)
    const { createApp } = await load('/node_modules/.vite/deps/vue.js')
    const { createPinia } = await load('/node_modules/.vite/deps/pinia.js')
    const { useProjectStore } = await load('/src/stores/project.ts')
    const { default: status } = await load('/src/components/VideoGenerationStatus.vue')
    const store = useProjectStore(createPinia())
    store.lines = [
      {
        id: 'original',
        shot: { status: 'failed', generationPhase: 'auto_reconciling', assets: [] },
      },
    ]
    await store.generateShotFor('original')
    createApp(status, { phase: 'auto_reconciling', hasAssets: false }).mount('#app')
  })
  await expect(page.getByRole('status')).toContainText('正在自动核对并恢复原视频')
  await expect(page.getByRole('status')).toContainText('不会重复扣费')
  expect(generated).toBe(0)
})
