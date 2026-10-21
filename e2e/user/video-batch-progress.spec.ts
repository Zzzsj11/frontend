import { expect, test } from '@playwright/test'
import { agentTestHeaders } from '../env'

// All supplier responses are synthetic; this test cannot submit real generation.
test('completed videos become ready independently and reload only observes pending jobs', async ({
  page,
}) => {
  await page.setExtraHTTPHeaders(agentTestHeaders(`code-video-progress-${Date.now()}`))
  let secondDone = false
  let submissions = 0
  const line = (id: string, done: boolean) => ({
    id,
    source: 'general_random',
    shotType: 'empty',
    lyrics: '',
    scenePrompt: '',
    shotPrompt: '公园树叶',
    digitalHumanIds: [],
    generationStatus: 'succeeded',
    shotOptions: {
      videoModel: 'doubao-seedance-2.0-all-in-one',
      duration: 5,
      ratio: '16:9',
      resolution: '720p',
    },
    shotAssets: done
      ? [
          {
            id: 'asset-' + id,
            videoUrl: '/synthetic.mp4',
            coverUrl: '/cover.svg',
            duration: 5,
            isCurrent: true,
          },
        ]
      : [],
  })
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path === '/api/generations/videos/batch') {
      submissions++
      return route.fulfill({ json: { count: 2, jobs: [{ id: 'job-one' }, { id: 'job-two' }] } })
    }
    if (path === '/api/generations/status')
      return route.fulfill({
        json: route
          .request()
          .postDataJSON()
          .ids.map((id: string) => ({
            id,
            status: id === 'job-one' || secondDone ? 'succeeded' : 'running',
            phase: 'platform_queued',
            result: { videoUrl: '/synthetic.mp4' },
          })),
      })
    if (path.endsWith('/generations/active'))
      return route.fulfill({
        json: secondDone
          ? []
          : [
              {
                id: 'job-two',
                kind: 'video',
                storyboardLineId: 'two',
                createdAt: new Date().toISOString(),
              },
            ],
      })
    if (path.includes('/storyboard-lines/'))
      return route.fulfill({ json: line(path.split('/').at(-1)!, true) })
    if (path === '/api/generations/observed') return route.fulfill({ json: { observed: 1 } })
    return route.fulfill({ json: [] })
  })
  await page.route('**/cover.svg', (route) =>
    route.fulfill({
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" />',
    }),
  )
  await page.route('**/progress-fixture', (route) =>
    route.fulfill({ contentType: 'text/html', body: '<div id="fixture"></div>' }),
  )
  async function mount(restoring: boolean) {
    await page.goto('/progress-fixture')
    await page.evaluate(
      async ({ restoring, lines }) => {
        const load = (path: string) => import(/* @vite-ignore */ path)
        const { createApp } = await load('/node_modules/.vite/deps/vue.js')
        const { createPinia } = await load('/node_modules/.vite/deps/pinia.js')
        const { useProjectStore } = await load('/src/stores/project.ts')
        const api = await load('/src/api/domain.ts')
        const { default: component } = await load('/src/components/ScriptEditor.vue')
        const pinia = createPinia(),
          store = useProjectStore(pinia)
        store.activeTaskId = 'video-fixture'
        store.activeStoryboardType = 'general_random'
        // Use the production API mapper for persisted assets on reload.
        store.lines = restoring
          ? [
              await api.fetchStoryboardLine('video-fixture', 'one'),
              {
                ...lines[1],
                shot: { status: 'none', assets: [] },
                scene: { status: 'none' },
                voice: { status: 'none' },
              },
            ]
          : lines.map((item) => ({
              ...item,
              shot: { status: 'none', assets: [] },
              scene: { status: 'none' },
              voice: { status: 'none' },
            }))
        createApp(component).use(pinia).mount('#fixture')
        if (restoring) void store.resumeActiveGenerations('video-fixture')
        else void store._generateRandomShotsBatch('video-fixture', store.lines)
      },
      { restoring, lines: [line('one', false), line('two', false)] },
    )
  }
  await mount(false)
  const rows = page.locator('.script-line')
  await expect(rows.nth(0).locator('.thumb-loading')).toHaveCount(0)
  await expect(rows.nth(0).locator('.shot-thumb img')).toBeVisible()
  await expect(rows.nth(1)).toContainText('平台排队中')
  await expect(page.locator('.generation-progress')).toContainText('视频已完成 1/2')
  await mount(true)
  await expect(rows.nth(1)).toContainText('平台排队中')
  expect(submissions).toBe(1)
  secondDone = true
  await expect(page.locator('.generation-progress')).toContainText('视频已完成 2/2')
  await expect(page.locator('.thumb-loading')).toHaveCount(0)
  expect(submissions).toBe(1)
})
