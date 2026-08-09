import { expect, test } from '@playwright/test'
test.skip(!process.env.ADMIN_CONSOLE_E2E, 'set ADMIN_CONSOLE_E2E=1')
const username=process.env.REMOTE_E2E_USERNAME||'admin', password=process.env.REMOTE_E2E_PASSWORD||'123456'
test('administrator can inspect dashboard, models, errors and audit logs',async({page})=>{
  await page.goto('/login');await page.getByLabel('用户名').fill(username);await page.getByLabel('密码').fill(password);await page.getByRole('button',{name:'登录'}).click()
  await page.goto('/admin');await expect(page.getByRole('heading',{name:'仪表盘'})).toBeVisible();await expect(page.getByText('累计 Token')).toBeVisible()
  await page.getByRole('button',{name:'模型管理'}).click();await expect(page.getByText('gpt-image-2')).toBeVisible();await expect(page.getByText('doubao-seedance-2.0')).toBeVisible()
  await page.getByRole('button',{name:'费用用量'}).click();await expect(page.getByRole('heading',{name:'费用用量'})).toBeVisible()
  await page.getByRole('button',{name:'错误日志'}).click();await expect(page.getByRole('heading',{name:'错误日志'})).toBeVisible()
  await page.getByRole('button',{name:'操作审计'}).click();await expect(page.getByRole('heading',{name:'操作审计'})).toBeVisible()
})
