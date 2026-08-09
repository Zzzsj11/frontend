import { expect, test } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'

test.skip(!process.env.REMOTE_FRONTEND_E2E, 'set REMOTE_FRONTEND_E2E=1 to test a deployed frontend')
test.setTimeout(5 * 60 * 1000)

const username = process.env.REMOTE_E2E_USERNAME || 'admin'
const password = process.env.REMOTE_E2E_PASSWORD || '123456'
const runId = process.env.REMOTE_E2E_RUN_ID || new Date().toISOString().replaceAll(/[:.]/g, '-')
const output = process.env.REMOTE_E2E_ARTIFACT_DIR || join(process.cwd(), 'test-artifacts/remote/runs', runId, 'screenshots')
const assFile = process.env.REMOTE_E2E_ASS_FILE || join(process.cwd(), 'test-artifacts/full-journey/inputs/10012204-full-e2e.ass')
mkdirSync(output, { recursive: true })

test('deployed frontend login, project and storyboard configuration journey', async ({ page }) => {
  let accessToken = ''
  let projectId = ''
  const projectName = `REMOTE-UI ${runId}`

  try {
    const loginResponse = page.waitForResponse((response) => response.url().includes('/api/auth/login') && response.request().method() === 'POST')
    await page.goto('/')
    await page.getByLabel('用户名').fill(username)
    await page.getByLabel('密码').fill(password)
    await page.getByRole('button', { name: '登录' }).click()
    const loginBody = await (await loginResponse).json()
    accessToken = loginBody.accessToken
    await expect(page.getByRole('heading', { name: '分镜编辑器' })).toBeVisible()
    await expect(page.locator('header').or(page.locator('.top-bar')).first()).toBeVisible()
    await page.screenshot({ path: join(output, '01-login.png'), fullPage: true })

    const projectResponse = page.waitForResponse((response) => response.url().endsWith('/api/projects') && response.request().method() === 'POST')
    await page.getByRole('button', { name: '创建歌曲项目' }).click()
    await page.getByPlaceholder('歌曲名称，回车创建').fill(projectName)
    await page.locator('.create-form').getByRole('button', { name: '创建' }).click()
    projectId = (await (await projectResponse).json()).id
    await expect(page.getByText(projectName, { exact: true })).toBeVisible()
    await page.screenshot({ path: join(output, '02-project-created.png'), fullPage: true })

    await page.locator('.script-editor .header-actions').getByRole('button', { name: 'ASS 分镜', exact: true }).click()
    const assDialog = page.locator('.modal').filter({ hasText: 'ASS 分镜' })
    await expect(assDialog).toBeVisible()
    await assDialog.locator('input[type="file"][accept=".ass"]').setInputFiles(assFile)
    const songCode = assDialog.locator('.song-input')
    await expect(songCode).toBeDisabled()
    await expect(songCode).toHaveValue('10012204')
    await expect(assDialog.getByText(/可不选/)).toBeVisible()
    await expect(assDialog.getByLabel('画幅')).toHaveValue('16:9')
    await expect(assDialog.getByLabel('清晰度')).toHaveValue('720p')
    await expect(assDialog.getByLabel('视频模型')).toBeDisabled()
    await expect(assDialog.getByLabel('图片模型')).toBeDisabled()
    await page.screenshot({ path: join(output, '03-ass-dialog.png'), fullPage: true })
    await page.reload()
    await expect(page.getByRole('heading', { name: '分镜编辑器' })).toBeVisible()
    await page.getByText(projectName, { exact: true }).click()

    await page.locator('.script-editor .header-actions').getByRole('button', { name: '通用分镜', exact: true }).click()
    const general = page.locator('.modal').filter({ hasText: '通用分镜' })
    await expect(general).toBeVisible()
    await general.getByLabel('画幅').selectOption('9:16')
    await expect(general.getByLabel('画幅')).toHaveValue('9:16')
    await expect(general.getByLabel('视频模型')).toBeDisabled()
    await expect(general.getByLabel('图片模型')).toBeDisabled()
    await page.screenshot({ path: join(output, '04-general-dialog.png'), fullPage: true })
    await expect(page.locator('[role="alertdialog"]')).toHaveCount(0)
    await page.screenshot({ path: join(output, '05-final-state.png'), fullPage: true })
  } finally {
    if (projectId && accessToken) {
      const response = await page.request.delete(`/api/projects/${projectId}`, { headers: { Authorization: `Bearer ${accessToken}` } })
      expect([200, 404]).toContain(response.status())
    }
  }
})
