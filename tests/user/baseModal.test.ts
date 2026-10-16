import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import BaseModal from '../../src/components/base/BaseModal.vue'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
})
const mountModal = (loading = false) => {
  const wrapper = mount(BaseModal, {
    props: { open: true, loading },
    slots: { default: '<input aria-label="内容" />' },
    attachTo: document.body,
  })
  wrappers.push(wrapper)
  return wrapper
}
const press = (element: Element, button = 0) =>
  element.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button }))

describe('modal outside pointer interaction', () => {
  it('leaves Escape to an open portal dropdown', () => {
    const wrapper = mountModal()
    const menu = document.createElement('div')
    menu.className = 'generation-model-menu'
    menu.dataset.state = 'open'
    document.body.append(menu)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }))
    expect(wrapper.emitted('close')).toBeUndefined()
    menu.remove()
  })
  it('closes from the backdrop but not from the dialog or right click', () => {
    const wrapper = mountModal()
    press(document.querySelector('[aria-label="内容"]')!)
    press(document.querySelector('.modal-mask')!, 2)
    expect(wrapper.emitted('close')).toBeUndefined()
    press(document.querySelector('.modal-mask')!)
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
  it('keeps an in-progress operation open', () => {
    const wrapper = mountModal(true)
    press(document.querySelector('.modal-mask')!)
    expect(wrapper.emitted('close')).toBeUndefined()
  })
  it('only closes the nested modal when its backdrop is pressed', () => {
    const outer = mountModal()
    const inner = mount(BaseModal, {
      props: { open: true, level: 'nested' },
      attachTo: document.body,
    })
    wrappers.push(inner)
    press(document.querySelector('.modal-mask.level-nested')!)
    expect(inner.emitted('close')).toHaveLength(1)
    expect(outer.emitted('close')).toBeUndefined()
  })
})
