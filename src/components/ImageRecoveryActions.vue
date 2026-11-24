<script setup lang="ts">
import { topModalPanel } from '../composables/useModalStack'
import { imageRecoveryActions } from '../utils/imageGenerationRecovery'
</script>

<template>
  <Teleport :to="topModalPanel || 'body'">
    <aside
      v-if="imageRecoveryActions.size"
      class="image-recovery"
      :class="{ 'is-in-modal': topModalPanel }"
      aria-label="图片生成状态"
    >
      <article v-for="[id, action] in imageRecoveryActions" :key="id">
        <strong>{{ action.target }}</strong>
        <p role="status">{{ action.message }}</p>
        <div class="image-actions">
          <button v-if="action.dismiss" @click="action.dismiss">取消</button>
          <button class="image-action" @click="action.run">{{ action.label }}</button>
        </div>
      </article>
    </aside>
  </Teleport>
</template>

<style scoped>
.image-recovery {
  position: fixed;
  inset: auto 24px 24px auto;
  z-index: var(--z-dropdown);
  width: min(360px, calc(100vw - 48px));
  max-height: 45vh;
  overflow: auto;
  display: grid;
  gap: 8px;
}
.image-recovery.is-in-modal {
  position: static;
  flex: 0 0 auto;
  width: 100%;
  max-height: 30vh;
  padding: 8px 16px;
}
.image-recovery article {
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-modal);
  background: var(--palette-ffffff);
  color: var(--text);
  padding: 16px;
}
.image-recovery p {
  margin: 6px 0 12px;
}
.image-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.image-actions button {
  padding: 6px 12px;
  border: 0;
  border-radius: var(--radius-md);
  cursor: pointer;
}
.image-action {
  background: var(--primary);
  color: var(--palette-ffffff);
}
</style>
