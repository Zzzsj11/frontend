<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { DEFAULT_SHOT_OPTIONS, useProjectStore } from '../stores/project'
import ScriptLineItem from './ScriptLine.vue'
import ShotDetailModal from './ShotDetailModal.vue'
import MagicScriptModal from './MagicScriptModal.vue'
import GeneralStoryboardModal from './GeneralStoryboardModal.vue'
import AppIcon from './AppIcon.vue'
import StoryboardOutlineModal from './StoryboardOutlineModal.vue'
import { apiRequest } from '../api/client'
import type { AccountBalance } from '../stores/auth'
import { confirmDialog } from '../composables/useConfirmDialog'
import { normalizeShotOptions } from '../mediaConstraints'
import { VIDEO_MODEL_OPTIONS } from '../generationModels'
import { estimateVideoBatchCost, estimateVideoBatchCostByProvider } from '../utils/videoBatchCost'

const store = useProjectStore()
const lineListRef = ref<HTMLDivElement>()
const checkingBatchCost = ref(false)

/** 时间线或其他入口选中不可见分镜时，将对应卡片平滑滚动到列表中央 */
watch(
  () => store.selectedLineId,
  async (lineId) => {
    if (!lineId) return
    await nextTick()
    const list = lineListRef.value
    const item = list?.querySelector<HTMLElement>(`[data-line-id="${lineId}"]`)
    if (!list || !item) return
    const listRect = list.getBoundingClientRect()
    const itemRect = item.getBoundingClientRect()
    const outsideView = itemRect.top < listRect.top || itemRect.bottom > listRect.bottom
    if (!outsideView) return
    list.scrollTo({
      top: list.scrollTop + itemRect.top - listRect.top - (list.clientHeight - itemRect.height) / 2,
      behavior: 'smooth',
    })
  },
)

// HTML5 拖拽排序
const dragIndex = ref(-1)
const overIndex = ref(-1)

const onDragStart = (index: number, e: DragEvent) => {
  dragIndex.value = index
  e.dataTransfer!.effectAllowed = 'move'
}
const onDragOver = (index: number, e: DragEvent) => {
  e.preventDefault()
  overIndex.value = index
}
const onDrop = (index: number) => {
  if (dragIndex.value >= 0) store.moveLine(dragIndex.value, index)
  dragIndex.value = -1
  overIndex.value = -1
}
const onDragEnd = () => {
  dragIndex.value = -1
  overIndex.value = -1
}

