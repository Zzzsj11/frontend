import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import StoryboardOutlineModal from '../../src/components/StoryboardOutlineModal.vue'
import { useProjectStore } from '../../src/stores/project'
import type { StoryBible } from '../../src/types'

describe('StoryboardOutlineModal wardrobe groups', () => {
  beforeEach(() => setActivePinia(createPinia()))

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('shows atmosphere intent and the three-shot wardrobe range for general storyboards', async () => {
    const store = useProjectStore()
    store.activeStoryBible = {
      version: 'story-bible-v6',
      logline: '雨夜重逢',
      characterPolicy: '同组服装一致，切换组时换装',
      wardrobeGroups: [
        {
          groupIndex: 0,
          shotStart: 0,
          shotEnd: 2,
          visualIntent: '冷蓝雨夜、克制疏离',
          wardrobeByCharacter: {
            'human-1': '深蓝防水风衣、灰色针织衫、黑色长裤与皮靴',
          },
        },
      ],
      shots: [],
    } as StoryBible
    store.outlineOpen = true

    mount(StoryboardOutlineModal, { attachTo: document.body })
    const scenesButton = [...document.body.querySelectorAll('button')].find(
      (button) => button.textContent === '场景总览',
    )
    expect(scenesButton).toBeTruthy()
    scenesButton?.click()
    await nextTick()

    expect(document.body.textContent).toContain('服装组 1')
    expect(document.body.textContent).toContain('镜头 1–3')
    expect(document.body.textContent).toContain('冷蓝雨夜、克制疏离')
    expect(document.body.textContent).toContain('深蓝防水风衣')
  })
})
