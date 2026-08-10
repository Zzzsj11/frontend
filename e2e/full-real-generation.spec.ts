import { expect, test, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'

test.skip(process.env.REAL_GENERATION_E2E !== '1', 'requires real model, image, video and TOS providers')
test.setTimeout(90 * 60 * 1000)

const runId = process.env.REAL_E2E_RUN_ID || new Date().toISOString().replaceAll(/[:.]/g, '-')
const artifactRoot = process.env.REAL_E2E_ARTIFACT_DIR || join(process.cwd(), 'test-artifacts/full-journey/runs', runId)
const output = join(artifactRoot, 'screenshots')
const assFixture = process.env.REAL_E2E_ASS_FILE || join(process.cwd(), 'test-artifacts/full-journey/inputs/10012204-full-e2e.ass')
const username = process.env.REAL_E2E_USERNAME || 'admin'
const password = process.env.REAL_E2E_PASSWORD || '123456'
const projectSuffix = process.env.REAL_E2E_PROJECT_SUFFIX ? ` ${process.env.REAL_E2E_PROJECT_SUFFIX}` : ''
mkdirSync(output, { recursive: true })
const generalOnly = process.env.REAL_E2E_PHASE === 'general'
const exportOnly = process.env.REAL_E2E_PHASE === 'general-export'
let shot = exportOnly ? 21 : generalOnly ? 12 : 0
const capture = async (page: Page, name: string) => {
  shot += 1
  await page.screenshot({ path: join(output, `${String(shot).padStart(2, '0')}-${name}.png`), fullPage: true })
}

async function createProject(page: Page, name: string) {
  await page.getByRole('button', { name: '创建歌曲项目' }).click()
  await page.getByPlaceholder('歌曲名称，回车创建').fill(name)
  await page.locator('.create-form').getByRole('button', { name: '创建' }).click()
  await expect(page.getByText(name, { exact: true })).toBeVisible()
  await expect(page.locator('.song-folder.current').filter({ hasText: name })).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.script-editor .header-actions').getByRole('button', { name: '通用分镜', exact: true })).toBeEnabled()
  await capture(page, `${name}-project-created`)
}

async function waitForPrompts(page: Page, expected: number, prefix: string) {
  await expect(page.locator('.line-wrapper')).toHaveCount(expected, { timeout: 30_000 })
  await expect(page.getByText(`已生成 ${expected}/${expected}`)).toBeVisible({ timeout: 10 * 60_000 })
  await expect(page.locator('.prompt-generation-state.failed')).toHaveCount(0)
  await capture(page, `${prefix}-all-prompts-complete`)
}

async function generateAllMedia(page: Page, count: number, prefix: string) {
  for (let index = 0; index < count; index++) {
    const line = page.locator('.line-wrapper').nth(index)
    await line.locator('.shot-thumb').click({ position: { x: 6, y: 6 } })
    const dialog = page.locator('.modal').filter({ hasText: '编辑分镜内容' })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: '生成场景', exact: true }).click()
    await capture(page, `${prefix}-line-${index + 1}-scene-started`)
    await dialog.getByTitle('关闭').click()
  }
  await expect(page.locator('.line-wrapper .shot-thumb img')).toHaveCount(count, { timeout: 15 * 60_000 })
  await capture(page, `${prefix}-all-scenes-complete`)

  for (let index = 0; index < count; index++) {
    const line = page.locator('.line-wrapper').nth(index)
    await line.getByRole('button', { name: '生成视频片段（场景 × 分镜 × 角色）' }).click()
    await capture(page, `${prefix}-line-${index + 1}-video-started`)
    await expect(line.locator('.shot-thumb video')).toHaveCount(1, { timeout: 25 * 60_000 })
  }
  await expect(page.locator('.line-wrapper .shot-thumb video')).toHaveCount(count, { timeout: 25 * 60_000 })
  await capture(page, `${prefix}-all-videos-complete`)

  await page.locator('.line-wrapper').first().click()
  const reopenedEditor = page.locator('.modal').filter({ hasText: '编辑分镜内容' })
  if (await reopenedEditor.isVisible()) await reopenedEditor.getByTitle('关闭').click()
  await expect(page.locator('.player-panel video')).toBeVisible()
  await capture(page, `${prefix}-video-player-ready`)
  await page.getByRole('button', { name: '导出素材', exact: true }).click()
  await expect(page.getByRole('button', { name: '素材已导出' })).toBeVisible({ timeout: 5 * 60_000 })
  await capture(page, `${prefix}-material-export-complete`)
}

test('ASS and general storyboard complete real frontend journeys through generated videos', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByRole('heading', { name: '分镜编辑器' })).toBeVisible()
  if (exportOnly) {
    const task = page.getByRole('button', { name: /通用分镜 ·/ }).last()
    await task.click()
    await expect(page.locator('.line-wrapper .shot-thumb video')).toHaveCount(2, { timeout: 30_000 })
    await page.locator('.line-wrapper').first().click()
    const editor = page.locator('.modal').filter({ hasText: '编辑分镜内容' })
    if (await editor.isVisible()) await editor.getByTitle('关闭').click()
    await expect(page.locator('.player-panel video')).toBeVisible()
    await capture(page, 'general-video-player-ready')
    await page.getByRole('button', { name: '导出素材', exact: true }).click()
    await expect(page.getByRole('button', { name: '素材已导出' })).toBeVisible({ timeout: 5 * 60_000 })
    await capture(page, 'general-material-export-complete')
    await expect(page.locator('[role="alertdialog"]')).toHaveCount(0)
    await capture(page, 'both-journeys-final-state')
    return
  }
  if (!generalOnly) await capture(page, 'login-and-empty-workspace')

  if (!generalOnly) {
    await createProject(page, `ASS 全链路真实验收${projectSuffix}`)
    await page.locator('.script-editor .header-actions').getByRole('button', { name: 'ASS 分镜', exact: true }).click()
    await page.locator('input[type="file"][accept=".ass"]').setInputFiles(assFixture)
    await page.locator('.role-card').nth(0).click()
    await page.locator('.role-card').nth(16).click()
    await capture(page, 'ass-input-and-cast-selected')
    await page.getByRole('button', { name: '生成', exact: true }).click()
    await waitForPrompts(page, 2, 'ass')
    await generateAllMedia(page, 2, 'ass')
  }

  await createProject(page, `通用分镜全链路真实验收${projectSuffix}`)
  await page.locator('.script-editor .header-actions').getByRole('button', { name: '通用分镜', exact: true }).click()
  const general = page.locator('.modal').filter({ hasText: '通用分镜' })
  await general.locator('.cast-item').nth(17).click()
  await general.getByLabel('空镜数量').fill('1')
  await general.getByLabel('人物镜数量').fill('1')
  await general.getByLabel('总时长（秒）').fill('10')
  await general.getByLabel('画幅').selectOption('9:16')
  await general.getByLabel('额外要求（可选）').fill('同一秋夜城市街区，从孤独到相遇，电影写实')
  await capture(page, 'general-parameters-and-cast-selected')
  await general.getByRole('button', { name: '批量生成' }).click()
  await waitForPrompts(page, 2, 'general')
  await generateAllMedia(page, 2, 'general')

  await expect(page.locator('[role="alertdialog"]')).toHaveCount(0)
  await capture(page, 'both-journeys-final-state')
})
