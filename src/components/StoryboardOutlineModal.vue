<script setup lang="ts">
import { ref } from 'vue'
import { useProjectStore } from '../stores/project'
import { confirmDialog } from '../composables/useConfirmDialog'
import AppIcon from './AppIcon.vue'
import BaseModal from './base/BaseModal.vue'

const store = useProjectStore()

const tab = ref<'scenes' | 'shots'>('shots')

const roleNames = (ids: string[] = []) =>
  ids.map((id) => store.digitalHumanOf(id)?.name || id).join('、')
const roleIdsOf = (shot: NonNullable<typeof store.activeStoryBible>['shots'][number]) =>
  shot.requiredCharacterIds || shot.preferredCharacterIds || []
const shotTypeOf = (shot: NonNullable<typeof store.activeStoryBible>['shots'][number]) =>
  shot.shotType || (roleIdsOf(shot).length ? 'character' : 'empty')
const locationOf = (id?: string) =>
  store.activeStoryBible?.locations?.find((item) => item.id === id)
const motifNames = (ids: string[] = []) =>
  ids
    .map((id) => store.activeStoryBible?.motifs?.find((item) => item.id === id)?.name || id)
    .join('、')
/** 历史任务的约束文案混入了内部字段名，展示时替换为中文（新建任务后端已直接输出中文） */
const POLICY_TERM_ZH: Record<string, string> = {
  requiredCharacterIds: '预分配角色',
  shotType: '镜头类型',
  locationId: '地点',
  characterAction: '人物动作',
}
const displayPolicy = (text: string) =>
  text.replace(
    /requiredCharacterIds|shotType|locationId|characterAction/g,
    (term) => POLICY_TERM_ZH[term] ?? term,
  )
const regenerate = async () => {
  if (
    !(await confirmDialog({
      title: '重新生成 MV 大纲',
      message:
        '重新生成后，每段视频的人物/空镜规划和人物分配都会更新，现有视频提示词将重新生成。是否继续？',
      confirmText: '重新生成',
    }))
  )
    return
  await store.regenerateOutline()
}
</script>

