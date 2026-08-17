import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createStoryboardOption,
  deleteStoryboardOption,
  listStoryboardOptions,
  updateStoryboardOption,
} from '../../src/api/adminStoryboardOptions'
import AdminStoryboardOptionsPanel from '../../src/components/AdminStoryboardOptionsPanel.vue'

vi.mock('../../src/api/adminStoryboardOptions', () => ({
  listStoryboardOptions: vi.fn(),
  createStoryboardOption: vi.fn(),
  updateStoryboardOption: vi.fn(),
  deleteStoryboardOption: vi.fn(),
}))

const genreItems = [
  { id: 'g1', kind: 'genre', parentId: null, name: '流行歌曲', sortOrder: 0 },
  { id: 'g2', kind: 'genre', parentId: 'g1', name: '爱情消极', sortOrder: 0 },
  { id: 'g3', kind: 'genre', parentId: 'g2', name: '失恋', sortOrder: 0 },
  { id: 'g4', kind: 'genre', parentId: null, name: '戏曲', sortOrder: 1 },
]

const flush = async () => {
  await vi.waitFor(() => expect(listStoryboardOptions).toHaveBeenCalled())
  await new Promise((resolve) => setTimeout(resolve))
}

describe('admin storyboard options panel', () => {
  beforeEach(() => {
    vi.mocked(listStoryboardOptions).mockReset()
    vi.mocked(createStoryboardOption).mockReset()
    vi.mocked(updateStoryboardOption).mockReset()
    vi.mocked(deleteStoryboardOption).mockReset()
    vi.mocked(listStoryboardOptions).mockResolvedValue(genreItems as never)
  })

  it('renders the genre category as an indented tree', async () => {
    const wrapper = mount(AdminStoryboardOptionsPanel)
    await flush()
    expect(listStoryboardOptions).toHaveBeenCalledWith('genre')
    const names = wrapper.findAll('.name-cell')
    expect(names.map((cell) => cell.text())).toEqual(['流行歌曲', '└爱情消极', '└失恋', '戏曲'])
    // 三级节点不再提供「新增子级」（最多三级）
    const thirdRow = wrapper.findAll('tr').find((row) => row.text().includes('失恋'))
    expect(thirdRow!.findAll('button[title="新增子级"]').length).toBe(0)
    wrapper.unmount()
  })

  it('creates a root option via the inline form', async () => {
    const wrapper = mount(AdminStoryboardOptionsPanel)
    await flush()
    await wrapper.find('.add-root').trigger('click')
    const input = wrapper.find('.inline-form input')
    await input.setValue('  新曲风  ')
    await wrapper.find('.inline-form .op-btn.primary').trigger('click')
    expect(createStoryboardOption).toHaveBeenCalledWith({
      kind: 'genre',
      parentId: null,
      name: '新曲风',
    })
    wrapper.unmount()
  })

  it('creates a child option under a genre node', async () => {
    const wrapper = mount(AdminStoryboardOptionsPanel)
    await flush()
    const row = wrapper.findAll('tr').find((r) => r.text().includes('爱情消极'))!
    await row.find('button[title="新增子级"]').trigger('click')
    await wrapper.find('.inline-form input').setValue('新子类')
    await wrapper.find('.inline-form .op-btn.primary').trigger('click')
    expect(createStoryboardOption).toHaveBeenCalledWith({
      kind: 'genre',
      parentId: 'g2',
      name: '新子类',
    })
    wrapper.unmount()
  })

  it('renames an option inline', async () => {
    const wrapper = mount(AdminStoryboardOptionsPanel)
    await flush()
    const row = wrapper.findAll('tr').find((r) => r.text().includes('戏曲'))!
    await row.find('button[title="重命名"]').trigger('click')
    const input = row.find('input')
    await input.setValue('戏曲曲艺')
    await row.find('.op-btn.primary').trigger('click')
    expect(updateStoryboardOption).toHaveBeenCalledWith('g4', { name: '戏曲曲艺' })
    wrapper.unmount()
  })

  it('deletes an option after inline confirmation', async () => {
    const wrapper = mount(AdminStoryboardOptionsPanel)
    await flush()
    const row = wrapper.findAll('tr').find((r) => r.text().includes('流行歌曲'))!
    await row.find('button[title="删除"]').trigger('click')
    // 一级分类提示级联删除子级
    expect(row.text()).toContain('含子级')
    await row.find('.op-btn.danger').trigger('click')
    expect(deleteStoryboardOption).toHaveBeenCalledWith('g1')
    wrapper.unmount()
  })

  it('switches kind tabs and reloads the list', async () => {
    vi.mocked(listStoryboardOptions).mockResolvedValue([] as never)
    const wrapper = mount(AdminStoryboardOptionsPanel)
    await flush()
    const seasonTab = wrapper.findAll('.kind-tab').find((tab) => tab.text() === '季节')!
    await seasonTab.trigger('click')
    expect(listStoryboardOptions).toHaveBeenCalledWith('season')
    wrapper.unmount()
  })
})
