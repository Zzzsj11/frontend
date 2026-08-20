<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { GeneralGender, GeneralStoryboardRequest, ShotGenOptions } from '../types'
import { GENERAL_GENDER_OPTIONS } from '../types'
import { useProjectStore } from '../stores/project'
import AppIcon from './AppIcon.vue'
import BaseModal from './base/BaseModal.vue'
import CharacterPortrait from './CharacterPortrait.vue'
import { MAX_VIDEO_DURATION, MIN_VIDEO_DURATION } from '../mediaConstraints'
import {
  DEFAULT_IMAGE_MODEL,
  DEFAULT_VIDEO_MODEL,
  IMAGE_MODEL_OPTIONS,
  VIDEO_MODEL_OPTIONS,
  generationModelLabel,
  loadGenerationModels,
} from '../generationModels'

const store = useProjectStore()
void loadGenerationModels()
const genre = ref('')
const secondary = ref('')
const tertiary = ref('')
const season = ref('秋')
const gender = ref<GeneralGender>('女')
const ageGroup = ref('青年')
const visualStyle = ref('电影写实')
const ratio = ref<ShotGenOptions['ratio']>('16:9')
const resolution = ref<ShotGenOptions['resolution']>('720p')
const imageModel = ref(DEFAULT_IMAGE_MODEL)
const videoModel = ref(DEFAULT_VIDEO_MODEL)
const emptyShotCount = ref(4)
const characterShotCount = ref(13)
const totalDuration = ref(210)
const extraRequirement = ref('')
const selectedHumanIds = ref<string[]>([])

const genreOption = computed(() =>
  store.generalStoryboardOptions?.genres.find((item) => item.value === genre.value),
)
const secondaryOptions = computed(() => genreOption.value?.children ?? [])
const secondaryOption = computed(() =>
  secondaryOptions.value.find((item) => item.value === secondary.value),
)
const tertiaryOptions = computed(() => secondaryOption.value?.children ?? [])
const tertiaryOption = computed(() =>
  tertiaryOptions.value.find((item) => item.value === tertiary.value),
)
const castPolicy = computed(
  () =>
    tertiaryOption.value?.castPolicy ??
    secondaryOption.value?.castPolicy ??
    genreOption.value?.castPolicy ??
    'optional_random',
)
const castRequired = computed(() => characterShotCount.value > 0 && castPolicy.value === 'required')
const totalShots = computed(
  () => Math.max(0, emptyShotCount.value) + Math.max(0, characterShotCount.value),
)
const minimumTotalDuration = computed(() => totalShots.value * MIN_VIDEO_DURATION)
const maximumTotalDuration = computed(() => totalShots.value * MAX_VIDEO_DURATION)
const averageDuration = computed(() =>
  totalShots.value ? Math.round((totalDuration.value / totalShots.value) * 10) / 10 : 0,
)
const durationIsValid = computed(
  () =>
    totalDuration.value >= minimumTotalDuration.value &&
    totalDuration.value <= maximumTotalDuration.value,
)
const canSubmit = computed(
  () =>
    !!genre.value &&
    (!secondaryOptions.value.length || !!secondary.value) &&
    totalShots.value > 0 &&
    durationIsValid.value &&
    (!castRequired.value || selectedHumanIds.value.length > 0),
)

const reset = () => {
  const options = store.generalStoryboardOptions
  genre.value = options?.genres[0]?.value ?? ''
  secondary.value = options?.genres[0]?.children?.[0]?.value ?? ''
  tertiary.value = options?.genres[0]?.children?.[0]?.children?.[0]?.value ?? ''
  season.value = options?.seasons.includes('秋') ? '秋' : (options?.seasons[0] ?? '')
  ageGroup.value = options?.ageGroups.includes('青年') ? '青年' : (options?.ageGroups[0] ?? '')
  visualStyle.value = options?.visualStyles.includes('电影写实')
    ? '电影写实'
    : (options?.visualStyles[0] ?? '')
  ratio.value = options?.ratios[0] ?? '16:9'
  resolution.value = '720p'
  imageModel.value = DEFAULT_IMAGE_MODEL
  videoModel.value = DEFAULT_VIDEO_MODEL
  gender.value = '女'
  emptyShotCount.value = 4
  characterShotCount.value = 13
  totalDuration.value = 210
  extraRequirement.value = ''
  selectedHumanIds.value = []
}

