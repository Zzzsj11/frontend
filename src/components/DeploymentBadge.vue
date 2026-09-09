<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getReleaseInfo, type ReleaseInfo } from '../api/release'
import { formatChinaDateTime } from '../utils/dateTime'

const props = defineProps<{ currentVersion?: string; checkIntervalMs?: number }>()

const DEFAULT_CHECK_INTERVAL_MS = 90_000
const buildVersion = String(import.meta.env.VITE_RELEASE_VERSION || 'development').trim()
const release = ref<ReleaseInfo | null>(null)
const checking = ref(true)
let timer = 0
let controller: AbortController | null = null
let stopped = false

const localVersion = computed(() => props.currentVersion?.trim() || buildVersion)
const remoteVersion = computed(() => release.value?.version?.trim() || '')
const canCompareVersions = computed(
  () => localVersion.value !== 'development' && Boolean(remoteVersion.value),
)
const updateAvailable = computed(
  () => canCompareVersions.value && localVersion.value !== remoteVersion.value,
)
const shortVersion = (version: string) => version.replace(/^git-/, '').slice(0, 7)
const completedAt = computed(() => {
  if (!release.value?.deployedAt)
    return localVersion.value === 'development' ? '本地' : shortVersion(localVersion.value)
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(release.value.deployedAt))
})
const fullTitle = computed(() => {
  if (updateAvailable.value) {
    const latestTime = release.value?.deployedAt
      ? `${formatChinaDateTime(release.value.deployedAt)}（北京时间）`
      : '未知'
    return `发现新版本，点击刷新\n当前版本：${shortVersion(localVersion.value)}\n最新版本：${shortVersion(remoteVersion.value)}\n最近更新：${latestTime}`
  }
  if (!release.value?.deployedAt) {
    if (checking.value) return '正在检查是否有新版本'
    return `版本检查暂不可用\n当前构建：${shortVersion(localVersion.value) || '本地'}`
  }
  return `最近部署完成：${formatChinaDateTime(release.value.deployedAt)}（北京时间）\n版本标识：${shortVersion(remoteVersion.value)}`
})

const clearTimer = () => {
  window.clearTimeout(timer)
  timer = 0
}
const scheduleCheck = () => {
  clearTimer()
  if (document.hidden) return
  timer = window.setTimeout(checkRelease, props.checkIntervalMs ?? DEFAULT_CHECK_INTERVAL_MS)
}
const checkRelease = async () => {
  if (controller) return
  controller = new AbortController()
  checking.value = true
  try {
    release.value = await getReleaseInfo(controller.signal)
  } catch {
    if (!release.value) release.value = { version: null, deployedAt: null }
  } finally {
    controller = null
    checking.value = false
    if (!stopped) scheduleCheck()
  }
}
const handleVisibilityChange = () => {
  if (document.hidden) clearTimer()
  else void checkRelease()
}
const refreshPage = () => window.location.reload()

onMounted(() => {
  void checkRelease()
  document.addEventListener('visibilitychange', handleVisibilityChange)
  window.addEventListener('online', checkRelease)
})
onBeforeUnmount(() => {
  stopped = true
  clearTimer()
  controller?.abort()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  window.removeEventListener('online', checkRelease)
})
</script>

<template>
  <button
    v-if="updateAvailable"
    type="button"
    class="deployment-badge update-available"
    :title="fullTitle"
    data-test="deployment-badge"
    aria-label="发现新版本，点击刷新页面"
    @click="refreshPage"
  >
    <span class="status-dot" aria-hidden="true"></span>
    <span class="desktop-label">发现新版本，点击刷新</span>
    <span class="mobile-label">新版本，刷新</span>
  </button>
  <span v-else class="deployment-badge" :title="fullTitle" data-test="deployment-badge">
    <span class="status-dot" :class="{ checking }" aria-hidden="true"></span>
    {{
      checking && !release
        ? '正在检查版本'
        : `部署 ${completedAt} · ${shortVersion(remoteVersion) || '本地'}`
    }}
  </span>
</template>

<style scoped>
.deployment-badge {
  display: inline-flex;
  height: 28px;
  align-items: center;
  gap: 6px;
  padding: 0 9px;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: var(--bg);
  color: var(--text-secondary);
  font-size: var(--font-sm);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.deployment-badge.update-available {
  border-color: var(--warning-border);
  background: var(--warning-light);
  color: var(--warning);
  cursor: pointer;
}
.deployment-badge.update-available:hover {
  border-color: var(--warning);
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: var(--radius-pill);
  background: var(--success);
}
.status-dot.checking {
  background: var(--text-secondary);
}
.update-available .status-dot {
  background: var(--warning);
}
.mobile-label {
  display: none;
}
@media (max-width: 900px) {
  .deployment-badge:not(.update-available) {
    display: none;
  }
}
@media (max-width: 639px) {
  .desktop-label {
    display: none;
  }
  .mobile-label {
    display: inline;
  }
}
</style>