<template>
  <BaseModal
    :open="store.outlineOpen && !!store.activeStoryBible"
    :loading="store.outlineLocked"
    width="900px"
    max-height="90vh"
    aria-label="MV 大纲总览"
    @close="store.closeOutline()"
  >
    <template #title> <AppIcon name="file" :size="17" /> MV 大纲总览 </template>
    <template v-if="store.activeStoryBible">
      <!-- Tab 切换 -->
      <nav class="outline-tabs">
        <button :class="{ active: tab === 'scenes' }" @click="tab = 'scenes'">场景总览</button>
        <button :class="{ active: tab === 'shots' }" @click="tab = 'shots'">逐镜大纲</button>
      </nav>

      <!-- 场景总览 Tab -->
      <template v-if="tab === 'scenes'">
        <div v-if="store.activeStoryBible.scenePlan?.length" class="scene-list">
          <div v-if="store.activeStoryBible.globalVisual" class="global-visual">
            <h4>全片视觉基调</h4>
            <dl>
              <template v-for="(v, k) in store.activeStoryBible.globalVisual" :key="k">
                <dt>
                  {{
                    {
                      visualStyle: '视觉风格',
                      colorPalette: '调色板',
                      lighting: '光线',
                      weather: '天气',
                      timeOfDay: '时间',
                      continuityRules: '连续性规则',
                    }[k] || k
                  }}
                </dt>
                <dd>{{ Array.isArray(v) ? v.join('；') : v }}</dd>
              </template>
            </dl>
          </div>
          <article
            v-for="scene in store.activeStoryBible.scenePlan"
            :key="scene.sceneIndex"
            class="scene-card"
          >
            <div class="scene-index">{{ String(scene.sceneIndex + 1).padStart(2, '0') }}</div>
            <div class="scene-body">
              <div class="scene-head">
                <strong>{{ scene.locationName }}</strong>
                <span class="scene-range"
                  >第 {{ (scene.lineStart ?? 0) + 1 }} – {{ (scene.lineEnd ?? 0) + 1 }} 句</span
                >
              </div>
              <div class="scene-attrs">
                <span v-if="scene.mood"><b>意境：</b>{{ scene.mood }}</span>
                <span v-if="scene.emotion"><b>情绪：</b>{{ scene.emotion }}</span>
                <span v-if="scene.visualTone"><b>视觉基调：</b>{{ scene.visualTone }}</span>
                <span v-if="scene.narrativePurpose"
                  ><b>叙事功能：</b>{{ scene.narrativePurpose }}</span
                >
                <span
                  v-for="(outfit, humanId) in scene.wardrobeByCharacter"
                  :key="humanId"
                  class="wardrobe-item"
                  ><b>{{ roleNames([humanId]) }}服装：</b>{{ outfit }}</span
                >
              </div>
            </div>
          </article>
        </div>
        <p v-else class="empty-tab">暂无场景规划数据</p>
      </template>

      <!-- 逐镜大纲 Tab（原内容） -->
      <template v-if="tab === 'shots'">
        <p class="outline-sub">{{ store.activeStoryBible.logline }}</p>
        <div class="policy">{{ displayPolicy(store.activeStoryBible.characterPolicy) }}</div>
        <div v-if="store.failedOutlineSegments.length" class="failed-segments">
          <div
            v-for="seg in store.failedOutlineSegments"
            :key="seg.sceneIndex"
            class="failed-segment"
          >
            <span class="failed-text" :title="seg.error"
              >场景{{ seg.sceneIndex + 1 }}「{{
                seg.locationName
              }}」大纲生成失败，该段镜头已保留占位</span
            >
            <button
              :disabled="!!store.segmentRetrying[seg.sceneIndex]"
              @click="store.retryOutlineSegment(seg.sceneIndex)"
            >
              {{ store.segmentRetrying[seg.sceneIndex] ? '正在重新生成…' : '重新生成该场景段' }}
            </button>
          </div>
        </div>
        <div class="outline-list">
          <article
            v-for="shot in store.activeStoryBible.shots"
            :key="shot.index"
            class="outline-shot"
            :class="{ 'is-failed': shot.outlineStatus === 'failed' }"
          >
            <div class="shot-index">{{ String(shot.index + 1).padStart(2, '0') }}</div>
            <div class="shot-content">
              <div class="shot-head">
                <strong>{{ shot.stage }}</strong>
                <span :class="['shot-type', shotTypeOf(shot)]">{{
                  shotTypeOf(shot) === 'character' ? '人物镜' : '空镜'
                }}</span>
                <span v-if="shot.outlineStatus === 'failed'" class="failed-tag">大纲未生成</span>
                <span v-if="shot.generationDuration" class="duration-tag"
                  >生成 {{ shot.generationDuration }} 秒</span
                >
              </div>
              <p v-if="shot.lyrics || shot.timelineLabel" class="lyrics">
                {{ shot.lyrics || `【${shot.timelineLabel}】` }}
              </p>
              <p class="intent">
                {{
                  shot.intent || [shot.outlineScene, shot.outlineShot].filter(Boolean).join('；')
                }}
              </p>
              <p class="roles">
                出场人物：{{
                  shotTypeOf(shot) === 'character'
                    ? roleNames(roleIdsOf(shot)) || '尚未分配'
                    : '无人'
                }}
              </p>
              <div v-if="shot.locationId || shot.characterAction" class="shot-contract">
                <span v-if="shot.locationId"
                  ><b>场景：</b>{{ locationOf(shot.locationId)?.name || shot.locationId
                  }}{{ shot.locationChange ? ' · 切换地点' : ' · 延续地点' }}</span
                >
                <span v-if="shot.characterAction"><b>动作：</b>{{ shot.characterAction }}</span>
                <span v-if="shot.emotionalFocus"><b>情绪：</b>{{ shot.emotionalFocus }}</span>
                <span v-if="shot.cameraPurpose"><b>镜头目的：</b>{{ shot.cameraPurpose }}</span>
                <span v-if="shot.motifIds?.length"
                  ><b>视觉母题：</b>{{ motifNames(shot.motifIds) }}</span
                >
                <span v-for="(outfit, humanId) in shot.wardrobeByCharacter" :key="humanId"
                  ><b>{{ roleNames([humanId]) }}服装：</b>{{ outfit }}</span
                >
                <span v-if="shot.sourceDuration !== undefined"
                  ><b>歌词显示：</b>{{ shot.sourceDuration }} 秒</span
                >
                <span v-if="shot.gapBefore"><b>前间隙：</b>{{ shot.gapBefore }} 秒</span>
                <span v-if="shot.gapAfter"
                  ><b>后间隙：</b>{{ shot.gapAfter }} 秒 ·
                  {{
                    shot.gapAfterAllocation === 'current'
                      ? '归入本镜'
                      : shot.gapAfterAllocation === 'next'
                        ? '归入下镜'
                        : '不合并'
                  }}</span
                >
                <span v-if="shot.materialDuration !== undefined"
                  ><b>时间轴素材：</b>{{ shot.materialDuration }} 秒</span
                >
              </div>
            </div>
          </article>
        </div>
        <p v-if="store.outlineError" class="outline-error">{{ store.outlineError }}</p>
      </template>
    </template>
    <template #footer>
      <span class="outline-tip">该大纲将指导后续每条视频提示词生成，只支持查看。</span>
      <button
        v-if="store.activeStoryboardType === 'ass'"
        class="regenerate"
        :disabled="store.outlineLocked"
        @click="regenerate"
      >
        <span v-if="store.outlineLocked" class="spinner" />{{
          store.outlineLocked ? '正在重新规划…' : '不满意，重新生成'
        }}
      </button>
      <button class="close" :disabled="store.outlineLocked" @click="store.closeOutline()">
        关闭
      </button>
    </template>
  </BaseModal>
</template>

