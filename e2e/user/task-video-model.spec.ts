import { expect, test } from '@playwright/test'
import videoCatalog from '../../backend/app/data/all_in_one_video_models_20261015.json' with { type: 'json' }

for (const kind of ['ass', 'general', 'general_random']) {
  for (const target of ['minimax-h3-all-in-one', 'gemini-omni-1.1-flash-preview-all-in-one']) {
    test(`${kind}: ${target} picker applies all lines and survives reload`, async ({ page }) => {
      let model = 'doubao-seedance-2.0-all-in-one'
      let saves = 0
      const preferences: Record<string, unknown> = {}
      const entries = videoCatalog.map((row) => ({ ...row, id: row.code }))
      const targetName = entries.find((item) => item.id === target)!.name
      await page.route('**/api/**', async (route) => {
        const path = new URL(route.request().url()).pathname
        if (!path.startsWith('/api/')) return route.continue()
        if (path.includes('/generation-preferences')) {
          if (route.request().method() === 'PUT')
            preferences[path.split('/').pop()!] = route.request().postDataJSON()
          return route.fulfill({ json: preferences })
        }
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
              modelName: entries.find((item) => item.id === body.model)?.name,
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
      const creators = ['ASS 视频', '定制通用分镜', '随机通用分镜']
      const positions = await Promise.all(
        creators.map((name) => page.getByRole('button', { name, exact: true }).boundingBox()),
      )
      expect(positions[0]!.y).toBeGreaterThan((await picker.boundingBox())!.y)
      expect(positions[1]!.y).toBe(positions[0]!.y)
      expect(positions[2]!.y).toBe(positions[0]!.y)
      await picker.click()
      await expect(page.getByRole('dialog', { name: '修改子项目视频模型' })).toBeVisible()
      await page.getByLabel('目标视频模型').click()
      await expect(page.locator('[data-model-option]')).toHaveCount(12)
      await expect(page.getByRole('button', { name: 'Veo 3.1', exact: true })).toHaveCount(1)
      await page
        .getByRole('button', {
          name: targetName,
          exact: true,
        })
        .click()
      await expect(page.getByText('第 1 镜：清晰度 480P → 720P')).toBeVisible()
      await page.getByRole('button', { name: '应用到全部分镜' }).click()
      await expect(picker).toContainText(targetName)
      expect(saves).toBe(1)
      await mount()
      await expect(page.getByRole('button', { name: `视频模型：${targetName}` })).toBeVisible()
      await page.evaluate(() => {
        const store = (
          window as unknown as { modelStore: { lines: Array<{ shot: { status: string } }> } }
        ).modelStore
        store.lines[0].shot.status = 'generating'
      })
      await expect(page.getByRole('button', { name: /视频模型：/ })).toBeDisabled()
    })
  }
}
