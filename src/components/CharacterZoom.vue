<script setup lang="ts">
import { computed } from 'vue'
import type { DigitalHuman } from '../types'
import ImageZoom from './ImageZoom.vue'
const props = defineProps<{ human: DigitalHuman; humans?: DigitalHuman[] }>()
const items = computed(() =>
  (props.humans?.length ? props.humans : [props.human]).map((human) => ({
    src: human.originalAvatar || human.avatar,
    thumbnail: human.avatar,
    alt: `${human.name} · 人物参考图`,
  })),
)
const index = computed(() =>
  Math.max(
    0,
    (props.humans || []).findIndex((human) => human.id === props.human.id),
  ),
)
</script>
<template>
  <ImageZoom
    :src="human.originalAvatar || human.avatar"
    :alt="`${human.name} · 人物参考图`"
    :label="`查看${human.name}大图`"
    :items="items"
    :index="index"
  />
</template>
