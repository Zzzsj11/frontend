<script setup lang="ts">
import { useProjectStore } from '../stores/project'
import { confirmDialog } from '../composables/useConfirmDialog'
import AppIcon from './AppIcon.vue'

const store = useProjectStore()
const roleNames = (ids: string[] = []) => ids.map((id) => store.digitalHumanOf(id)?.name || id).join('、')
const roleIdsOf = (shot: NonNullable<typeof store.activeStoryBible>['shots'][number]) => shot.requiredCharacterIds || shot.preferredCharacterIds || []
const shotTypeOf = (shot: NonNullable<typeof store.activeStoryBible>['shots'][number]) => shot.shotType || (roleIdsOf(shot).length ? 'character' : 'empty')
const locationOf = (id?: string) => store.activeStoryBible?.locations?.find((item) => item.id === id)
const motifNames = (ids: string[] = []) => ids.map((id) => store.activeStoryBible?.motifs?.find((item) => item.id === id)?.name || id).join('、')
const regenerate = async () => {
  if (!await confirmDialog({
    title: '重新生成 MV 大纲',
    message: '重新生成后，每段视频的人物/空镜规划和人物分配都会更新，现有视频提示词将重新生成。是否继续？',
    confirmText: '重新生成',
  })) return
  await store.regenerateOutline()
}
</script>