/** 大纲生成等待：正向计时器 + 百分比估算（阶段进度与时间爬升取大，保证递增不停滞） */
const outlineElapsed = ref(0)
let outlineTimer = 0
watch(
  () => store.outlineLocked,
  (loading) => {
    window.clearInterval(outlineTimer)
    if (loading) {
      outlineElapsed.value = 0
      outlineTimer = window.setInterval(() => {
        outlineElapsed.value = Math.max(0, Date.now() - store.outlineStartedAt)
      }, 1000)
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => window.clearInterval(outlineTimer))

/** 线上 V2 实测：通用约 24 秒，ASS 两阶段约 75 秒。 */
const isGeneralOutline = computed(() => store.activeStoryboardType === 'general')

const outlinePercent = computed(() => {
  const progress = store.outlineProgress
  // 时间爬升：按预估总时长估算，封顶 95%，无进度事件期间也保持缓慢递增
  const estimateSec = isGeneralOutline.value ? 30 : 90
  const timeBased = Math.min(95, (outlineElapsed.value / 1000 / estimateSec) * 100)
  let stageBased = 5
  if (progress?.phase === 'segments' && progress.segmentsTotal)
    stageBased = 15 + 75 * ((progress.segmentsDone ?? 0) / progress.segmentsTotal)
  else if (progress?.phase === 'shots' && progress.stagesTotal)
    stageBased = 10 + 80 * ((progress.stagesDone ?? 0) / progress.stagesTotal)
  else if (progress?.phase === 'planning' || progress?.phase === 'generating') stageBased = 10
  return Math.round(Math.max(timeBased, stageBased))
})

const outlineElapsedText = computed(() => {
  const totalSeconds = Math.floor(outlineElapsed.value / 1000)
  return `${Math.floor(totalSeconds / 60)}:${String(totalSeconds % 60).padStart(2, '0')}`
})

const outlineStageText = computed(() => {
  const progress = store.outlineProgress
  if (isGeneralOutline.value)
    return progress?.shotsTotal ? `共 ${progress.shotsTotal} 个镜头` : '整体规划中'
  if (progress?.phase === 'shots') return '全曲镜头大纲生成中（第 2/2 阶段）'
  if (progress?.phase === 'segments' && progress.segmentsTotal)
    return `分段大纲生成中 ${progress.segmentsDone ?? 0}/${progress.segmentsTotal}`
  return '大场景规划中（第 1/2 阶段）'
})

/** 逐句提示词生成进度（ASS/通用统一） */
const storyboardPercent = computed(() => {
  const { completed, total } = store.storyboardProgress
  return total ? Math.round((completed / total) * 100) : 0
})

/** 可批量生成视频的分镜数：提示词就绪且视频「未生成/失败」（生成中的不计） */
const batchGeneratableLines = computed(() =>
  store.lines.filter(
    (line) =>
      line.generationStatus === 'succeeded' &&
      line.shot.status !== 'done' &&
      line.shot.status !== 'generating',
  ),
)
const batchGeneratableCount = computed(() => batchGeneratableLines.value.length)

const confirmBatchGenerate = async () => {
  if (!batchGeneratableCount.value || checkingBatchCost.value || store.batchShooting) return
  checkingBatchCost.value = true
  try {
    const items = batchGeneratableLines.value.map((line) => {
      const options = normalizeShotOptions(line.shotOptions ?? DEFAULT_SHOT_OPTIONS)
      return { duration: options.duration, model: options.videoModel }
    })
    const { totalSeconds, estimatedCost } = estimateVideoBatchCost(items)
    const providerEstimates = estimateVideoBatchCostByProvider(items)
    const modelCodes = [...new Set(items.map((item) => item.model).filter(Boolean))]
    const modelText = modelCodes
      .map(
        (code) =>
          VIDEO_MODEL_OPTIONS.find((option) => option.value === code)?.label || code || 'SD2.0',
      )
      .join('、')
    const balance = await apiRequest<AccountBalance>('/account/balance?force=true')
    const balanceLines: string[] = []
    let sufficient = true
    for (const [provider, estimate] of Object.entries(providerEstimates)) {
      const providerBalance = balance.providers?.[provider as 'yinghe' | 'ppio'] ?? balance
      const rawRemaining =
        provider === 'ppio'
          ? providerBalance.balance == null
            ? null
            : Number(providerBalance.balance)
          : providerBalance.key?.remaining
      const remaining =
        providerBalance.available && Number.isFinite(rawRemaining) ? Number(rawRemaining) : null
      const unlimited = Boolean(
        provider === 'yinghe' &&
        providerBalance.available &&
        providerBalance.key &&
        providerBalance.key.quotaAmt === null,
      )
      const label = provider === 'ppio' ? 'PPIO' : '英和'
      balanceLines.push(
        `${label}预计 ¥${Number(estimate).toFixed(2)}，余额 ${unlimited ? '不限额' : remaining == null ? '暂时无法获取' : `¥${remaining.toFixed(2)}`}`,
      )
      if (!unlimited && (remaining == null || remaining + 1e-9 < Number(estimate)))
        sufficient = false
    }
    const conclusion = sufficient
      ? '【余额充足，可以开始批量生成任务】'
      : '【余额不足，请联系负责人进行充值】'
    const message = `本次将生成总计：${items.length} 条，共：${totalSeconds} 秒，${modelText || '视频模型'} 视频，预计总费用为：${estimatedCost.toFixed(2)} 元。\n${balanceLines.join('\n')}\n\n${conclusion}`
    const confirmed = await confirmDialog({
      title: sufficient ? '确认批量生成视频' : '子账号余额不足',
      message,
      confirmText: sufficient ? '确定生成' : '知道了',
      cancelText: sufficient ? '取消' : '稍后处理',
      danger: !sufficient,
    })
    if (sufficient && confirmed) void store.generateAllShots()
  } catch (error) {
    await confirmDialog({
      title: '费用预估失败',
      message: error instanceof Error ? error.message : '余额暂时无法查询，请稍后重试',
      confirmText: '知道了',
      cancelText: '关闭',
      danger: true,
    })
  } finally {
    checkingBatchCost.value = false
  }
}
</script>

<template>
  <section class="panel script-editor">
    <header class="panel-header">
      <div class="title-group">
        <h2>视频编辑器</h2>
        <span v-if="store.storyboardProgress.total" class="generation-progress">
          <span class="generation-progress-track">
            <span class="generation-progress-fill" :style="{ width: `${storyboardPercent}%` }" />
          </span>
          已生成 {{ store.storyboardProgress.completed }}/{{ store.storyboardProgress.total }}
          <button
            v-if="store.storyboardProgress.failed"
            class="retry-all"
            @click="store.retryFailedStoryboardLines()"
          >
            {{ store.storyboardProgress.failed }} 条失败，重试
          </button>
        </span>
      </div>
      <div class="header-actions">
        <button
          class="btn-outline"
          :disabled="
            !batchGeneratableCount ||
            store.batchShooting ||
            store.songSwitching ||
            checkingBatchCost
          "
          title="批量生成全部「提示词就绪但视频未生成/失败」分镜的视频片段（最多同时生成 200 个）"
          @click="confirmBatchGenerate"
        >
          <span v-if="store.batchShooting || checkingBatchCost" class="spinner" />
          <AppIcon v-else name="sparkles" :size="15" />
          {{ checkingBatchCost ? '正在核算费用…' : '批量生成'
          }}{{ batchGeneratableCount ? `（${batchGeneratableCount}）` : '' }}
        </button>
        <button class="btn-outline" @click="store.openLibrary()">
          <AppIcon name="users" :size="15" />
          角色阵容
          <span v-if="store.castHumans.length" class="cast-count">{{
            store.castHumans.length
          }}</span>
        </button>
        <button
          class="btn-outline"
          :disabled="!store.activeStoryBible"
          @click="store.openOutline()"
        >
          <AppIcon name="file" :size="13" />
          查看大纲
        </button>
        <button
          class="btn-primary"
          :disabled="store.magicLoading || store.songSwitching"
          @click="store.openMagic()"
        >
          <span v-if="store.magicLoading" class="spinner light" />
          <AppIcon v-else name="sparkles" :size="15" />
          ASS 视频
        </button>
        <button
          class="btn-primary"
          :disabled="store.generalStoryboardLoading || store.songSwitching"
          @click="store.openGeneralStoryboard()"
        >
          <span v-if="store.generalStoryboardLoading" class="spinner light" />
          <AppIcon v-else name="movie" :size="15" />
          定制通用分镜
        </button>
        <button
          class="btn-primary"
          :disabled="store.randomGeneralStoryboardLoading || store.songSwitching"
          @click="store.openRandomGeneralStoryboard()"
        >
          <span v-if="store.randomGeneralStoryboardLoading" class="spinner light" />
          <AppIcon v-else name="movie" :size="15" />
          随机通用分镜
        </button>
      </div>
    </header>

    <!-- ASS 两阶段流程：大纲阶段状态横幅 -->
    <div
      v-if="store.outlinePhase === 'pending' || store.outlinePhase === 'outlining'"
      class="outline-banner"
    >
      <template v-if="store.outlinePhase === 'outlining'">
        <span class="spinner" />
        <span class="banner-text">
          {{ isGeneralOutline ? '正在规划 MV 大纲' : '正在生成 MV 大纲' }}（{{
            outlineStageText
          }}），本轮约需 {{ isGeneralOutline ? '1' : '2' }} 分钟，请稍候 · 已等待
          <span class="outline-elapsed">{{ outlineElapsedText }}</span>
        </span>
        <div class="outline-progress-track">
          <div class="outline-progress-fill" :style="{ width: `${outlinePercent}%` }" />
        </div>
        <span class="outline-progress-value">{{ outlinePercent }}%</span>
      </template>
      <template v-else>{{
        isGeneralOutline ? '分镜清单已就绪，准备生成 MV 大纲' : '歌词时间轴拆分完成，准备生成大纲'
      }}</template>
    </div>
    <div v-else-if="store.outlinePhase === 'failed'" class="outline-banner error">
      <span class="banner-text"
        >MV 大纲生成失败{{
          store.outlineError ? `：${store.outlineError}` : ''
        }}，已拆分的分镜列表已保留</span
      >
      <button class="banner-btn" :disabled="store.outlineLocked" @click="store.regenerateOutline()">
        重新生成大纲
      </button>
    </div>
    <div v-if="store.failedOutlineSegments.length" class="outline-banner warning">
      <span class="banner-text"
        >{{ store.failedOutlineSegments.length }} 个场景段大纲未生成，其余段落不受影响：</span
      >
      <span
        v-for="seg in store.failedOutlineSegments"
        :key="seg.sceneIndex"
        class="segment-failure"
        :title="seg.error"
      >
        场景{{ seg.sceneIndex + 1 }}·{{ seg.locationName }}
        <button
          class="banner-btn"
          :disabled="!!store.segmentRetrying[seg.sceneIndex]"
          @click="store.retryOutlineSegment(seg.sceneIndex)"
        >
          {{ store.segmentRetrying[seg.sceneIndex] ? '生成中…' : '重新生成' }}
        </button>
      </span>
    </div>

    <div ref="lineListRef" class="line-list">
      <div v-if="store.songSwitching" class="task-loading" role="status">
        <span class="spinner" />
        正在载入子任务…
      </div>
      <div
        v-for="(line, index) in store.lines"
        :key="line.id"
        class="line-wrapper"
        :data-line-id="line.id"
        :class="{ 'drag-over': overIndex === index && dragIndex !== index }"
        draggable="true"
        @dragstart="onDragStart(index, $event)"
        @dragover="onDragOver(index, $event)"
        @drop="onDrop(index)"
        @dragend="onDragEnd"
      >
        <ScriptLineItem :line="line" :index="index" />
      </div>

      <p v-if="!store.songSwitching && store.lines.length === 0" class="empty-tip">
        暂无视频，可点击下方【单个视频】或顶部三种分镜入口开始创作
      </p>
    </div>

    <footer class="editor-footer">
      <button class="btn-add" @click="store.addLine()">
        <AppIcon name="plus" :size="14" />
        单个视频
      </button>
    </footer>

    <!-- 弹层懒挂载（P3d）：关闭时不保留组件实例/watchers；打开时的初始化由各弹窗 immediate watch 完成 -->
    <ShotDetailModal v-if="!!store.editingLine" />
    <MagicScriptModal v-if="store.magicOpen" />
    <GeneralStoryboardModal v-if="store.generalStoryboardOpen" />
    <GeneralStoryboardModal v-if="store.randomGeneralStoryboardOpen" random />
    <StoryboardOutlineModal v-if="store.outlineOpen && !!store.activeStoryBible" />
  </section>
</template>

<style scoped>
.script-editor {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.task-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 160px;
  color: var(--text-muted);
  font-size: var(--font-sm);
}
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.generation-progress {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: 10px;
  color: var(--text-muted);
  font-size: var(--font-sm);
}
.generation-progress-track {
  display: inline-block;
  width: 72px;
  height: 6px;
  border-radius: 3px;
  background: #dbe7f8;
  overflow: hidden;
}
.generation-progress-fill {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: var(--primary);
  transition: width 0.4s ease;
}
.retry-all {
  border: 0;
  background: transparent;
  color: var(--primary);
  cursor: pointer;
  padding: 0 4px;
}
.outline-banner {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  background: #f2f7ff;
  border: 1px solid #d4e3fb;
  color: #35608f;
  font-size: var(--font-sm);
}
.outline-banner.error {
  background: var(--danger-light);
  border-color: var(--danger-border);
  color: var(--danger-active);
}
.outline-banner.warning {
  background: var(--warning-light);
  border-color: var(--warning-border);
  color: #96621a;
}
.banner-text {
  min-width: 0;
  word-break: break-all;
}
.banner-btn {
  border: 1px solid currentColor;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  padding: 2px 9px;
  font-size: var(--font-sm);
  cursor: pointer;
}
.banner-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.outline-progress-track {
  flex-basis: 100%;
  height: 6px;
  border-radius: 3px;
  background: #dbe7f8;
  overflow: hidden;
}
.outline-progress-fill {
  height: 100%;
  border-radius: 3px;
  background: var(--primary);
  transition: width 0.6s ease;
}
.outline-progress-value,
.outline-elapsed {
  font-variant-numeric: tabular-nums;
}
.segment-failure {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.title-group {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.header-actions {
  display: flex;
  gap: 6px;
}
.header-actions button {
  min-height: 30px;
  padding: 5px 11px;
  border-radius: var(--radius-sm);
  font-size: var(--font-sm);
}
.cast-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  border-radius: var(--radius-sm);
  background: var(--primary);
  color: #fff;
  font-size: 11px;
  padding: 0 5px;
}
.line-list {
  flex: 1;
  height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 14px;
  padding-right: 4px;
  min-height: 0;
}
.line-wrapper {
  /* P3a：屏外行跳过布局/绘制；auto 记住已渲染行真实高度，104px 仅是未渲染行的滚动条估算 */
  content-visibility: auto;
  contain-intrinsic-size: auto 104px;
}
.line-wrapper.drag-over {
  outline: 2px dashed var(--primary);
  outline-offset: 2px;
  border-radius: var(--radius-md);
}
.empty-tip {
  color: var(--text-secondary);
  text-align: center;
  margin-top: 60px;
  font-size: var(--font-md);
}
.editor-footer {
  display: flex;
  justify-content: center;
  padding-top: 14px;
}
.btn-add {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px dashed var(--border-dark);
  border-radius: var(--radius-sm);
  background: #fff;
  color: var(--text);
  padding: 8px 28px;
  font-size: var(--font-md);
  cursor: pointer;
  transition:
    border-color 0.15s,
    color 0.15s;
}
.btn-add:hover {
  border-color: var(--primary);
  color: var(--primary);
}
</style>
