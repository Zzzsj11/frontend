import { expect, test } from '@playwright/test'

const taskId = 'ass-export-test'
const base = {
  taskId,
  kind: 'video',
  jobId: 'job-final',
  totalAssets: 3,
  processedAssets: 0,
  totalBytes: 0,
  processedBytes: 0,
  createdAt: '2026-10-09T00:00:00Z',
  updatedAt: '2026-10-09T00:00:00Z',
}

test('MV export shows progress, survives reload, retries and keeps ZIP separate', async ({
  page,
}) => {
  let posts = 0
  let item = {
    ...base,
    id: 'final-1',
    status: 'running',
    progress: 42,
    stage: '合成画面与字幕 · 已处理 20 秒',
    error: '',
    archiveUrl: '',
  }
  const zip = {
    ...base,
    kind: 'materials',
    id: 'zip-1',
    status: 'ready',
    progress: 100,
    stage: '导出完成',
    archiveUrl: '/assets.zip',
  }
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path.endsWith('/video-exports')) {
      posts += 1
      return route.fulfill({ json: item, status: 202 })
    }
    if (path.endsWith('/material-exports')) return route.fulfill({ json: [item, zip] })
    // 模拟实时连接断开，必须通过 GET 兜底持续更新。
    if (path.endsWith('/events')) return route.abort()
    if (path === '/api/material-exports/final-1') return route.fulfill({ json: item })
    return route.fulfill({ json: {} })
  })
  await page.route('**/export-fixture', (route) =>
    route.fulfill({
      contentType: 'text/html',
      body: '<html><body><div id="fixture"></div></body></html>',
    }),
  )
  async function mount(restore = false) {
    await page.goto('/export-fixture')
    await page.evaluate(
      async ({ taskId, restore }) => {
        const load = (path: string) => import(/* @vite-ignore */ path)
        const { createApp } = await load('/node_modules/.vite/deps/vue.js')
        const { createPinia } = await load('/node_modules/.vite/deps/pinia.js')
        const { useProjectStore } = await load('/src/stores/project.ts')
        const { default: component } = await load('/src/components/ExportActions.vue')
        await load('/src/style.css')
        const pinia = createPinia()
        const store = useProjectStore(pinia)
        store.activeTaskId = taskId
        store.activeStoryboardType = 'ass'
        store.projectAudio = { filename: '歌曲.mp3', duration: 30 }
        store.lines = [
          {
            id: 'line',
            shot: {
              assets: [{ id: 'asset', videoUrl: 'https://test.tos/video.mp4' }],
              currentAssetId: 'asset',
            },
          },
        ]
        createApp(component).use(pinia).mount('#fixture')
        if (restore) await store.restoreMaterialExports(taskId)
      },
      { taskId, restore },
    )
  }
  await mount()
  const merge = page.getByRole('button', { name: '合并并导出', exact: true })
  const zipButton = page.getByRole('button', { name: '导出素材', exact: true })
  expect((await merge.boundingBox())!.x).toBeLessThan((await zipButton.boundingBox())!.x)
  await merge.click()
  await expect(page.getByRole('progressbar', { name: '合并并导出完成百分比' })).toHaveAttribute(
    'value',
    '42',
  )
  await expect(page.getByRole('button', { name: '合并并导出中 42%' })).toBeDisabled()
  expect(posts).toBe(1)
  await page.screenshot({ path: 'output/playwright/mv-export-progress.png' })
  await mount(true)
  await expect(page.getByRole('progressbar', { name: '合并并导出完成百分比' })).toHaveAttribute(
    'value',
    '42',
  )
  await expect(page.getByRole('link', { name: '下载素材' })).toBeVisible()
  item = {
    ...item,
    status: 'failed',
    stage: '合并导出失败',
    error: '第 1 镜视频过短，请补齐后重试',
    updatedAt: '2026-10-09T00:01:00Z',
  }
  await expect(page.getByRole('alert')).toContainText('第 1 镜视频过短', { timeout: 15000 })
  item = {
    ...item,
    status: 'ready',
    progress: 100,
    stage: '合并导出完成',
    error: '',
    archiveUrl: '/final.mp4',
    updatedAt: '2026-10-09T00:02:00Z',
  }
  await page.getByRole('button', { name: '合并并导出重试' }).click()
  await expect(page.getByRole('link', { name: '下载成片' })).toHaveAttribute('href', '/final.mp4')
  await expect(page.getByRole('link', { name: '下载素材' })).toBeVisible()
  expect(posts).toBe(2)
})
