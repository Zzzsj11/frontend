<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getReleaseInfo, type ReleaseInfo } from '../api/release'

const release = ref<ReleaseInfo | null>(null)

const shortVersion = computed(
  () => release.value?.version?.replace(/^git-/, '').slice(0, 7) || '本地',
)
const completedAt = computed(() => {
  if (!release.value?.deployedAt) return '未发布'
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
  if (!release.value?.deployedAt) return '当前为本地或未标记的部署版本'
  const fullTime = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    dateStyle: 'medium',
    timeStyle: 'medium',
  }).format(new Date(release.value.deployedAt))
  return `最近部署完成：${fullTime}（北京时间）\n版本：${release.value.version}`
})

onMounted(async () => {
  try {
    release.value = await getReleaseInfo()
  } catch {
    release.value = { version: null, deployedAt: null }
  }
})
</script>

<template>
  <span class="deployment-badge" :title="fullTitle" data-test="deployment-badge">
    <span class="status-dot" aria-hidden="true"></span>
    部署 {{ completedAt }} · {{ shortVersion }}
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
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--success);
}
@media (max-width: 900px) {
  .deployment-badge {
    display: none;
  }
}
</style>
