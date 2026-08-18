import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createSongEmotion,
  deleteSongEmotion,
  listSongEmotions,
  updateSongEmotion,
} from '../../src/api/adminSongEmotions'
import AdminSongEmotionProfilesPanel from '../../src/components/AdminSongEmotionProfilesPanel.vue'

vi.mock('../../src/api/domain', () => ({
  fetchGeneralStoryboardOptions: vi.fn().mockResolvedValue({
    genres: [
      {
        value: '流行歌曲',
        label: '流行歌曲',
        children: [
          {
            value: '爱情消极',
            label: '爱情消极',
            children: [{ value: '失恋', label: '失恋' }],
          },
        ],
      },
    ],
    seasons: ['春', '夏', '秋', '冬', '通用'],
    ageGroups: [],
    visualStyles: [],
    ratios: [],
  }),
}))

vi.mock('../../src/api/adminSongEmotions', () => ({
  listSongEmotions: vi.fn(),
  createSongEmotion: vi.fn(),
  updateSongEmotion: vi.fn(),
  deleteSongEmotion: vi.fn(),
}))
const item = {
  songCode: '00000780',
  songName: '姐姐真漂亮',
  artists: 'SHINEE',
  primaryCategory: '流行歌曲',
  secondaryCategory: '爱情消极',
  tertiaryCategory: '爱而不得',
  materialCategory: '流行歌曲-爱情消极-爱而不得',
  seasons: '秋/冬',
  atmosphere: '暖色调',
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
}

describe('admin song emotion profiles panel', () => {
  beforeEach(() => {
    vi.mocked(listSongEmotions)
      .mockReset()
      .mockResolvedValue({ total: 1, items: [item] })
    vi.mocked(createSongEmotion).mockReset().mockResolvedValue(item)
    vi.mocked(updateSongEmotion).mockReset().mockResolvedValue(item)
    vi.mocked(deleteSongEmotion).mockReset().mockResolvedValue({ ok: true })
  })
  it('lists and searches profiles', async () => {
    const wrapper = mount(AdminSongEmotionProfilesPanel)
    await vi.waitFor(() => expect(wrapper.text()).toContain('姐姐真漂亮'))
    await wrapper.find('input[aria-label="搜索歌曲情感库"]').setValue('SHINEE')
    await wrapper.find('.search').trigger('submit')
    expect([...vi.mocked(listSongEmotions).mock.calls.at(-1)![0].entries()]).toContainEqual([
      'q',
      'SHINEE',
    ])
    expect(wrapper.findAll('.top-pager button')).toHaveLength(2)
  })
  it('clears the search and resets the full list', async () => {
    vi.mocked(listSongEmotions).mockResolvedValue({ total: 120, items: [item] })
    const wrapper = mount(AdminSongEmotionProfilesPanel)
    await vi.waitFor(() =>
      expect(wrapper.get('[aria-label="顶部选择页码"]').findAll('option')).toHaveLength(3),
    )
    await wrapper.get('[aria-label="顶部选择页码"]').setValue('3')
    await wrapper.get('input[aria-label="搜索歌曲情感库"]').setValue('喜欢你')
    await wrapper.get('button[aria-label="清空搜索"]').trigger('click')
    await vi.waitFor(() => {
      const query = vi.mocked(listSongEmotions).mock.calls.at(-1)![0]
      expect(query.get('offset')).toBe('0')
      expect(query.has('q')).toBe(false)
    })
    expect(wrapper.get<HTMLInputElement>('input[aria-label="搜索歌曲情感库"]').element.value).toBe(
      '',
    )
  })
  it('selects a page from both pagination controls', async () => {
    vi.mocked(listSongEmotions).mockResolvedValue({ total: 120, items: [item] })
    const wrapper = mount(AdminSongEmotionProfilesPanel)
    await vi.waitFor(() =>
      expect(wrapper.get('[aria-label="顶部选择页码"]').findAll('option')).toHaveLength(3),
    )
    await wrapper.get('[aria-label="顶部选择页码"]').setValue('3')
    await vi.waitFor(() =>
      expect(vi.mocked(listSongEmotions).mock.calls.at(-1)![0].get('offset')).toBe('100'),
    )
    await vi.waitFor(() =>
      expect(wrapper.get<HTMLSelectElement>('[aria-label="底部选择页码"]').element.value).toBe('3'),
    )
  })
  it('uses linked category and season defaults for a new profile', async () => {
    const wrapper = mount(AdminSongEmotionProfilesPanel, { attachTo: document.body })
    await vi.waitFor(() => expect(wrapper.text()).toContain('姐姐真漂亮'))
    await wrapper.get('button.primary').trigger('click')
    await vi.waitFor(() =>
      expect(document.body.querySelectorAll('.category-row select')).toHaveLength(3),
    )
    const selects = document.body.querySelectorAll<HTMLSelectElement>('.category-row select')
    expect([...selects[0].options].map((option) => option.text)).toContain('流行歌曲')
    expect([...selects[1].options].map((option) => option.text)).toContain('爱情消极')
    expect(document.body.querySelector('.material-preview')?.textContent).toContain(
      '流行歌曲-爱情消极-失恋',
    )
    const checkedSeason = document.body.querySelector<HTMLInputElement>(
      '.season-option input:checked',
    )
    expect(checkedSeason?.value).toBe('通用')
    wrapper.unmount()
  })
  it('edits and soft deletes a profile', async () => {
    const wrapper = mount(AdminSongEmotionProfilesPanel, { attachTo: document.body })
    await vi.waitFor(() => expect(wrapper.text()).toContain('姐姐真漂亮'))
    await wrapper.findAll('.actions button')[0].trigger('click')
    const name = document.body.querySelector<HTMLInputElement>('input[required]:not([disabled])')!
    name.value = '修改后'
    name.dispatchEvent(new Event('input'))
    document.body.querySelector<HTMLFormElement>('.editor')!.dispatchEvent(new Event('submit'))
    await vi.waitFor(() => expect(updateSongEmotion).toHaveBeenCalled())
    await wrapper.findAll('.actions button').at(-1)!.trigger('click')
    await wrapper.find('.actions .danger').trigger('click')
    expect(deleteSongEmotion).toHaveBeenCalledWith('00000780')
    wrapper.unmount()
  })
})
