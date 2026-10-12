import { expect, test } from '@playwright/test'

for (const kind of ['ass', 'general', 'general_random']) {
  test(`${kind}: model picker applies all lines and survives reload`, async ({ page }) => {
    let model = 'doubao-seedance-2.0'
    let saves = 0
    const entries = [
      { id: model, name: 'SD2.0（英和）', modality: 'video', capabilities: {} },
      {
        id: 'minimax-h3',
        name: 'H3（英和）',
        modality: 'video',
        capabilities: { resolutions: ['720p', '1080p'] },
      },
      { id: 'wan3.0-video', name: 'Wan3.0（英和）', modality: 'video', capabilities: {} },
      { id: 'veo-3.1', name: 'Veo', modality: 'video', capabilities: {} },
    ]
    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname
      if (!path.startsWith('/api/')) return route.continue()
      if (path.endsWith('/model-options')) return route.fulfill({ json: entries })
      if (path.endsWith('/video-model')) {
        const body = route.request().postDataJSON()
        if (body.apply) {
          model = body.model
          saves++
        }
        return route.fulfill({
          json: {
            taskId: 'model-task',
            model: body.model,
            modelName: 'H3（英和）',
            count: 2,
            adjustments: ['第 1 镜：清晰度 480P → 720P', '第 2 镜：清晰度 480P → 720P'],
            blockers: [],
            previewToken: 'preview-v1',
            applied: Boolean(body.apply),
            lines: ['one', 'two'].map((id) => ({
              id,
              shotOptions: {
                videoModel: body.model,
                resolution: '720p',
                ratio: '16:9',
                duration: 5,
              },
            })),
            task: {
              storyboardConfig: { video_model: model, videoModelDefaults: { videoModel: model } },
            },
          },
        })
      }
      return route.fulfill({ json: [] })
    })
    await page.route('**/model-fixture', (route) =>
      route.fulfill({
        contentType: 'text/html',
        body: '<html><body><div id="fixture"></div></body></html>',
      }),
    )
    async function mount() {
      await page.goto('/model-fixture')
      await page.evaluate(
        async ({ kind, model }) => {
          const load = (path: string) => import(/* @vite-ignore */ path)
          const { createApp } = await load('/node_modules/.vite/deps/vue.js')
          const { createPinia } = await load('/node_modules/.vite/deps/pinia.js')
          const { useProjectStore, DEFAULT_SHOT_OPTIONS } = await load('/src/stores/project.ts')
          const { default: component } = await load('/src/components/ScriptEditor.vue')
          await load('/src/style.css')
          const pinia = createPinia()
          const store = useProjectStore(pinia)
          store.activeTaskId = 'model-task'
          store.activeStoryboardType = kind
          store.activeStoryboardConfig = { video_model: model }
          store.lines = ['one', 'two'].map((id) => ({
            id,
            source: kind,
            lyrics: '歌词',
            scenePrompt: '场景',
            shotPrompt: '镜头',
            digitalHumanIds: [],
            voice: { status: 'none' },
            scene: { status: 'none' },
            shot: { status: 'none', assets: [] },
            generationStatus: 'succeeded',
            shotOptions: { ...DEFAULT_SHOT_OPTIONS, videoModel: model },
          }))
          createApp(component).use(pinia).mount('#fixture')
          ;(window as unknown as { modelStore: unknown }).modelStore = store
        },
        { kind, model },
      )
    }
    await mount()
    const picker = page.getByRole('button', { name: /视频模型：/ })
    const batch = page.getByRole('button', { name: /批量生成（2）/ })
    expect((await picker.boundingBox())!.x).toBeLessThan((await batch.boundingBox())!.x)
    await picker.click()
    await expect(page.getByRole('dialog', { name: '修改子项目视频模型' })).toBeVisible()
    await expect(page.getByLabel('目标视频模型').locator('option')).toHaveCount(3)
    await page.getByLabel('目标视频模型').selectOption('minimax-h3')
    await expect(page.getByText('第 1 镜：清晰度 480P → 720P')).toBeVisible()
    await page.getByRole('button', { name: '应用到全部分镜' }).click()
    await expect(picker).toHaveText(/H3（英和）/)
    expect(saves).toBe(1)
    await mount()
    await expect(page.getByRole('button', { name: /视频模型：H3/ })).toBeVisible()
    await page.evaluate(() => {
      const store = (
        window as unknown as { modelStore: { lines: Array<{ shot: { status: string } }> } }
      ).modelStore
      store.lines[0].shot.status = 'generating'
    })
    await expect(page.getByRole('button', { name: /视频模型：/ })).toBeDisabled()
  })
}