<template>
  <div v-if="store.outlineOpen && store.activeStoryBible" class="outline-mask" @click.self="store.closeOutline()">
    <section class="outline-modal" role="dialog" aria-modal="true" aria-label="MV 大纲总览">
      <header>
        <div><h3><AppIcon name="file" :size="17" /> MV 大纲总览</h3><p>{{ store.activeStoryBible.logline }}</p></div>
        <button title="关闭" aria-label="关闭" @click="store.closeOutline()"><AppIcon name="close" :size="17" /></button>
      </header>
      <div class="policy">{{ store.activeStoryBible.characterPolicy }}</div>
      <div v-if="store.failedOutlineSegments.length" class="failed-segments">
        <div v-for="seg in store.failedOutlineSegments" :key="seg.sceneIndex" class="failed-segment">
          <span class="failed-text" :title="seg.error">场景{{ seg.sceneIndex + 1 }}「{{ seg.locationName }}」大纲生成失败，该段镜头已保留占位</span>
          <button :disabled="!!store.segmentRetrying[seg.sceneIndex]" @click="store.retryOutlineSegment(seg.sceneIndex)">
            {{ store.segmentRetrying[seg.sceneIndex] ? '正在重新生成…' : '重新生成该场景段' }}
          </button>
        </div>
      </div>
      <div class="outline-list">
        <article v-for="shot in store.activeStoryBible.shots" :key="shot.index" class="outline-shot" :class="{ 'is-failed': shot.outlineStatus === 'failed' }">
          <div class="shot-index">{{ String(shot.index + 1).padStart(2, '0') }}</div>
          <div class="shot-content">
            <div class="shot-head">
              <strong>{{ shot.stage }}</strong>
              <span :class="['shot-type', shotTypeOf(shot)]">{{ shotTypeOf(shot) === 'character' ? '人物镜' : '空镜' }}</span>
              <span v-if="shot.outlineStatus === 'failed'" class="failed-tag">大纲未生成</span>
              <span v-if="shot.generationDuration" class="duration-tag">生成 {{ shot.generationDuration }} 秒</span>
            </div>
            <p v-if="shot.lyrics || shot.timelineLabel" class="lyrics">{{ shot.lyrics || `【${shot.timelineLabel}】` }}</p>
            <p class="intent">{{ shot.intent || [shot.outlineScene, shot.outlineShot].filter(Boolean).join('；') }}</p>
            <p class="roles">出场人物：{{ shotTypeOf(shot) === 'character' ? roleNames(roleIdsOf(shot)) || '尚未分配' : '无人' }}</p>
            <div v-if="shot.locationId || shot.characterAction" class="shot-contract">
              <span v-if="shot.locationId"><b>场景：</b>{{ locationOf(shot.locationId)?.name || shot.locationId }}{{ shot.locationChange ? ' · 切换地点' : ' · 延续地点' }}</span>
              <span v-if="shot.characterAction"><b>动作：</b>{{ shot.characterAction }}</span>
              <span v-if="shot.emotionalFocus"><b>情绪：</b>{{ shot.emotionalFocus }}</span>
              <span v-if="shot.cameraPurpose"><b>镜头目的：</b>{{ shot.cameraPurpose }}</span>
              <span v-if="shot.motifIds?.length"><b>视觉母题：</b>{{ motifNames(shot.motifIds) }}</span>
              <span v-if="shot.sourceDuration !== undefined"><b>歌词显示：</b>{{ shot.sourceDuration }} 秒</span>
              <span v-if="shot.gapBefore"><b>前间隙：</b>{{ shot.gapBefore }} 秒</span>
              <span v-if="shot.gapAfter"><b>后间隙：</b>{{ shot.gapAfter }} 秒 · {{ shot.gapAfterAllocation === 'current' ? '归入本镜' : shot.gapAfterAllocation === 'next' ? '归入下镜' : '不合并' }}</span>
              <span v-if="shot.materialDuration !== undefined"><b>时间轴素材：</b>{{ shot.materialDuration }} 秒</span>
            </div>
          </div>
        </article>
      </div>
      <p v-if="store.outlineError" class="outline-error">{{ store.outlineError }}</p>
      <footer>
        <span>该大纲将指导后续每条视频提示词生成，只支持查看。</span>
        <button v-if="store.activeStoryboardType === 'ass'" class="regenerate" :disabled="store.outlineLoading" @click="regenerate">
          <span v-if="store.outlineLoading" class="spinner" />{{ store.outlineLoading ? '正在重新规划…' : '不满意，重新生成' }}
        </button>
        <button class="close" :disabled="store.outlineLoading" @click="store.closeOutline()">关闭</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.outline-mask{position:fixed;inset:0;z-index:1100;display:flex;align-items:center;justify-content:center;padding:28px;background:rgba(20,18,17,.54);backdrop-filter:blur(3px)}.outline-modal{display:flex;width:min(900px,94vw);max-height:90vh;flex-direction:column;overflow:hidden;border-radius:18px;background:#fff;box-shadow:0 28px 80px rgba(0,0,0,.28)}header{display:flex;align-items:flex-start;justify-content:space-between;padding:20px 22px 15px;border-bottom:1px solid var(--border)}header h3{display:flex;align-items:center;gap:8px;margin:0;color:var(--text);font-size:19px}header p{margin:6px 0 0;color:var(--text-secondary);font-size:13px}header button{display:grid;width:30px;height:30px;place-items:center;border:0;border-radius:8px;background:transparent;color:var(--text-secondary);cursor:pointer}.policy{margin:14px 20px 0;padding:10px 12px;border-radius:10px;background:#fff5ed;color:#a84d20;font-size:12px;line-height:1.6}.outline-list{display:flex;flex:1;min-height:0;flex-direction:column;gap:9px;overflow:auto;padding:14px 20px}.outline-shot{display:flex;gap:12px;padding:12px;border:1px solid var(--border);border-radius:12px;background:#fff}.shot-index{display:grid;width:34px;height:34px;flex:0 0 auto;place-items:center;border-radius:10px;background:#fff0e7;color:var(--primary);font-size:12px;font-weight:750}.shot-content{min-width:0;flex:1}.shot-head{display:flex;align-items:center;gap:8px}.shot-head strong{font-size:13px}.shot-type{padding:2px 7px;border-radius:8px;font-size:10px;font-weight:700}.shot-type.character{background:#ffede5;color:#e75b29}.shot-type.empty{background:#eef3f5;color:#62727a}.duration-tag{padding:2px 7px;border-radius:8px;background:#eef7ff;color:#3373a8;font-size:10px;font-weight:700}.lyrics,.intent,.roles{margin:5px 0 0;font-size:12px;line-height:1.55}.lyrics{color:var(--text);font-weight:600}.intent{color:var(--text-secondary)}.roles{color:#9b664b}.failed-segments{margin:12px 20px 0;display:flex;flex-direction:column;gap:8px}.failed-segment{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 12px;border:1px solid #ffd0cc;border-radius:10px;background:#fff5f4;color:#b03a2e;font-size:12px}.failed-segment .failed-text{min-width:0;word-break:break-all}.failed-segment button{flex-shrink:0;border:1px solid currentColor;border-radius:7px;background:transparent;color:inherit;padding:3px 10px;font-size:12px;cursor:pointer}.failed-segment button:disabled{opacity:.55;cursor:not-allowed}.outline-shot.is-failed{border-style:dashed;opacity:.75}.failed-tag{padding:2px 7px;border-radius:8px;background:#fdeceb;color:#c0392b;font-size:10px;font-weight:700}.shot-contract{display:grid;grid-template-columns:1fr 1fr;gap:4px 12px;margin-top:7px;padding:8px 10px;border-radius:8px;background:#faf8f6;color:var(--text-secondary);font-size:11px;line-height:1.5}.shot-contract b{color:var(--text);font-weight:650}.outline-error{margin:0 20px 10px;color:#c33;font-size:12px}footer{display:flex;align-items:center;justify-content:flex-end;gap:9px;padding:13px 20px;border-top:1px solid var(--border)}footer>span:first-child{margin-right:auto;color:var(--text-secondary);font-size:11px}.regenerate,.close{padding:7px 13px;border-radius:9px;font-size:12px;cursor:pointer}.regenerate{border:1px solid #ffc4a7;background:#fff5ef;color:#dc5c28}.close{border:0;background:var(--primary);color:#fff}button:disabled{cursor:not-allowed;opacity:.55}@media(max-width:650px){.shot-contract{grid-template-columns:1fr}}
</style>
