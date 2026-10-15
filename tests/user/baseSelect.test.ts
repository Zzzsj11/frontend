import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import BaseSelect from '../../src/components/base/BaseSelect.vue'
import BaseModelSelect from '../../src/components/base/BaseModelSelect.vue'

describe('shared dropdown contracts', () => {
  it('preserves empty and numeric values and native change handlers', async () => {
    const wrapper = mount(BaseSelect, {
      props: { modelValue: '', modelModifiers: { number: true } },
      slots: {
        default: () => [h('option', { value: '' }, '不限制'), h('option', { value: 6 }, '6 秒')],
      },
    })
    const control = wrapper.findComponent(BaseModelSelect)
    expect(control.props('groups')[0].items[0].label).toBe('不限制')
    control.vm.$emit('update:modelValue', control.props('groups')[0].items[1].value)
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([6])
    const event = wrapper.emitted('change')?.[0][0] as Event
    expect((event.target as HTMLSelectElement).value).toBe('6')
    wrapper.unmount()
  })

  it('refreshes dependent choices when parent options change', async () => {
    const options = ref(['秋'])
    const wrapper = mount(
      defineComponent({
        setup: () => () =>
          h(
            BaseSelect,
            { modelValue: '秋' },
            { default: () => options.value.map((label) => h('option', { value: label }, label)) },
          ),
      }),
    )
    expect(wrapper.text()).toContain('秋')
    options.value = ['冬', '秋']
    await nextTick()
    const control = wrapper.findComponent(BaseModelSelect)
    expect(control.props('groups')[0].items.map((item) => item.label)).toEqual(['冬', '秋'])
    expect(wrapper.text()).toContain('秋')
    wrapper.unmount()
  })

  it('keeps disabled choices from changing the value', () => {
    const wrapper = mount(BaseSelect, {
      props: { value: 'a' },
      slots: {
        default: () => [
          h('option', { value: 'a' }, '可选'),
          h('option', { value: 'b', disabled: true }, '停用'),
        ],
      },
    })
    const control = wrapper.findComponent(BaseModelSelect)
    control.vm.$emit('update:modelValue', control.props('groups')[0].items[1].value)
    expect(wrapper.emitted('change')).toBeUndefined()
    wrapper.unmount()
  })
})
