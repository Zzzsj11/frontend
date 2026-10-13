import { expect, test } from '@playwright/test'

test('ASS, custom and random modals close from outside on mouse and touch', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path === '/api/model-options') return route.fulfill({ json: [] })
    if (path === '/api/storyboards/general/options')
      return route.fulfill({
        json: {
          genres: [{ value: 'pop', label: '流行歌曲' }],
          seasons: ['春'],
          ageGroups: ['青年'],
          visualStyles: ['电影写实'],
          ratios: ['16:9'],
        },
      })
    return route.fulfill({ json: [] })
  })
  await page.route('**/modal-fixture', (route) =>
    route.fulfill({
      contentType: 'text/html',
      body: '<html><body><div id="fixture"></div></body></html>',
    }),
  )
  await page.goto('/modal-fixture')
  await page.evaluate(async () => {
    const load = (path: string) => import(/* @vite-ignore */ path)
    const { createApp } = await load('/node_modules/.vite/deps/vue.js')
    const { createPinia } = await load('/node_modules/.vite/deps/pinia.js')
    const { useProjectStore } = await load('/src/stores/project.ts')
    const { default: component } = await load('/src/components/ScriptEditor.vue')
    await load('/src/style.css')
    const pinia = createPinia()
    useProjectStore(pinia)
    createApp(component).use(pinia).mount('#fixture')
  })
  for (const name of ['ASS 视频', '定制通用分镜', '随机通用分镜']) {
    await page.getByRole('button', { name, exact: true }).click()
    const dialog = page.getByRole('dialog', { name, exact: true })
    await expect(dialog).toBeVisible()
    await dialog.locator('h3').click()
    await expect(dialog).toBeVisible()
    await page.mouse.click(8, 8)
    await expect(dialog).toHaveCount(0)
    await page.getByRole('button', { name, exact: true }).click()
    await expect(dialog).toBeVisible()
    await page
      .locator('.modal-mask')
      .dispatchEvent('pointerdown', { button: 0, pointerType: 'touch', isPrimary: true })
    await expect(dialog).toHaveCount(0)
  }
})
