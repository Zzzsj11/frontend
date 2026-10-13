import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

let mediaDir = ''
test.beforeAll(() => {
  mediaDir = mkdtempSync(join(tmpdir(), 'mv-fullscreen-'))
  for (const [name, color] of [
    ['one', 'blue'],
    ['two', 'red'],
  ]) {
    execFileSync(
      process.env.FFMPEG_BIN || 'ffmpeg',
      [
        '-y',
        '-f',
        'lavfi',
        '-i',
        `color=c=${color}:s=320x180:r=25:d=1.2`,
        '-c:v',
        'libx264',
        '-threads',
        '1',
        '-pix_fmt',
        'yuv420p',
        '-movflags',
        '+faststart',
        join(mediaDir, `${name}.mp4`),
      ],
      { stdio: 'pipe' },
    )
  }
})
test.afterAll(() => {
  if (mediaDir) rmSync(mediaDir, { recursive: true, force: true })
})

test('fullscreen plays both real clips, keeps the timeline and returns to the prior mode', async ({
  page,
}) => {
  await page.route('**/media/*.mp4', (route) =>
    route.fulfill({
      path: join(mediaDir, new URL(route.request().url()).pathname.split('/').pop()!),
      contentType: 'video/mp4',
    }),
  )
  await page.route('**/fullscreen-fixture', (route) =>
    route.fulfill({
      contentType: 'text/html',
      body: '<html><body><div id="fixture"></div></body></html>',
    }),
  )
  await page.goto('/fullscreen-fixture')
  await page.evaluate(async () => {
    const load = (path: string) => import(/* @vite-ignore */ path)
    const { createApp } = await load('/node_modules/.vite/deps/vue.js')
    const { createPinia } = await load('/node_modules/.vite/deps/pinia.js')
    const { useProjectStore } = await load('/src/stores/project.ts')
    const { default: component } = await load('/src/components/PlayerPanel.vue')
    await load('/src/style.css')
    const pinia = createPinia()
    const store = useProjectStore(pinia)
    store.lines = ['one', 'two'].map((id) => ({
      id,
      digitalHumanIds: [],
      lyrics: id,
      voice: { status: 'none' },
      scene: { status: 'none' },
      shot: {
        status: 'done',
        currentAssetId: id,
        assets: [{ id, videoUrl: `/media/${id}.mp4`, duration: 1.2 }],
      },
    }))
    store.selectedLineId = 'one'
    store.currentTime = 0.3
    store.playMode.single = true
    createApp(component).use(pinia).mount('#fixture')
    ;(window as unknown as { playerStore: unknown }).playerStore = store
  })
  await page.locator('.controls button[title="全屏"]').click()
  await expect(page.locator('.fs-controls')).toBeVisible()
  await page.mouse.move(20, 20)
  await expect(page.locator('.fs-controls')).toBeHidden({ timeout: 4500 })
  await page.locator('.fs-control-zone').hover()
  await expect(page.locator('.fs-controls')).toBeVisible()
  await expect(page.locator('.fs-controls button[title="退出全屏"] svg path')).toHaveAttribute(
    'd',
    'M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z',
  )
  await expect(page.locator('.fs-time')).toHaveText('00:00 / 00:02')
  expect(
    await page.evaluate(
      () => (window as unknown as { playerStore: { currentTime: number } }).playerStore.currentTime,
    ),
  ).toBe(0.3)
  const bar = await page.locator('.fs-progress').boundingBox()
  await page.mouse.click(bar!.x + bar!.width * 0.75, bar!.y + bar!.height / 2)
  await expect(page.locator('.preview video')).toHaveAttribute('src', '/media/two.mp4')
  expect(
    await page.evaluate(
      () => (window as unknown as { playerStore: { currentTime: number } }).playerStore.currentTime,
    ),
  ).toBeCloseTo(1.8, 1)
  await page.evaluate(() =>
    (window as unknown as { playerStore: { seek: (time: number) => void } }).playerStore.seek(0.3),
  )
  await expect(page.locator('.preview video')).toHaveAttribute('src', '/media/one.mp4')
  await page.locator('.fs-controls button[title="播放"]').click()
  await expect(page.locator('.preview video')).toHaveAttribute('src', '/media/two.mp4', {
    timeout: 10000,
  })
  expect(await page.evaluate(() => Boolean(document.fullscreenElement))).toBe(true)
  await expect
    .poll(
      () =>
        page.evaluate(
          () =>
            (window as unknown as { playerStore: { isPlaying: boolean } }).playerStore.isPlaying,
        ),
      { timeout: 10000 },
    )
    .toBe(false)
  expect(
    await page.evaluate(
      () => (window as unknown as { playerStore: { currentTime: number } }).playerStore.currentTime,
    ),
  ).toBeCloseTo(2.4)
  await page.locator('.fs-control-zone').hover()
  await page.locator('.fs-controls button[title="退出全屏"]').click()
  await expect(page.locator('.fs-controls')).toHaveCount(0)
  expect(
    await page.evaluate(
      () =>
        (window as unknown as { playerStore: { playMode: { single: boolean } } }).playerStore
          .playMode.single,
    ),
  ).toBe(true)
  // 循环设置在全屏仍作用于整条时间轴，而不是最后一个片段。
  await page.evaluate(() => {
    const store = (
      window as unknown as {
        playerStore: { playMode: { loop: boolean }; seek: (time: number) => void }
      }
    ).playerStore
    store.playMode.loop = true
    store.seek(2.1)
  })
  await expect(page.locator('.preview video')).toHaveAttribute('src', '/media/two.mp4')
  await page.locator('.controls button[title="全屏"]').click()
  await page.locator('.fs-controls button[title="播放"]').click()
  await expect(page.locator('.preview video')).toHaveAttribute('src', '/media/one.mp4', {
    timeout: 10000,
  })
  expect(
    await page.evaluate(
      () => (window as unknown as { playerStore: { isPlaying: boolean } }).playerStore.isPlaying,
    ),
  ).toBe(true)
  await page.evaluate(() =>
    (window as unknown as { playerStore: { pause: () => void } }).playerStore.pause(),
  )
  await page.locator('.fs-control-zone').hover()
  await page.locator('.fs-controls button[title="退出全屏"]').click()
})
