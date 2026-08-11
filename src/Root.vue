<script setup lang="ts">
import { useAuthStore } from './stores/auth'
import ErrorDialog from './components/ErrorDialog.vue'
import AppHeader from './components/AppHeader.vue'
const auth = useAuthStore()
</script>
<template>
  <ErrorDialog />
  <div v-if="!auth.ready" class="boot">正在加载…</div>
  <template v-else
    ><div v-if="auth.authenticated" class="authenticated-shell">
      <AppHeader />
      <main class="route-shell"><RouterView /></main>
    </div>
    <RouterView v-else
  /></template>
</template>
<style scoped>
.boot {
  min-height: 100vh;
  display: grid;
  place-items: center;
  color: var(--text-secondary);
}
.authenticated-shell {
  display: flex;
  height: 100vh;
  height: 100dvh;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
}
.route-shell {
  min-height: 0;
  flex: 1;
  overflow: auto;
}
.route-shell:has(.app-layout) {
  overflow: hidden;
}
</style>
