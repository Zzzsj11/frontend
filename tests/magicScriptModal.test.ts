import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MagicScriptModal from '../src/components/MagicScriptModal.vue'
import { useProjectStore } from '../src/stores/project'

describe('magic script defaults', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('defaults the resolution select to 480p', async () => {
    const store = useProjectStore()
    const wrapper = mount(MagicScriptModal, { attachTo: document.body })
    store.magicOpen = true
    // BaseModal Teleport 到 body，等 watch(resetForm) 与弹层渲染完成
    await vi.waitFor(() =>
      expect(document.body.querySelectorAll('select').length).toBeGreaterThan(0),
    )

    const selects = Array.from(document.body.querySelectorAll('select'))
    const resolutionSelect = selects.find((select) => select.querySelector('option[value="1080p"]'))
    expect(resolutionSelect, '未找到清晰度下拉框').toBeDefined()
    expect(resolutionSelect!.value).toBe('480p')
    wrapper.unmount()
  })

  it('mounts correctly when already open (P3d 懒挂载回归：immediate watch 不得引用未初始化的 const)', async () => {
    const store = useProjectStore()
    // 先置 open 再挂载——v-if 懒挂载后挂载即打开，immediate watch 同步执行 resetForm
    store.magicOpen = true
    const wrapper = mount(MagicScriptModal, { attachTo: document.body })
    await vi.waitFor(() =>
      expect(document.body.querySelectorAll('select').length).toBeGreaterThan(0),
    )
    expect(document.body.querySelector('input[type="file"][accept=".ass"]')).toBeTruthy()
    wrapper.unmount()
  })
})
