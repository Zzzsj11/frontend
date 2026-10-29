import { selectDropdown, expectDropdownOptions } from '../select'
import { expect, test } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { agentTestHeaders, remoteCredentials, testRunId } from '../env'

test.skip(!process.env.REMOTE_FRONTEND_E2E, 'set REMOTE_FRONTEND_E2E=1 to test a deployed frontend')
test.setTimeout(5 * 60 * 1000)

const { username, password } = remoteCredentials()
const runId = testRunId()
const output =
  process.env.REMOTE_E2E_ARTIFACT_DIR ||
  join(process.cwd(), 'test-artifacts/remote/runs', runId, 'screenshots')
const assFile =
  process.env.REMOTE_E2E_ASS_FILE ||
  join(process.cwd(), 'test-artifacts/full-journey/inputs/10012204-full-e2e.ass')
mkdirSync(output, { recursive: true })

test('deployed frontend login, project and storyboard configuration journey', async ({ page }) => {
  await page.route('**/api/**', (route) =>
    route.continue({ headers: { ...route.request().headers(), ...agentTestHeaders(runId) } }),
  )
  let accessToken = ''
  let projectId = ''
  const projectName = `REMOTE-UI ${runId}`

  try {
    const loginResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/api/auth/login') && response.request().method() === 'POST',
    )
    await page.goto('/')
    await page.getByLabel('用户名').fill(username)
    await page.getByLabel('密码').fill(password)
    await page.getByRole('button', { name: '登录' }).click()
    const loginBody = await (await loginResponse).json()
    accessToken = loginBody.accessToken
    await expect(page.getByRole('heading', { name: '视频编辑器' })).toBeVisible()
    await expect(page.locator('.balance-pill.yinghe')).toHaveCount(0)
    await expect(page.locator('.app-header .balance-pill')).toHaveCount(1)
    await expect(page.locator('.balance-pill.all-in-one')).toContainText('All in one')
    await expect(page.locator('header').or(page.locator('.top-bar')).first()).toBeVisible()
    await page.screenshot({ path: join(output, '01-login.png'), fullPage: true })

    const projectResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/projects') && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: '创建歌曲项目' }).click()
    await page.getByPlaceholder('歌曲名称，回车创建').fill(projectName)
    await page.locator('.create-form').getByRole('button', { name: '创建' }).click()
    projectId = (await (await projectResponse).json()).id
    await expect(page.getByText(projectName, { exact: true })).toBeVisible()
    await page.screenshot({ path: join(output, '02-project-created.png'), fullPage: true })

    await page
      .locator('.script-editor .header-actions')
      .getByRole('button', { name: 'ASS 视频', exact: true })
      .click()
    const assDialog = page.locator('.modal').filter({ hasText: 'ASS 视频' })
    await expect(assDialog).toBeVisible()
    await assDialog.locator('input[type="file"][accept=".ass"]').setInputFiles(assFile)
    const songCode = assDialog.locator('.song-input')
    await expect(songCode).toBeDisabled()
    await expect(songCode).toHaveValue('10012204')
    await expect(assDialog.getByText(/可不选/)).toBeVisible()
    await expect(assDialog.getByLabel('画幅')).toHaveAttribute('data-value', '16:9')
    await expect(assDialog.getByLabel('清晰度').first()).toHaveAttribute('data-value', '480p')
    await expect(assDialog.getByLabel('视频模型')).toBeEnabled()
    await assDialog.getByLabel('视频模型').click()
    await expect(page.locator('[data-model-option]')).toHaveCount(12)
    await expect(
      page.locator('[data-model-option]').filter({ hasText: /英和|all in one|RunningHub/ }),
    ).toHaveCount(0)
    await page.getByRole('button', { name: 'Gemini Omni 1.1 Flash Preview', exact: true }).click()
    await expect(assDialog.getByLabel('清晰度').first()).toHaveAttribute('data-value', '720p')
    await expectDropdownOptions(assDialog.getByLabel('画幅'), 2)
    await assDialog.getByLabel('视频模型').click()
    await page.getByRole('button', { name: 'SD2.0', exact: true }).click()
    await expect(assDialog.getByLabel('图片模型')).toBeEnabled()
    await assDialog.getByLabel('图片模型').click()
    await page.getByRole('button', { name: 'Nano Banana 2.1', exact: true }).click()
    await expect(assDialog.getByLabel('图片模型')).toContainText('Nano Banana 2.1')
    await page.screenshot({ path: join(output, '03-ass-dialog.png'), fullPage: true })
    await page.reload()
    await expect(page.getByRole('heading', { name: '视频编辑器' })).toBeVisible()
    await page.getByText(projectName, { exact: true }).click()

    await page
      .locator('.script-editor .header-actions')
      .getByRole('button', { name: '定制通用分镜', exact: true })
      .click()
    const general = page.locator('.modal').filter({ hasText: '定制通用分镜' })
    await expect(general).toBeVisible()
    await selectDropdown(general.getByLabel('画幅'), '9:16')
    await expect(general.getByLabel('画幅')).toHaveAttribute('data-value', '9:16')
    await expect(general.getByLabel('视频模型')).toBeEnabled()
    await expect(general.getByLabel('图片模型')).toBeEnabled()
    await general.getByLabel('图片模型').click()
    await page.getByRole('button', { name: 'Nano Banana 2.1', exact: true }).click()
    await expect(general.getByLabel('图片模型')).toContainText('Nano Banana 2.1')
    await general.getByLabel('图片模型').click()
    await expect(page.locator('[data-model-option]')).toHaveCount(2)
    await page.screenshot({ path: join(output, '04-image-model-options.png'), fullPage: true })
    await page.getByRole('button', { name: 'Seedream Pro', exact: true }).click()
    await selectDropdown(general.getByLabel('图片清晰度'), '1.5K')
    await expectDropdownOptions(general.getByLabel('图片清晰度'), ['1K', '1.5K', '2K'])
    for (const mode of ['定制通用分镜', '随机通用分镜']) {
      if (mode === '随机通用分镜') {
        await general.getByRole('button', { name: '取消', exact: true }).click()
        await page
          .locator('.script-editor .header-actions')
          .getByRole('button', { name: mode, exact: true })
          .click()
      }
      const dialog = page.locator('.modal').filter({ hasText: mode })
      await expect(dialog.getByLabel('空镜数量')).toHaveAttribute('max', '30')
      await expect(dialog.getByLabel('人物镜数量')).toHaveAttribute('max', '30')
      await dialog.getByLabel('空镜数量').fill('5')
      await dialog.getByLabel('人物镜数量').fill('25')
      await dialog.getByLabel('总时长（秒）').fill('300')
      await expect(dialog.locator('.estimate')).toContainText('30 个视频（上限 30）')
      await expect(dialog.locator('.estimate')).not.toHaveClass(/invalid/)
      await dialog.getByLabel('人物镜数量').fill('26')
      await expect(dialog.locator('.estimate')).toHaveClass(/invalid/)
      await expect(dialog.locator('.modal-footer .btn-primary')).toBeDisabled()
      await dialog.getByLabel('人物镜数量').fill('25')
    }
    await page.screenshot({ path: join(output, '04-general-dialog.png'), fullPage: true })
    await expect(page.locator('[role="alertdialog"]')).toHaveCount(0)
    await page.screenshot({ path: join(output, '05-final-state.png'), fullPage: true })
  } finally {
    if (projectId && accessToken) {
      const response = await page.request.delete(`/api/projects/${projectId}`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      })
      expect([200, 404]).toContain(response.status())
    }
  }
})