// immediate：弹层懒挂载（P3d）后挂载即打开，靠 immediate 完成表单初始化
watch(
  () => store.generalStoryboardOpen,
  (open) => {
    if (open) reset()
  },
  { immediate: true },
)
watch(
  () => store.generalStoryboardOptions,
  (options) => {
    if (store.generalStoryboardOpen && options && !genre.value) reset()
  },
)
watch(genre, () => {
  secondary.value = secondaryOptions.value[0]?.value ?? ''
  tertiary.value = secondaryOptions.value[0]?.children?.[0]?.value ?? ''
})
watch(secondary, () => {
  tertiary.value = tertiaryOptions.value[0]?.value ?? ''
})

const toggleHuman = (id: string) => {
  const index = selectedHumanIds.value.indexOf(id)
  index >= 0 ? selectedHumanIds.value.splice(index, 1) : selectedHumanIds.value.push(id)
}

const labelOf = (value: string, options: Array<{ value: string; label: string }>) =>
  options.find((item) => item.value === value)?.label ?? value

const submit = () => {
  if (!canSubmit.value || store.generalStoryboardLoading) return
  const request: GeneralStoryboardRequest = {
    genre: labelOf(genre.value, store.generalStoryboardOptions?.genres ?? []),
    secondaryCategory: secondary.value
      ? labelOf(secondary.value, secondaryOptions.value)
      : undefined,
    tertiaryCategory: tertiary.value ? labelOf(tertiary.value, tertiaryOptions.value) : undefined,
    season: season.value,
    gender: gender.value,
    ageGroup: ageGroup.value,
    visualStyle: visualStyle.value,
    ratio: ratio.value,
    resolution: resolution.value,
    imageModel: imageModel.value,
    videoModel: videoModel.value,
    emptyShotCount: Math.max(0, Math.round(emptyShotCount.value)),
    characterShotCount: Math.max(0, Math.round(characterShotCount.value)),
    totalDuration: Math.round(totalDuration.value),
    digitalHumanIds: [...selectedHumanIds.value],
    extraRequirement: extraRequirement.value.trim() || undefined,
  }
  store.runGeneralStoryboard(request)
}
</script>

