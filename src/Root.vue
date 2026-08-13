<script setup lang="ts">
import { useAuthStore } from './stores/auth'
import ErrorDialog from './components/ErrorDialog.vue'
import AppHeader from './components/AppHeader.vue'
import ImagePreviewOverlay from './components/ImagePreviewOverlay.vue'
const auth = useAuthStore()
</script>
<template>
  <ErrorDialog />
  <!-- 全局唯一图片预览遮罩（P3b）：各处的 ImageZoom 只是触发按钮 -->
  <ImagePreviewOverlay />
  <div v-if="!auth.ready" class="boot">正在加载…</div>
  <!-- 只保留单个 RouterView：若按认证状态切换两个 RouterView，退出登录瞬间路由仍是
       /projects，裸 RouterView 会重新挂载 App.vue，重放 SongSidebar 的 loadSongProjects
       等初始化请求，此时 token 已清空 → 401 → refresh 失败 → 误弹“登录已过期” -->
  <div v-else class="app-shell" :class="{ authenticated: auth.authenticated }">
    <AppHeader v-if="auth.authenticated" />
    <main class="route-shell"><RouterView /></main>
  </div>
</template>
<style scoped>
.boot {
  min-height: 100vh;
  display: grid;
  place-items: center;
  color: var(--text-secondary);
}
.app-shell {
  min-height: 0;
}
.app-shell.authenticated {
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
