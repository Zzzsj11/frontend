import { expect, test } from '@playwright/test'

test('user generates an editable storyboard from ASS', async ({ page }) => {
  await page.route('**/api/auth/refresh', (route) => route.fulfill({ status: 401, contentType: 'application/json', body: '{}' }))
  await page.route('**/api/auth/login', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ accessToken: 'test-token', user: { id: 'user-e2e', username: 'admin', displayName: '管理员', role: 'admin', mustChangePassword: true } }) }))
  await page.route('**/api/projects', async (route) => {
    if (route.request().method() === 'GET') await route.fulfill({ contentType: 'application/json', body: JSON.stringify([{ id: 'project-e2e', name: 'E2E 项目', tasks: [] }]) })
    else await route.fallback()
  })
  await page.route('**/api/digital-humans', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify([{ id:'dh-luoli',name:'洛璃',style:'国风',avatar:'https://tos.test/luoli.png',description:'系统角色',scope:'system',readOnly:true }]) }))
  await page.route('**/api/digital-human-styles', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify([{ id:'style-system-1',name:'国风',scope:'system',readOnly:true }]) }))
  await page.route('**/api/storyboards/ass', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        taskId: 'task-e2e',
        title: 'E2E storyboard',
        cast: ['dh-luoli'],
        lines: [
          {
            lyrics: '自动化测试歌词',
            start: 1,
            end: 5,
            id: 'line-e2e',
            scenePrompt: '',
            shotPrompt: '',
            digitalHumanIds: ['dh-luoli'],
            generationStatus: 'pending',
          },
        ],
        meta: { encoding: 'utf-8', dialogues: 1, segments: 1 },
      }),
    })
  })
  await page.route('**/api/tasks/task-e2e/storyboard-lines/line-e2e/generate', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ id:'line-e2e', scenePrompt:'清晨的房间', shotPrompt:'镜头缓慢推进', digitalHumanIds:['dh-luoli'], generationStatus:'succeeded', generationAttempt:1 }),
  }))

  await page.goto('/')
  await page.getByLabel('用户名').fill('admin')
  await page.getByLabel('密码').fill('123456')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByRole('heading', { name: '分镜编辑器' })).toBeVisible()
  await page.getByRole('button', { name: 'ASS 分镜' }).first().click()
  await page.locator('input[type="file"][accept=".ass"]').setInputFiles({
    name: '10012204-journey.ass',
    mimeType: 'text/plain',
    buffer: Buffer.from('[Script Info]\n[V4+ Styles]\n[Events]\n'),
  })
  await expect(page.getByPlaceholder('输入歌曲编号，如 SM-2026-0731')).toHaveValue('10012204')
  await page.getByRole('button', { name: '生成', exact: true }).click()

  await expect(page.getByText('自动化测试歌词').first()).toBeVisible()
  await expect(page.getByText('镜头缓慢推进').first()).toBeVisible()
  await expect(page.getByText('MV 分镜制作').last()).toBeVisible()
})
