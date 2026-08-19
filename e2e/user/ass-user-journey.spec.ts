import { expect, test } from '@playwright/test'

test('user generates an editable storyboard from ASS', async ({ page }) => {
  await page.route('**/api/auth/refresh', (route) =>
    route.fulfill({ status: 401, contentType: 'application/json', body: '{}' }),
  )
  await page.route('**/api/auth/login', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        accessToken: 'test-token',
        user: {
          id: 'user-e2e',
          username: 'admin',
          displayName: '管理员',
          role: 'admin',
          isSuperAdmin: true,
          permissions: [],
          mustChangePassword: false,
        },
      }),
    }),
  )
  await page.route('**/api/account/balance*', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        available: true,
        balance: '287.391936',
        balanceDisplay: '287.39',
        currency: 'credits',
        updatedAt: '2026-08-07T00:00:00Z',
      }),
    }),
  )
  await page.route('**/api/model-options', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        imageModels: [{ code: 'gpt-image-2', name: 'Img2' }],
        videoModels: [{ code: 'doubao-seedance-2.0', name: 'SD2.0' }],
      }),
    }),
  )
  // 通用分镜选项（需求 7 起由后端组装，e2e 全 mock 环境按种子口径补齐）
  await page.route('**/api/storyboards/general/options', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        genres: [
          {
            value: '流行歌曲',
            label: '流行歌曲',
            children: [
              {
                value: '爱情消极',
                label: '爱情消极',
                children: [{ value: '失恋', label: '失恋' }],
              },
            ],
          },
          { value: '戏曲', label: '戏曲' },
        ],
        seasons: ['春', '夏', '秋', '冬', '通用'],
        ageGroups: ['少儿', '青少年', '青年', '中年', '老年'],
        visualStyles: ['电影写实', '动漫', '国风', '复古', '赛博朋克'],
        ratios: ['16:9', '9:16', '4:3', '1:1'],
      }),
    }),
  )
  await page.route('**/api/projects', async (route) => {
    if (route.request().method() === 'GET')
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify([{ id: 'project-e2e', name: 'E2E 项目', tasks: [] }]),
      })
    else await route.fallback()
  })
  await page.route('**/api/digital-humans', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'dh-luoli',
          name: '洛璃',
          style: '国风',
          avatar: 'https://tos.test/luoli.png',
          description: '系统角色',
          scope: 'system',
          readOnly: true,
        },
      ]),
    }),
  )
  await page.route('**/api/digital-human-styles', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify([
        { id: 'style-system-1', name: '国风', scope: 'system', readOnly: true },
      ]),
    }),
  )
  await page.route('**/api/storyboards/ass', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        taskId: 'task-e2e',
        title: '10012204',
        status: 'parsed',
        cast: ['dh-luoli'],
        lines: [
          {
            lyrics: '自动化测试歌词',
            start: 1,
            end: 5,
            id: 'line-e2e',
            shotType: 'empty',
            plannedDuration: 4,
            scenePrompt: '',
            shotPrompt: '',
            digitalHumanIds: [],
            generationStatus: 'pending',
            shotOptions: {
              resolution: '720p',
              duration: 4,
              ratio: '16:9',
              imageModel: 'gpt-image-2',
              videoModel: 'doubao-seedance-2.0',
              segmentType: 'lyric',
              timelineLabel: '自动化测试歌词',
              outlineStatus: 'pending',
            },
          },
        ],
        meta: { encoding: 'utf-8', dialogues: 1, segments: 1 },
      }),
    })
  })
  // 大纲端点已异步化：POST 受理返回 202，进度经 SSE 推送，终态后前端重新拉取任务全量
  await page.route('**/api/tasks/task-e2e/storyboard-outline/regenerate', (route) =>
    route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        taskId: 'task-e2e',
        status: 'outlining',
        progress: { phase: 'planning', segmentsDone: 0, segmentsTotal: 0 },
      }),
    }),
  )
  await page.route('**/api/tasks/task-e2e/storyboard-outline/events', (route) =>
    route.fulfill({
      contentType: 'text/event-stream',
      body: `data: ${JSON.stringify({ type: 'outline', taskId: 'task-e2e', status: 'generating', progress: {} })}\n\n`,
    }),
  )
  // 注意尾部的 *：fetchSongScript 会带 ?history=0 查询串，不带 * 的 glob 匹配不到会穿透到真实后端
  await page.route('**/api/tasks/task-e2e*', (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'task-e2e',
        title: '10012204',
        status: 'generating',
        storyboardType: 'ass',
        cast: ['dh-luoli'],
        storyboardConfig: {
          storyBible: {
            version: '1',
            logline: '测试大纲',
            characterPolicy: '',
            failedSegments: [],
            shots: [{ index: 0, stage: '场景一', shotType: 'character', outlineStatus: 'ready' }],
          },
        },
        lines: [
          {
            id: 'line-e2e',
            lyrics: '自动化测试歌词',
            start: 1,
            end: 5,
            shotType: 'character',
            plannedDuration: 4,
            scenePrompt: '',
            shotPrompt: '',
            digitalHumanIds: ['dh-luoli'],
            generationStatus: 'pending',
            generationAttempt: 0,
            shotOptions: {
              resolution: '720p',
              duration: 4,
              ratio: '16:9',
              imageModel: 'gpt-image-2',
              videoModel: 'doubao-seedance-2.0',
              segmentType: 'lyric',
              timelineLabel: '自动化测试歌词',
              outlineStatus: 'ready',
            },
          },
        ],
      }),
    })
  })
  await page.route('**/api/tasks/task-e2e/storyboard-lines/line-e2e/generate', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'line-e2e',
        scenePrompt: '清晨的房间',
        shotPrompt: '镜头缓慢推进',
        digitalHumanIds: ['dh-luoli'],
        generationStatus: 'succeeded',
        generationAttempt: 1,
      }),
    }),
  )

  await page.goto('/')
  await page.getByLabel('用户名').fill('admin')
  await page.getByLabel('密码').fill('123456')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByRole('heading', { name: '视频编辑器' })).toBeVisible()
  await expect(page.locator('.balance-value')).toHaveText('287.39')
  await expect(page.getByRole('link', { name: '返回镜序 MV 工作台' })).toBeVisible()
  await expect(page.getByRole('button', { name: /287\.39/ })).toBeVisible()
  await page.getByRole('button', { name: /管理员/ }).click()
  await expect(page.getByRole('menuitem', { name: '管理后台' })).toBeVisible()
  await page.getByRole('button', { name: /管理员/ }).click()
  await page.getByRole('button', { name: 'ASS 视频' }).first().click()
  await page.locator('input[type="file"][accept=".ass"]').setInputFiles({
    name: '10012204-journey.ass',
    mimeType: 'text/plain',
    buffer: Buffer.from('[Script Info]\n[V4+ Styles]\n[Events]\n'),
  })
  await expect(page.locator('.song-input')).toBeDisabled()
  await expect(page.locator('.song-input')).toHaveValue('10012204')
  await expect(page.getByLabel('画幅 *')).toHaveValue('16:9')
  await expect(page.getByLabel('清晰度 *')).toHaveValue('480p')
  await expect(page.getByLabel('视频模型')).toHaveValue('doubao-seedance-2.0')
  await expect(page.getByLabel('视频模型')).toBeEnabled()
  await expect(page.getByLabel('图片模型 *')).toHaveValue('gpt-image-2')
  await expect(page.getByLabel('图片模型 *')).toBeDisabled()
  await page.getByRole('button', { name: '生成', exact: true }).click()

  await expect(page.getByText('自动化测试歌词').first()).toBeVisible()
  await expect(page.getByText('镜头缓慢推进').first()).toBeVisible()
  await expect(page.getByText('10012204').last()).toBeVisible()

  await page
    .locator('.script-editor .header-actions')
    .getByRole('button', { name: '通用 MV 视频', exact: true })
    .click()
  const general = page.locator('.modal').filter({ hasText: '通用 MV 视频' })
  await expect(general.getByLabel('清晰度 *')).toHaveValue('720p')
  const scaleInputs = general.locator('input[type="number"]')
  await expect(scaleInputs.nth(0)).toHaveValue('4')
  await expect(scaleInputs.nth(1)).toHaveValue('17')
  await expect(scaleInputs.nth(2)).toHaveValue('210')
  await expect(general.getByLabel('视频模型')).toHaveValue('doubao-seedance-2.0')
  await expect(general.getByLabel('视频模型')).toBeEnabled()
  await expect(general.getByLabel('图片模型 *')).toHaveValue('gpt-image-2')
  await expect(general.getByLabel('图片模型 *')).toBeDisabled()
})
