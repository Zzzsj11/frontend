<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import AppIcon from './AppIcon.vue'

const { state, close } = useConfirmDialog()
const onKeydown = (event: KeyboardEvent) => {
  if (state.open && event.key === 'Escape') close(false)
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="confirm-fade">
      <div v-if="state.open" class="confirm-mask" @click.self="close(false)">
        <div class="confirm-card" role="alertdialog" aria-modal="true" :aria-label="state.title">
          <div class="confirm-icon" :class="{ danger: state.danger }">
            <AppIcon :name="state.danger ? 'trash' : 'sparkles'" :size="20" />
          </div>
          <div class="confirm-content">
            <h3>{{ state.title }}</h3>
            <p>{{ state.message }}</p>
          </div>
          <footer class="confirm-actions">
            <button class="confirm-cancel" @click="close(false)">{{ state.cancelText }}</button>
            <button class="confirm-submit" :class="{ danger: state.danger }" @click="close(true)">
              {{ state.confirmText }}
            </button>
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.confirm-mask {
  position: fixed;
  inset: 0;
  z-index: 1200;
  background: rgba(20, 20, 20, 0.48);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.confirm-card {
  width: 420px;
  max-width: 100%;
  background: #fff;
  border-radius: var(--radius-lg);
  padding: 24px;
  box-shadow: var(--shadow-modal);
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  gap: 14px;
}
.confirm-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  background: var(--primary-light);
  color: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
}
.confirm-icon.danger {
  background: rgba(238, 51, 51, 0.08);
  color: var(--danger);
}
.confirm-content h3 {
  margin: 2px 0 8px;
  font-size: var(--font-lg);
  color: var(--text);
}
.confirm-content p {
  margin: 0;
  line-height: 1.65;
  color: var(--text-secondary);
  font-size: var(--font-md);
  white-space: pre-line;
}
.confirm-actions {
  grid-column: 1/-1;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 8px;
}
.confirm-actions button {
  min-width: 82px;
  border-radius: var(--radius-pill);
  padding: 9px 18px;
  font-size: var(--font-md);
  font-weight: 600;
  cursor: pointer;
}
.confirm-cancel {
  border: 1px solid var(--border-dark);
  background: #fff;
  color: var(--text-secondary);
}
.confirm-cancel:hover {
  border-color: var(--primary);
  color: var(--primary);
}
.confirm-submit {
  border: 0;
  background: var(--primary-gradient);
  color: #fff;
  box-shadow: 0 4px 12px rgba(255, 90, 44, 0.28);
}
.confirm-submit.danger {
  background: var(--danger-gradient);
  box-shadow: 0 4px 12px rgba(229, 57, 53, 0.25);
}
.confirm-fade-enter-active,
.confirm-fade-leave-active {
  transition: opacity 0.15s;
}
.confirm-fade-enter-active .confirm-card,
.confirm-fade-leave-active .confirm-card {
  transition: transform 0.15s;
}
.confirm-fade-enter-from,
.confirm-fade-leave-to {
  opacity: 0;
}
.confirm-fade-enter-from .confirm-card,
.confirm-fade-leave-to .confirm-card {
  transform: translateY(8px) scale(0.98);
}
</style>
