import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CharacterPortrait from '../../src/components/CharacterPortrait.vue'

describe('CharacterPortrait', () => {
  it('uses the existing character sheet as a CSS sprite without changing its URL', () => {
    const src = 'https://tos.example/system/digital-humans/thumbnails/031.jpg'
    const wrapper = mount(CharacterPortrait, { props: { src, alt: '小男孩 01' } })
    const portrait = wrapper.get('[role="img"]')

    expect(portrait.attributes('aria-label')).toBe('小男孩 01')
    expect(portrait.attributes('style')).toContain(src)
    expect(wrapper.find('img').exists()).toBe(false)
  })
})
