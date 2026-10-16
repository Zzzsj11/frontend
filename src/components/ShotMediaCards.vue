<script setup lang="ts">
import { computed } from 'vue'
import type { DigitalHuman, ScriptLine } from '../types'
import AppIcon from './AppIcon.vue'
import CharacterPortrait from './CharacterPortrait.vue'
import { openImageGallery, type PreviewImage } from '../composables/useImagePreview'
const props = defineProps<{
  line: ScriptLine
  humans: DigitalHuman[]
  showsCast: boolean
  activeTab: string | null
  cover?: string
  video?: string
  versions: number
}>()
const emit = defineEmits<{ edit: [tab: 'cast' | 'shot' | 'scene']; video: [] }>()
const gallery = computed<PreviewImage[]>(() => [
  ...(props.line.scene.imageUrl
    ? [
        {
          src: props.line.scene.originalImageUrl || props.line.scene.imageUrl,
          thumbnail: props.line.scene.imageUrl,
          alt: '场景图',
        },
      ]
    : []),
  ...props.humans.map((human) => ({
    src: human.originalAvatar || human.avatar,
    thumbnail: human.avatar,
    alt: `${human.name} · 人物参考图`,
  })),
])
const showScene = () => {
  if (props.line.scene.imageUrl) openImageGallery(gallery.value, 0)
  else emit('edit', 'scene')
}
const showHuman = (index: number) =>
  openImageGallery(gallery.value, index + (props.line.scene.imageUrl ? 1 : 0))
const showVideo = () => {
  if (props.video) emit('video')
  else emit('edit', 'shot')
}
const currentModel = computed(
  () => props.line.shot.assets.find((asset) => asset.id === props.line.shot.currentAssetId)?.model,
)
</script>
<template>
  <div class="preview-cards" :class="{ 'without-cast': !showsCast }">
    <div v-if="showsCast" class="pcard" :class="{ open: activeTab === 'cast' }">
      <div class="pcard-media">
        <div v-if="humans.length" class="pcard-avatars">
          <button
            v-for="(human, index) in humans"
            :key="human.id"
            class="portrait-preview"
            :aria-label="`查看${human.name}大图`"
            :title="`查看${human.name}大图`"
            @click="showHuman(index)"
          >
            <CharacterPortrait :src="human.avatar" :alt="human.name" /><span class="preview-corner"
              ><AppIcon name="zoom-in" :size="14"
            /></span>
          </button>
        </div>
        <span v-else class="pcard-empty"><AppIcon name="user" :size="24" />空镜头</span>
      </div>
      <button
        class="pcard-tab"
        :class="{ active: activeTab === 'cast' }"
        @click="emit('edit', 'cast')"
      >
        <AppIcon name="users" :size="13" />人物 <span>{{ humans.length }}</span>
      </button>
    </div>
    <div class="pcard" :class="{ open: activeTab === 'shot' }">
      <button
        class="pcard-media media-button"
        :aria-label="video ? '播放当前视频' : '展开视频调整'"
        @click="showVideo"
      >
        <img v-if="cover" :src="cover" alt="视频预览" /><video
          v-else-if="video"
          :src="video"
          preload="metadata"
          muted
        />
        <span v-else class="pcard-empty"><AppIcon name="movie" :size="24" />暂无视频</span>
        <span v-if="video" class="preview-corner"><AppIcon name="play" :size="17" /></span>
        <span v-if="versions > 1" class="version-badge">{{ versions }} 版</span>
        <span v-if="currentModel?.startsWith('minimax-h3')" class="model-badge">H3</span>
        <span v-if="line.shot.status === 'generating'" class="media-state">视频生成中…</span>
        <span v-if="line.shot.status === 'failed'" class="media-state" :title="line.shot.error"
          >视频生成失败</span
        >
      </button>
      <button
        class="pcard-tab"
        :class="{ active: activeTab === 'shot' }"
        @click="emit('edit', 'shot')"
      >
        <AppIcon name="movie" :size="13" />视频
      </button>
    </div>
    <div class="pcard" :class="{ open: activeTab === 'scene' }">
      <div class="scene-preview">
        <button
          class="pcard-media media-button"
          :aria-label="line.scene.imageUrl ? '查看场景大图' : '展开场景调整'"
          @click="showScene"
        >
          <img v-if="line.scene.imageUrl" :src="line.scene.imageUrl" alt="场景预览" /><span
            v-if="line.scene.imageUrl"
            class="preview-corner"
            ><AppIcon name="zoom-in" :size="17" /></span
          ><span v-else class="pcard-empty"><AppIcon name="scene" :size="24" />暂无场景</span>
          <span v-if="line.scene.status === 'generating'" class="media-state">场景生成中…</span
          ><span v-if="line.scene.status === 'failed'" class="media-state" :title="line.scene.error"
            >场景生成失败</span
          >
        </button>
      </div>
      <button
        class="pcard-tab"
        :class="{ active: activeTab === 'scene' }"
        @click="emit('edit', 'scene')"
      >
        <AppIcon name="scene" :size="13" />场景
      </button>
    </div>
  </div>
</template>
<style scoped>
.preview-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.preview-cards.without-cast {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.pcard {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.pcard.open {
  border-color: var(--primary);
  box-shadow: 0 0 0 1px var(--primary);
}
.pcard-media {
  position: relative;
  height: 96px;
  background: var(--surface-dark);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.media-button {
  width: 100%;
  padding: 0;
  border: 0;
  cursor: pointer;
}
.media-button > img,
.media-button > video {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.pcard-avatars {
  display: flex;
  gap: 4px;
  padding: 6px;
  width: 100%;
  justify-content: center;
}
.portrait-preview {
  position: relative;
  flex: 1;
  min-width: 0;
  max-width: 100px;
  height: 72px;
  padding: 0;
  border: 1px solid var(--preview-border);
  border-radius: var(--radius-sm);
  overflow: hidden;
  cursor: zoom-in;
}
.preview-corner {
  position: absolute;
  top: 5px;
  right: 5px;
  padding: 3px;
  display: flex;
  border-radius: var(--radius-xs);
  background: var(--preview-control);
  color: var(--preview-text);
}
.pcard-empty {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: center;
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.pcard-tab {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 0;
  border-top: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  font-weight: 600;
  padding: 8px 6px;
  cursor: pointer;
}
.pcard-tab.active {
  background: var(--primary);
  color: var(--preview-text);
}
.scene-preview {
  position: relative;
}
.version-badge {
  position: absolute;
  bottom: 4px;
  right: 4px;
  color: var(--preview-text);
  background: var(--preview-control);
  border-radius: var(--radius-xs);
  padding: 2px;
  font-size: var(--font-sm);
}
.model-badge {
  position: absolute;
  top: 5px;
  left: 5px;
  padding: 3px 6px;
  background: var(--primary);
  color: var(--preview-text);
  border-radius: var(--radius-sm);
  font-size: var(--font-sm);
}
.media-state {
  position: absolute;
  bottom: 0;
  inset-inline: 0;
  padding: 5px;
  font-size: var(--font-sm);
  background: var(--preview-control);
  color: var(--preview-text);
}
@media (max-width: 480px) {
  .pcard-media {
    height: 84px;
  }
  .portrait-preview {
    height: 62px;
  }
}
</style>
