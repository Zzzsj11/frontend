<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import AppIcon from '../AppIcon.vue'

/**
 * 全局统一弹框基座（规范见 docs/FRONTEND-GUIDELINES.md 第 5 节）
 * 封装：Teleport 到 body、遮罩点击/Esc 关闭（loading 时禁止）、z-index 档位、aria 属性。
 * 内容结构：title 插槽（标题区）+ actions 插槽（标题栏右侧操作区）→ 默认插槽（主体，业务侧自备滚动容器类）→ footer 插槽。
 */
const props = withDefaults(
  defineProps<{
    open: boolean
    /** 标题文本；需带图标等富文本时使用 title 插槽 */
    title?: string
    ariaLabel?: string
    /** 为 true 时禁止遮罩/Esc/按钮关闭（用于生成中等不可中断状态） */
    loading?: boolean
    /** primary=一级弹框(z-index 1000)；nested=弹框内二级弹层(z-index 1100) */
    level?: 'primary' | 'nested'
    /** emphasized 用于需要更强背景聚焦的编辑弹框。 */
    maskVariant?: 'default' | 'emphasized'
    width?: string
    maxHeight?: string
  }>(),
  {
    title: '',
    ariaLabel: '',
    loading: false,
    level: 'primary',
    maskVariant: 'default',
    width: '620px',
    maxHeight: '92vh',
  },
)
const emit = defineEmits<{ close: [] }>()

const requestClose = () => {
  if (props.loading) return
  emit('close')
}
const onKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') requestClose()
}
watch(
  () => props.open,
  (open) => {
    if (open) window.addEventListener('keydown', onKeydown)
    else window.removeEventListener('keydown', onKeydown)
  },
)
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="modal-mask"
      :class="[`level-${level}`, `mask-${maskVariant}`]"
      @click.self="requestClose"
    >
      <section
        class="modal"
        :style="{ width, maxHeight }"
        role="dialog"
        aria-modal="true"
        :aria-label="ariaLabel || title"
      >
        <header class="modal-header">
          <h3>
            <slot name="title">{{ title }}</slot>
          </h3>
          <div v-if="$slots.actions" class="modal-actions">
            <slot name="actions" />
          </div>
          <button
            class="modal-close"
            :disabled="loading"
            title="关闭"
            aria-label="关闭"
            @click="requestClose"
          >
            <AppIcon name="close" :size="14" />
          </button>
        </header>
        <slot />
        <footer v-if="$slots.footer" class="modal-footer">
          <slot name="footer" />
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(0, 0, 0, 0.45);
}
.modal-mask.level-nested {
  z-index: 1100;
  background: rgba(0, 0, 0, 0.6);
}
.modal-mask.mask-emphasized {
  background: rgba(0, 0, 0, 0.62);
}
.modal {
  display: flex;
  max-width: 100%;
  flex-direction: column;
  overflow: hidden;
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-modal);
}
.modal-header {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 22px;
  border-bottom: 1px solid var(--border);
}
.modal-header h3 {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: var(--text);
  font-size: var(--font-lg);
}
.modal-header h3 :deep(.app-icon) {
  flex: 0 0 auto;
  color: var(--primary);
}
.modal-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}
.modal-close {
  display: grid;
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  place-items: center;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}
.modal-close:hover:not(:disabled) {
  background: var(--bg);
  color: var(--text);
}
.modal-close:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.modal-footer {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 22px 18px;
  border-top: 1px solid var(--border);
}
</style>
