<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{ src?: string; alt?: string }>()
const legacySheet = ref(false)

watch(
  () => props.src,
  () => {
    legacySheet.value = false
  },
)

const onLoad = (event: Event) => {
  const image = event.target as HTMLImageElement
  // 历史身份卡是横版多视图，私有旧卡手动更新前仍需裁出左侧正脸。
  legacySheet.value = image.naturalWidth / image.naturalHeight >= 1.5
}
</script>

<template>
  <span
    class="character-portrait"
    :class="{ 'legacy-sheet': legacySheet }"
    role="img"
    :aria-label="alt || '人物头像'"
  >
    <img v-if="src" :key="src" :src="src" alt="" aria-hidden="true" @load="onLoad" />
  </span>
</template>

<style scoped>
.character-portrait {
  position: relative;
  display: block;
  width: 100%;
  height: 100%;
  flex: none;
  overflow: hidden;
  background-color: var(--surface-muted);
}

.character-portrait img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center top;
}

.character-portrait.legacy-sheet img {
  position: absolute;
  left: 0;
  top: 38%;
  width: 220%;
  max-width: none;
  height: auto;
  transform: translateY(-38%);
}
</style>
