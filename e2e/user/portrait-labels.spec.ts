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

test('single portraits remain complete in wide, square and vertical containers', async ({
  page,
}) => {
  await page.route('**/portrait-fixture', (route) =>
    route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' }),
  )
  await page.goto('/portrait-fixture')
  await page.evaluate(async () => {
    const load = (path: string) => import(/* @vite-ignore */ path)
    const { createApp, h } = await load('/node_modules/.vite/deps/vue.js')
    const { default: Portrait } = await load('/src/components/CharacterPortrait.vue')
    const src =
      'data:image/svg+xml,' +
      encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="150"><rect width="100" height="150" fill="green"/><circle cx="50" cy="75" r="40" fill="white"/></svg>',
      )
    createApp({
      render: () =>
        [
          [124, 68],
          [64, 64],
          [124, 186],
        ].map(([width, height]) =>
          h('div', { style: { width: width + 'px', height: height + 'px' } }, [
            h(Portrait, { src, alt: '完整人物' }),
          ]),
        ),
    }).mount('#app')
  })
  const images = page.locator('.character-portrait img')
  await expect(images).toHaveCount(3)
  for (const image of await images.all()) {
    await expect(image).toHaveJSProperty('naturalHeight', 150)
    await expect(image).toHaveCSS('object-fit', 'contain')
  }
})

for (const entry of ['GeneralStoryboardModal', 'MagicScriptModal']) {
  test(`${entry} displays complete vertical portraits in the character picker`, async ({
    page,
  }) => {
    await page.route(/^https?:\/\/[^/]+\/api\//, (route) => route.fulfill({ json: [] }))
    await page.route('**/portrait-fixture', (route) =>
      route.fulfill({ contentType: 'text/html', body: '<div id="app"></div>' }),
    )
    await page.goto('/portrait-fixture')
    await page.evaluate(async (entry) => {
      const load = (path: string) => import(/* @vite-ignore */ path)
      const { createApp, h } = await load('/node_modules/.vite/deps/vue.js')
      const { createPinia } = await load('/node_modules/.vite/deps/pinia.js')
      const { default: Modal } = await load(`/src/components/${entry}.vue`)
      const { useProjectStore } = await load('/src/stores/project.ts')
      const pinia = createPinia()
      const store = useProjectStore(pinia)
      store.digitalHumans = Array.from({ length: 28 }, (_, i) => ({
        id: `portrait-${i}`,
        name: `人物${i}`,
        style: '男',
        description: '',
        avatar:
          'data:image/svg+xml,' +
          encodeURIComponent(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="150"><rect width="100" height="150" fill="green"/></svg>',
          ),
      }))
      store.generalStoryboardOptions = {
        genres: [{ value: 'pop', label: '流行歌曲' }],
        seasons: ['秋'],
        ageGroups: ['青年'],
        visualStyles: ['电影写实'],
        ratios: ['16:9'],
      }
      store.generalStoryboardOpen = true
      store.magicOpen = true
      createApp({ render: () => h(Modal) })
        .use(pinia)
        .mount('#app')
    }, entry)
    const portraits = page.locator('.character-portrait')
    await expect(portraits).toHaveCount(28)
    const portrait = portraits.first()
    await expect(portrait.locator('img')).toHaveCSS('object-fit', 'contain')
    const box = await portrait.boundingBox()
    expect(box!.height / box!.width).toBeCloseTo(1.5, 1)
    await portrait.scrollIntoViewIfNeeded()
    await page.screenshot({ path: `output/playwright/${entry}-complete-portraits.png` })
  })
}