<template>
  <BaseModal
    :open="store.generalStoryboardOpen"
    width="920px"
    max-height="94vh"
    :loading="store.generalStoryboardLoading"
    aria-label="通用 MV 视频"
    @close="store.closeGeneralStoryboard()"
  >
    <template #title><AppIcon name="movie" :size="18" />通用 MV 视频</template>
    <div class="modal-body">
      <p v-if="store.generalStoryboardError" class="error-tip">
        {{ store.generalStoryboardError }}
      </p>
      <p
        v-if="!store.generalStoryboardOptions && !store.generalStoryboardError"
        class="loading-tip"
      >
        <span class="spinner" />正在加载生成选项…
      </p>

      <template v-if="store.generalStoryboardOptions">
        <section class="form-section">
          <h4>音乐属性</h4>
          <div class="field-grid three">
            <label
              ><span>曲风 *</span
              ><select v-model="genre">
                <option
                  v-for="item in store.generalStoryboardOptions.genres"
                  :key="item.value"
                  :value="item.value"
                >
                  {{ item.label }}
                </option>
              </select></label
            >
            <label
              ><span>二级分类{{ secondaryOptions.length ? ' *' : '' }}</span
              ><select v-model="secondary" :disabled="!secondaryOptions.length">
                <option v-if="!secondaryOptions.length" value="">无下级分类</option>
                <option v-for="item in secondaryOptions" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select></label
            >
            <label
              ><span>三级分类</span
              ><select v-model="tertiary">
                <option value="">不指定</option>
                <option v-for="item in tertiaryOptions" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select></label
            >
          </div>
        </section>

        <section class="form-section">
          <h4>视觉与人物设定</h4>
          <div class="field-grid five">
            <label
              ><span>季节</span
              ><select v-model="season">
                <option v-for="item in store.generalStoryboardOptions.seasons" :key="item">
                  {{ item }}
                </option>
              </select></label
            >
            <label
              ><span>性别</span
              ><select v-model="gender">
                <option v-for="item in GENERAL_GENDER_OPTIONS" :key="item" :value="item">
                  {{ item }}
                </option>
              </select></label
            >
            <label
              ><span>年龄段</span
              ><select v-model="ageGroup">
                <option v-for="item in store.generalStoryboardOptions.ageGroups" :key="item">
                  {{ item }}
                </option>
              </select></label
            >
            <label
              ><span>画面风格</span
              ><select v-model="visualStyle">
                <option v-for="item in store.generalStoryboardOptions.visualStyles" :key="item">
                  {{ item }}
                </option>
              </select></label
            >
            <label
              ><span>画幅</span
              ><select v-model="ratio">
                <option v-for="item in store.generalStoryboardOptions.ratios" :key="item">
                  {{ item }}
                </option>
              </select></label
            >
          </div>
        </section>

        <section class="form-section">
          <h4>生成规模</h4>
          <div class="field-grid three">
            <label
              ><span>空镜数量</span
              ><input v-model.number="emptyShotCount" type="number" min="0" max="50"
            /></label>
            <label
              ><span>人物镜数量</span
              ><input v-model.number="characterShotCount" type="number" min="0" max="50"
            /></label>
            <label
              ><span>总时长（秒）</span
              ><input
                v-model.number="totalDuration"
                type="number"
                :min="minimumTotalDuration"
                :max="maximumTotalDuration"
            /></label>
          </div>
          <p class="estimate" :class="{ invalid: totalShots > 0 && !durationIsValid }">
            将生成 <strong>{{ totalShots }}</strong> 个视频：{{ emptyShotCount }} 个空镜、{{
              characterShotCount
            }}
            个人物镜，平均每镜约 <strong>{{ averageDuration }} 秒</strong>；允许总时长
            <strong>{{ minimumTotalDuration }}–{{ maximumTotalDuration }} 秒</strong>（每镜 4–15
            秒）
          </p>
          <div class="field-grid three model-grid">
            <label
              ><span>清晰度 *</span
              ><select v-model="resolution">
                <option value="480p">480p</option>
                <option value="720p">720p</option>
                <option value="1080p">1080p</option>
              </select></label
            >
            <label
              ><span>视频模型 *</span
              ><select v-model="videoModel" aria-label="视频模型">
                <option v-for="item in VIDEO_MODEL_OPTIONS" :key="item.value" :value="item.value">
                  {{ generationModelLabel(item) }}
                </option>
              </select></label
            >
            <label
              ><span>图片模型 *</span
              ><select v-model="imageModel" disabled>
                <option v-for="item in IMAGE_MODEL_OPTIONS" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select></label
            >
          </div>
          <p class="model-hint">H3 同时执行上限为 2 个任务，超出的任务会自动排队。</p>
          <label class="extra-field"
            ><span>额外要求（可选）</span
            ><textarea
              v-model="extraRequirement"
              rows="3"
              placeholder="例如：雨夜、克制情绪、避免舞蹈场面，多使用缓慢运镜…"
            />
          </label>
        </section>
        <section class="form-section">
          <h4>人物素材{{ castRequired ? '（必选）' : '（可选）' }}</h4>
          <div>
            <p class="field-label">
              从已有角色库选择
              <span v-if="characterShotCount <= 0">（当前没有人物镜，无需选择）</span>
              <span v-else-if="castRequired">（当前分类必须手动选择至少一位人物）</span>
              <span v-else>（未选择时，系统会按性别设定自动匹配系统人物）</span>
            </p>
            <div class="cast-list">
              <button
                v-for="human in store.digitalHumans"
                :key="human.id"
                class="cast-item"
                :class="{ active: selectedHumanIds.includes(human.id) }"
                @click="toggleHuman(human.id)"
              >
                <CharacterPortrait :src="human.avatar" :alt="human.name" /><span>{{
                  human.name
                }}</span>
                <AppIcon v-if="selectedHumanIds.includes(human.id)" name="check" :size="12" />
              </button>
              <span v-if="!store.digitalHumans.length" class="empty-cast"
                >角色库暂无可选人物，请先到角色阵容中添加数字人</span
              >
            </div>
          </div>
        </section>
      </template>
    </div>

    <template #footer>
      <button
        class="cancel-btn"
        :disabled="store.generalStoryboardLoading"
        @click="store.closeGeneralStoryboard()"
      >
        取消
      </button>
      <button
        class="btn-primary"
        :disabled="!canSubmit || store.generalStoryboardLoading || !store.generalStoryboardOptions"
        @click="submit"
      >
        <span v-if="store.generalStoryboardLoading" class="spinner light" />
        <AppIcon v-else name="sparkles" :size="15" />
        {{ store.generalStoryboardLoading ? '正在生成视频脚本…' : '批量生成' }}
      </button>
    </template>
  </BaseModal>
