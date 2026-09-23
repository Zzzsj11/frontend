import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CharacterPortrait from '../../src/components/CharacterPortrait.vue'

const src = 'https://tos.test/portrait.jpg'

async function loadImage(wrapper: ReturnType<typeof mount>, width: number, height: number) {
  const image = wrapper.get('img')
  Object.defineProperties(image.element, {
    naturalWidth: { value: width, configurable: true },
    naturalHeight: { value: height, configurable: true },
  })
  await image.trigger('load')
}

describe('CharacterPortrait', () => {
  it('centers a headshot without cropping it as a character sheet', async () => {
    const wrapper = mount(CharacterPortrait, { props: { src, alt: '小男孩 01' } })
    await loadImage(wrapper, 1024, 1536)
    expect(wrapper.get('[role="img"]').attributes('aria-label')).toBe('小男孩 01')
    expect(wrapper.get('img').attributes('src')).toBe(src)
    expect(wrapper.classes()).not.toContain('legacy-sheet')
  })

  it('keeps the left-face crop for legacy sheets and resets after replacement', async () => {
    const wrapper = mount(CharacterPortrait, { props: { src } })
    await loadImage(wrapper, 1344, 768)
    expect(wrapper.classes()).toContain('legacy-sheet')
    await wrapper.setProps({ src: 'https://tos.test/new.jpg' })
    expect(wrapper.classes()).not.toContain('legacy-sheet')
    await loadImage(wrapper, 320, 480)
    expect(wrapper.classes()).not.toContain('legacy-sheet')
  })

  it('does not treat square portraits as sheets and tolerates unavailable images', async () => {
    const wrapper = mount(CharacterPortrait, { props: { src } })
    await loadImage(wrapper, 1024, 1024)
    expect(wrapper.classes()).not.toContain('legacy-sheet')
    await wrapper.setProps({ src: undefined })
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.attributes('aria-label')).toBe('人物头像')
  })
})
