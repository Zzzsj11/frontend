import { expect, test, type Page } from '@playwright/test'

async function mountWorkspace(page: Page) {
  await page.evaluate(async () => {
    const load = (path: string) => import(/* @vite-ignore */ path)
    const { createApp, h } = await load('/node_modules/.vite/deps/vue.js')
    const { createPinia } = await load('/node_modules/.vite/deps/pinia.js')
    const { useProjectStore } = await load('/src/stores/project.ts')
    const { default: status } = await load('/src/components/VideoGenerationStatus.vue')
    const store = useProjectStore(createPinia())
    store.activeTaskId = 'task-1'
    store.lines = [
      {
        id: 'original',
        shot: { status: 'failed', generationPhase: 'auto_reconciling', assets: [] },
      },
    ]
    await store.generateShotFor('original')
    await store.resumeActiveGenerations('task-1')
    createApp({
      setup: () => () =>
        h(status, { phase: store.lines[0].shot.generationPhase, hasAssets: false }),
    }).mount('#app')
  })
}

test('automatic recovery keeps observing original job and blocks creation after reload', async ({
  page,
}) => {
  let generated = 0
  let activeLookups = 0
  const observed: string[][] = []
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path === '/api/tasks/task-1/generations/active') {
      activeLookups++
      return route.fulfill({
        json: [
          {
            id: 'job-original',
            kind: 'video',
            storyboardLineId: 'original',
            phase: 'auto_reconciling',
          },
        ],
      })
    }
    if (path === '/api/generations/status') {
      observed.push(route.request().postDataJSON().ids)
      return route.fulfill({
        json: [{ id: 'job-original', status: 'running', phase: 'auto_reconciling' }],
      })
    }
    if (path.startsWith('/api/generations/videos')) generated++
    await route.fulfill({ json: [] })
  })
  await page.route('**/recovery-fixture', (route) =>
    route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' }),
  )
  await page.goto('/recovery-fixture')
  for (let round = 0; round < 2; round++) {
    if (round) await page.reload()
    const before = observed.length
    await mountWorkspace(page)
    await expect.poll(() => observed.length).toBeGreaterThan(before)
    expect(generated).toBe(0)
    await expect(page.getByRole('status')).toContainText('正在查询原视频工单')
  }
  expect(activeLookups).toBe(2)
  expect(observed.every((ids) => ids.length === 1 && ids[0] === 'job-original')).toBe(true)
  expect(generated).toBe(0)
})
