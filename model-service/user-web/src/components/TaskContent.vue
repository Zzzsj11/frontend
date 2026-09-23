<script setup lang="ts">
import type { TaskContent } from '../stores/portal'
defineProps<{ content?: TaskContent; empty: string }>()
const roles: Record<string, string> = {
  user: '用户',
  system: '系统',
  developer: '开发者',
  assistant: '模型',
  negative: '负面提示词',
  first_frame: '首帧',
  last_frame: '尾帧',
  reference_image: '参考图',
  reference_video: '参考视频',
  reference_audio: '参考音频',
}
function safeUrl(value?: string) {
  try {
    const url = new URL(value || '')
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password
      ? value
      : undefined
  } catch {
    return undefined
  }
}
</script>
<template>
  <div class="task-content">
    <div v-for="(item, index) in content?.texts" :key="index" class="text-block">
      <span class="muted">{{ roles[item.role] || '文本' }}</span>
      <pre>{{ item.text }}</pre>
    </div>
    <div v-if="content?.media.length" class="media-grid">
      <figure v-for="(item, index) in content.media" :key="index">
        <template v-if="safeUrl(item.url)">
          <img
            v-if="item.kind === 'image'"
            :src="safeUrl(item.thumbnail_url) || safeUrl(item.url)"
            :alt="(roles[item.role] || '图片') + (index + 1)"
            loading="lazy"
            referrerpolicy="no-referrer"
          />
          <video
            v-else-if="item.kind === 'video'"
            :src="safeUrl(item.url)"
            :poster="safeUrl(item.thumbnail_url)"
            controls
            preload="none"
          />
          <audio
            v-else-if="item.kind === 'audio'"
            :src="safeUrl(item.url)"
            controls
            preload="none"
          />
          <figcaption>
            {{
              roles[item.role] ||
              { image: '图片', video: '视频', audio: '音频' }[item.kind] ||
              '素材'
            }}
            {{ index + 1 }} ·
            <a :href="safeUrl(item.url)" target="_blank" rel="noopener noreferrer">打开原文件</a>
          </figcaption>
        </template>
      </figure>
    </div>
    <p v-if="!content?.texts.length && !content?.media.length" class="muted">{{ empty }}</p>
  </div>
</template>
<style scoped>
.text-block {
  padding: 14px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  margin-bottom: 12px;
}
pre {
  margin: 8px 0 0;
  font: inherit;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
}
.media-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr));
  gap: 16px;
}
figure {
  margin: 0;
  min-width: 0;
}
img,
video {
  display: block;
  width: 100%;
  max-height: 360px;
  object-fit: contain;
  background: var(--bg);
  border-radius: var(--radius-sm);
}
audio {
  width: 100%;
}
figcaption {
  margin-top: 8px;
  font-size: 13px;
  color: var(--muted);
}
a {
  color: var(--primary);
}
</style>
