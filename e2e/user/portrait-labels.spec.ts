import { expect, test } from '@playwright/test'

test('portrait preview exposes label edit only for editable assets', async ({ page }) => {
  await page.route('**/portrait-fixture', (route) =>
    route.fulfill({ contentType: 'text/html', body: '<div id="app"></div><p id="edited"></p>' }),
  )
  await page.goto('/portrait-fixture')
  await page.evaluate(async () => {
    const load = (path: string) => import(/* @vite-ignore */ path)
    const { createApp } = await load('/node_modules/.vite/deps/vue.js')
    const { default: Preview } = await load('/src/components/ImagePreviewOverlay.vue')
    const { openImageGallery } = await load('/src/composables/useImagePreview.ts')
    createApp(Preview).mount('#app')
    openImageGallery([
      {
        src: 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7',
        alt: '测试1',
        editLabel: () => {
          document.querySelector('#edited')!.textContent = '已打开名称编辑'
        },
      },
    ])
  })
  await page.getByRole('button', { name: '修改名称' }).click()
  await expect(page.locator('#edited')).toHaveText('已打开名称编辑')
  await expect(page.getByRole('dialog', { name: '图片大图预览' })).toHaveCount(0)
})

test('asset labels stay above portraits in a multi-column grid', async ({ page }) => {
  await page.route('**/portrait-fixture', (route) =>
    route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' }),
  )
  await page.goto('/portrait-fixture')
  await page.evaluate(async () => {
    const load = (path: string) => import(/* @vite-ignore */ path)
    const { createApp, h } = await load('/node_modules/.vite/deps/vue.js')
    const { createPinia } = await load('/node_modules/.vite/deps/pinia.js')
    const { default: Library } = await load('/src/components/AssetLibrary.vue')
    const { default: Preview } = await load('/src/components/ImagePreviewOverlay.vue')
    const { useProjectStore } = await load('/src/stores/project.ts')
    const pinia = createPinia()
    const store = useProjectStore(pinia)
    store.digitalHumans = [
      '男14',
      '男13',
      '老男1',
      ...Array.from({ length: 32 }, (_, i) => `系统人物${i}`),
    ].map((name, index) => ({
      id: `fixture-${index}`,
      name,
      style: '男',
      description: '',
      readOnly: false,
      avatar: 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7',
    }))
    store.libraryOpen = true
    createApp({ render: () => [h(Library), h(Preview)] })
      .use(pinia)
      .mount('#app')
  })
  await expect(page.locator('.dh-card')).toHaveCount(35)
  for (const name of ['男14', '男13', '老男1']) {
    await expect(page.locator('.dh-name-row strong', { hasText: name })).toBeVisible()
  }
  const positions = await page.locator('.dh-card').evaluateAll((cards) =>
    cards.map((card) => ({
      x: card.getBoundingClientRect().x,
      y: card.getBoundingClientRect().y,
      labelY: card.querySelector('.dh-info')!.getBoundingClientRect().y,
      portraitY: card.querySelector('.dh-portrait')!.getBoundingClientRect().y,
      portraitWidth: card.querySelector('.dh-portrait')!.getBoundingClientRect().width,
      portraitHeight: card.querySelector('.dh-portrait')!.getBoundingClientRect().height,
    })),
  )
  expect(
    positions.every((position) => position.portraitHeight / position.portraitWidth > 1.45),
  ).toBeTruthy()
  expect(positions[1].x).toBeGreaterThan(positions[0].x)
  expect(positions[1].y).toBe(positions[0].y)
  expect(positions.every((position) => position.labelY < position.portraitY)).toBeTruthy()
  await page.getByRole('button', { name: '查看男14大图', exact: true }).click()
  await page.getByRole('button', { name: '修改名称', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '编辑数字人 · 男14' })).toBeVisible()
})
