import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AdminPagination from '../../src/components/base/AdminPagination.vue'

describe('AdminPagination', () => {
  it('展示总数、当前页、总页数并支持前后翻页', async () => {
    const wrapper = mount(AdminPagination, {
      props: { page: 2, total: 120, pageSize: 50, position: '顶部' },
    })
    expect(wrapper.text()).toContain('共 120 条')
    expect(wrapper.text()).toContain('当前第 2 页')
    expect(wrapper.text()).toContain('/ 3 页')
    await wrapper.get('button[aria-label="上一页"]').trigger('click')
    expect(wrapper.emitted('change')?.at(-1)).toEqual([1])
    await wrapper.get('button[aria-label="下一页"]').trigger('click')
    expect(wrapper.emitted('change')?.at(-1)).toEqual([3])
  })

  it('支持手动输入并约束到有效页码', async () => {
    const wrapper = mount(AdminPagination, {
      props: { page: 1, total: 120, pageSize: 50, position: '底部' },
    })
    await wrapper.get('input').setValue('99')
    expect(wrapper.emitted('change')?.at(-1)).toEqual([3])
  })
})
