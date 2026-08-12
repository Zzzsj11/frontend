import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ConfirmDialog from '../src/components/ConfirmDialog.vue'
import { confirmDialog } from '../src/composables/useConfirmDialog'

describe('confirm dialog keyboard handling', () => {
  it('confirms on Enter and cancels on Escape', async () => {
    mount(ConfirmDialog)

    const enterPromise = confirmDialog('确定删除吗？')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await expect(enterPromise).resolves.toBe(true)

    const escapePromise = confirmDialog('再确认一次')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await expect(escapePromise).resolves.toBe(false)
  })

  it('ignores key events while the dialog is closed', async () => {
    mount(ConfirmDialog)
    // 未打开时按 Enter 不应触发任何 resolver
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    const promise = confirmDialog('确认操作')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await expect(promise).resolves.toBe(true)
  })
})
