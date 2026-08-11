<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ src?: string; alt?: string }>()

const backgroundImage = computed(() => (props.src ? `url(${JSON.stringify(props.src)})` : 'none'))
</script>

<template>
  <span
    class="character-portrait"
    role="img"
    :aria-label="alt || '人物头像'"
    :style="{ backgroundImage }"
  />
</template>

<style scoped>
.character-portrait {
  display: block;
  width: 100%;
  height: 100%;
  flex: none;
  background-color: var(--surface-muted);
  background-repeat: no-repeat;
  background-position: left 38%;
  background-size: 220% auto;
}
</style>
