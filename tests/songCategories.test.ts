import { describe, expect, it } from 'vitest'

import { SONG_CATEGORY_GENRES } from '../src/songCategories'
import type { StoryboardCategoryOption } from '../src/types'

const walk = (
  nodes: StoryboardCategoryOption[],
  visit: (node: StoryboardCategoryOption) => void,
) => {
  for (const node of nodes) {
    visit(node)
    if (node.children) walk(node.children, visit)
  }
}

describe('SONG_CATEGORY_GENRES（通用分镜三级分类）', () => {
  it('keeps value identical to label everywhere (backend storage alignment)', () => {
    walk(SONG_CATEGORY_GENRES, (node) => expect(node.value).toBe(node.label))
  })

  it('covers the full top-level genre list', () => {
    expect(SONG_CATEGORY_GENRES.map((node) => node.value)).toEqual([
      '流行歌曲',
      '民族歌曲',
      '国风',
      '红歌',
      '舞曲',
      '中文说唱',
      '儿童歌曲',
      '祝福歌曲',
      '戏曲',
      '外语歌曲',
      '中文喊麦',
    ])
  })

  it('marks 戏曲 and 中文喊麦 as leaves without a secondary category', () => {
    for (const name of ['戏曲', '中文喊麦']) {
      const node = SONG_CATEGORY_GENRES.find((item) => item.value === name)
      expect(node, name).toBeDefined()
      expect(node?.children, name).toBeUndefined()
    }
  })

  it('keeps sibling values unique at every level', () => {
    const checkUnique = (nodes: StoryboardCategoryOption[]) => {
      const values = nodes.map((node) => node.value)
      expect(new Set(values).size).toBe(values.length)
      nodes.forEach((node) => node.children && checkUnique(node.children))
    }
    checkUnique(SONG_CATEGORY_GENRES)
  })

  it('provides a complete three-level path under 流行歌曲', () => {
    const pop = SONG_CATEGORY_GENRES[0]
    expect(pop.value).toBe('流行歌曲')
    expect(pop.children?.length).toBeGreaterThan(0)
    for (const secondary of pop.children ?? []) {
      expect(secondary.children?.length, `${secondary.value} 应有三级分类`).toBeGreaterThan(0)
    }
  })
})
