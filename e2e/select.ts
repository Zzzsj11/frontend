import { expect, type Locator } from '@playwright/test'

export async function selectDropdown(trigger: Locator, label: string) {
  await trigger.click()
  await trigger.page().getByRole('option', { name: label, exact: true }).click()
}
export async function expectDropdownOptions(trigger: Locator, expected: number | string[]) {
  await trigger.click()
  const options = trigger.page().getByRole('option')
  if (typeof expected === 'number') await expect(options).toHaveCount(expected)
  else await expect(options.locator('.generation-model-item-text')).toHaveText(expected)
  await trigger.press('Escape')
}