</template>

<style scoped>
.modal-body {
  padding: 18px 22px;
  overflow-y: auto;
}
.form-section {
  margin-bottom: 20px;
}
.form-section:last-child {
  margin-bottom: 0;
}
.form-section h4 {
  margin: 0 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
  font-size: var(--font-md);
}
.field-label {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
}
.field-label span,
.extra-field > span {
  color: var(--text-secondary);
  font-weight: 400;
}
.people-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.upload-box,
.cast-list {
  min-height: 106px;
  border: 1px dashed var(--border-dark);
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  padding: 10px;
}
.upload-box {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 7px;
  color: var(--text-secondary);
  cursor: pointer;
}
.upload-box:hover {
  border-color: var(--primary);
  background: var(--primary-light);
}
.image-list,
.cast-list {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.image-list {
  width: 100%;
  border: 0;
  padding: 0;
  background: transparent;
}
.image-thumb {
  width: 58px;
  height: 72px;
  position: relative;
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.image-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.image-thumb button {
  position: absolute;
  right: 3px;
  top: 3px;
  width: 18px;
  height: 18px;
  border: 0;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
}
.image-add {
  width: 58px;
  height: 72px;
  border: 1px dashed var(--border-dark);
  border-radius: var(--radius-sm);
  background: #fff;
  color: var(--text-secondary);
}
.cast-item {
  position: relative;
  width: 62px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: #fff;
  padding: 4px;
  color: var(--text-secondary);
  cursor: pointer;
}
.cast-item.active {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-light);
}
.cast-item img {
  width: 100%;
  height: 56px;
  object-fit: cover;
  border-radius: var(--radius-sm);
}
.cast-item span {
  display: block;
  font-size: 11px;
  overflow: hidden;
  white-space: nowrap;
}
.cast-item .app-icon {
  position: absolute;
  right: 5px;
  top: 5px;
  background: var(--primary);
  color: #fff;
  border-radius: 50%;
  padding: 2px;
}
.empty-cast {
  font-size: var(--font-sm);
  color: var(--text-secondary);
}
.field-grid {
  display: grid;
  gap: 12px;
}
.field-grid.three {
  grid-template-columns: repeat(3, 1fr);
}
.field-grid.five {
  grid-template-columns: repeat(5, 1fr);
}
.field-grid label,
.extra-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: var(--font-sm);
  color: var(--text-secondary);
}
select,
input,
textarea {
  width: 100%;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: #fff;
  padding: 9px 10px;
  font: inherit;
  color: var(--text);
  outline: none;
}
select:focus,
input:focus,
textarea:focus {
  border-color: var(--primary);
}
textarea {
  resize: vertical;
}
.estimate {
  margin: 11px 0;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  background: var(--primary-light);
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.estimate strong {
  color: var(--primary);
}
.cancel-btn {
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-pill);
  background: #fff;
  padding: 9px 20px;
  cursor: pointer;
}
.error-tip {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--danger-light);
  color: var(--danger);
}
.loading-tip {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px;
  color: var(--text-secondary);
}
@media (max-width: 760px) {
  .people-grid,
  .field-grid.three,
  .field-grid.five {
    grid-template-columns: 1fr 1fr;
  }
}
@media (max-width: 520px) {
  .people-grid,
  .field-grid.three,
  .field-grid.five {
    grid-template-columns: 1fr;
  }
}
.cast-list {
  max-height: 210px;
  overflow-y: auto;
  align-content: flex-start;
}
.estimate.invalid {
  background: var(--danger-light);
  color: var(--danger);
}
.estimate.invalid strong {
  color: var(--danger);
}
.model-grid {
  margin: 12px 0 6px;
}
.model-grid select:disabled {
  background: var(--surface-muted);
  color: var(--text-secondary);
  cursor: not-allowed;
}
.model-hint {
  margin: 0 0 12px;
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.cast-list {
  max-height: 240px;
  overflow-x: hidden;
  overflow-y: auto;
  flex-wrap: wrap;
}
.cast-item {
  flex: 1 1 124px;
  width: 124px;
  max-width: 160px;
}
.cast-item img {
  height: 68px;
  object-fit: contain;
  background: var(--surface-muted);
}
.cast-item .character-portrait {
  width: 100%;
  height: 68px;
  border-radius: var(--radius-sm);
}
</style>