<style scoped>
/* ---------- Tabs ---------- */
.outline-tabs {
  display: flex;
  gap: 0;
  margin: 10px 20px 0;
  border-bottom: 2px solid var(--border-light, #eee);
}
.outline-tabs button {
  border: none;
  background: transparent;
  color: var(--text-secondary);
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  transition:
    color 0.15s,
    border-color 0.15s;
}
.outline-tabs button:hover {
  color: var(--text);
}
.outline-tabs button.active {
  color: var(--primary);
  border-bottom-color: var(--primary);
}

/* ---------- 场景总览 ---------- */
.scene-list {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  gap: 9px;
  overflow: auto;
  padding: 14px 20px;
}
.global-visual {
  margin-bottom: 6px;
  padding: 12px 14px;
  border-radius: var(--radius-md);
  background: #f8f5f0;
}
.global-visual h4 {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--text);
}
.global-visual dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 12px;
  margin: 0;
}
.global-visual dt {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.global-visual dd {
  margin: 0;
  font-size: 12px;
  color: var(--text);
  line-height: 1.5;
}
.scene-card {
  display: flex;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: #fff;
}
.scene-index {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: var(--radius-sm);
  background: var(--primary-light);
  color: var(--primary);
  font-size: var(--font-sm);
  font-weight: 750;
}
.scene-body {
  min-width: 0;
  flex: 1;
}
.scene-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.scene-head strong {
  font-size: 13px;
}
.scene-range {
  font-size: 11px;
  color: var(--text-secondary);
}
.scene-attrs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 12px;
  margin-top: 7px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: #faf8f6;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-secondary);
}
.scene-attrs b {
  color: var(--text);
  font-weight: 650;
}
.empty-tab {
  padding: 40px 20px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 13px;
}

.outline-sub {
  margin: 14px 20px 0;
  color: var(--text-secondary);
  font-size: 13px;
}
.policy {
  margin: 14px 20px 0;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--primary-light);
  color: #a84d20;
  font-size: var(--font-sm);
  line-height: 1.6;
}
.outline-list {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  gap: 9px;
  overflow: auto;
  padding: 14px 20px;
}
.outline-shot {
  display: flex;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: #fff;
}
.shot-index {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: var(--radius-sm);
  background: var(--primary-light);
  color: var(--primary);
  font-size: var(--font-sm);
  font-weight: 750;
}
.shot-content {
  min-width: 0;
  flex: 1;
}
.shot-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.shot-head strong {
  font-size: 13px;
}
.shot-type {
  padding: 2px 7px;
  border-radius: var(--radius-sm);
  font-size: 10px;
  font-weight: 700;
}
.shot-type.character {
  background: var(--primary-light);
  color: var(--primary);
}
.shot-type.empty {
  background: #eef3f5;
  color: #62727a;
}
.duration-tag {
  padding: 2px 7px;
  border-radius: var(--radius-sm);
  background: var(--info-light);
  color: var(--info);
  font-size: 10px;
  font-weight: 700;
}
.lyrics,
.intent,
.roles {
  margin: 5px 0 0;
  font-size: var(--font-sm);
  line-height: 1.55;
}
.lyrics {
  color: var(--text);
  font-weight: 600;
}
.intent {
  color: var(--text-secondary);
}
.roles {
  color: #9b664b;
}
.failed-segments {
  margin: 12px 20px 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.failed-segment {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid var(--danger-border);
  border-radius: var(--radius-sm);
  background: var(--primary-light);
  color: var(--danger-active);
  font-size: var(--font-sm);
}
.failed-segment .failed-text {
  min-width: 0;
  word-break: break-all;
}
.failed-segment button {
  flex-shrink: 0;
  border: 1px solid currentColor;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  padding: 3px 10px;
  font-size: var(--font-sm);
  cursor: pointer;
}
.failed-segment button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.outline-shot.is-failed {
  border-style: dashed;
  opacity: 0.75;
}
.failed-tag {
  padding: 2px 7px;
  border-radius: var(--radius-sm);
  background: var(--danger-light);
  color: var(--danger-active);
  font-size: 10px;
  font-weight: 700;
}
.shot-contract {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 12px;
  margin-top: 7px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: #faf8f6;
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.5;
}
.shot-contract b {
  color: var(--text);
  font-weight: 650;
}
.outline-error {
  margin: 0 20px 10px;
  color: var(--danger);
  font-size: var(--font-sm);
}
.outline-tip {
  margin-right: auto;
  color: var(--text-secondary);
  font-size: 11px;
}
.regenerate,
.close {
  padding: 7px 13px;
  border-radius: var(--radius-sm);
  font-size: var(--font-sm);
  cursor: pointer;
}
.regenerate {
  border: 1px solid var(--primary-border);
  background: var(--primary-light);
  color: #dc5c28;
}
.close {
  border: 0;
  background: var(--primary);
  color: #fff;
}
button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
@media (max-width: 650px) {
  .shot-contract {
    grid-template-columns: 1fr;
  }
}
</style>
