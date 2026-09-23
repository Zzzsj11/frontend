<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
const props = withDefaults(defineProps<{ open: boolean; title: string; loading?: boolean }>(), {
  loading: false,
})
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
let previous: HTMLElement | null = null
function close() {
  if (!props.loading) emit('close')
}
watch(
  () => props.open,
  async (open) => {
    await nextTick()
    if (open && dialog.value && !dialog.value.open) {
      previous = document.activeElement as HTMLElement
      dialog.value.showModal()
    } else if (!open) {
      dialog.value?.close()
      previous?.focus()
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  dialog.value?.close()
  previous?.focus()
})
</script>
<template>
  <Teleport to="body">
    <dialog ref="dialog" :aria-label="title" aria-modal="true" @cancel.prevent="close">
      <header>
        <h2>{{ title }}</h2>
        <button class="secondary" aria-label="关闭弹窗" :disabled="loading" @click="close">
          <svg
            viewBox="0 0 24 24"
            width="18"
            height="18"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            aria-hidden="true"
          >
            <path d="m6 6 12 12M18 6 6 18" />
          </svg>
        </button>
      </header>
      <div class="modal-body"><slot /></div>
      <footer v-if="$slots.footer"><slot name="footer" /></footer>
    </dialog>
  </Teleport>
</template>
<style scoped>
dialog {
  width: min(640px, calc(100vw - 32px));
  max-height: 90dvh;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 0;
  background: var(--panel);
  color: var(--text);
}
dialog::backdrop {
  background: var(--modal-backdrop);
}
header,
footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 24px;
}
header {
  border-bottom: 1px solid var(--border);
}
header h2 {
  font-size: 20px;
  margin: 0;
}
header button {
  display: grid;
  place-items: center;
  padding: 8px;
}
.modal-body {
  padding: 24px;
  overflow-wrap: anywhere;
}
footer {
  border-top: 1px solid var(--border);
  justify-content: flex-end;
}
</style>
