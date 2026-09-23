import assert from 'node:assert/strict'
import test from 'node:test'
import { points, money, moneyPoints, signedPoints, financialDetails } from '../admin-web/src/utils/financial.ts'
test('积分只取整数部分，金额精确四舍五入且保留两位', () => {
  assert.equal(points('123.999999'), '123')
  assert.equal(points('-12.99999'), '-12')
  assert.equal(points('-0.999'), '0')
  assert.equal(signedPoints('5.8'), '+5')
  assert.equal(signedPoints('-0.2'), '0')
  assert.equal(money('1.005'), '1.01')
  assert.equal(money('-1.005'), '-1.01')
  assert.equal(money('9.999'), '10.00')
  assert.equal(money('6.9'), '6.90')
  assert.equal(money('5e-3'), '0.01')
  assert.equal(money('4e-3'), '0.00')
  assert.equal(money('999999999999999999.995'), '1000000000000000000.00')
  assert.equal(moneyPoints('0.29'), '29')
  assert.equal(money(null), '—')
  assert.equal(points('NaN'), '—')
})
test('财务详情格式化不改变原始 API 数据', () => {
  const source = { billing: {points:'123.456', cny:'1.235'}, usage:{completion_tokens:5}, pricing:{rates:[{cny:'0.000001',unit:1}]} }
  const original = JSON.stringify(source)
  const view = financialDetails(source)
  assert.equal(view.billing.points, '123')
  assert.equal(view.billing.cny, '1.24')
  assert.equal(view.usage.completion_tokens, 5)
  assert.equal(view.pricing.rates[0].cny, '0.00')
  assert.equal(JSON.stringify(source), original)
})

test('用户门户积分展示与后台一致，不把小数进位或显示负零', async () => {
  const portal = await import('../user-web/src/utils/financial.ts')
  assert.equal(portal.points('100.000000'), '100')
  assert.equal(portal.points('0.999999'), '0')
  assert.equal(portal.points('123.987654'), '123')
  assert.equal(portal.signedPoints('-0.123456'), '0')
  assert.equal(portal.signedPoints('-12.987654'), '-12')
  assert.equal(portal.money('1.005'), '1.01')
})
