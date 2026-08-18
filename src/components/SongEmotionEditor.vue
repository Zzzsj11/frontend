<script setup lang="ts">
import { computed, watch } from 'vue'
import type { SongEmotionInput } from '../api/adminSongEmotions'
import type { GeneralStoryboardOptions } from '../types'

const props = defineProps<{
  editing: boolean
  busy: boolean
  options: GeneralStoryboardOptions | null
}>()
const emit = defineEmits<{ submit: []; cancel: [] }>()
const model = defineModel<SongEmotionInput>({ required: true })

const primaryOptions = computed(() => props.options?.genres ?? [])
const selectedPrimary = computed(() =>
  primaryOptions.value.find((item) => item.value === model.value.primaryCategory),
)
const secondaryOptions = computed(() => selectedPrimary.value?.children ?? [])
const selectedSecondary = computed(() =>
  secondaryOptions.value.find((item) => item.value === model.value.secondaryCategory),
)
const tertiaryOptions = computed(() => selectedSecondary.value?.children ?? [])
const seasonOptions = computed(() => props.options?.seasons ?? [])
const selectedSeasons = computed({
  get: () => model.value.seasons.split('/').filter(Boolean),
  set: (values: string[]) => {
    if (values.includes('通用'))
      model.value.seasons =
        model.value.seasons === '通用' ? values.filter((x) => x !== '通用').join('/') : '通用'
    else model.value.seasons = values.join('/')
  },
})

const categoryPath = (values: Array<string | null>) => values.filter(Boolean).join('-')
const syncMaterialCategory = () => {
  model.value.materialCategory = categoryPath([
    model.value.primaryCategory,
    model.value.secondaryCategory,
    model.value.tertiaryCategory,
  ])
}
const selectPrimary = () => {
  const secondary = selectedPrimary.value?.children?.[0]
  model.value.secondaryCategory = secondary?.value ?? null
  model.value.tertiaryCategory = secondary?.children?.[0]?.value ?? null
  syncMaterialCategory()
}
const selectSecondary = () => {
  model.value.tertiaryCategory = selectedSecondary.value?.children?.[0]?.value ?? null
  syncMaterialCategory()
}
const initializeDefaults = () => {
  if (!model.value.primaryCategory && primaryOptions.value.length) {
    model.value.primaryCategory = primaryOptions.value[0].value
    selectPrimary()
  }
  if (!model.value.seasons && seasonOptions.value.length)
    model.value.seasons = seasonOptions.value.includes('通用') ? '通用' : seasonOptions.value[0]
}
watch(() => props.options, initializeDefaults, { immediate: true })
</script>

<template>
  <form class="editor" @submit.prevent="emit('submit')">
    <div class="field-row identity-row">
      <label
        >歌曲编号<input v-model="model.songCode" :disabled="editing" required pattern="\d{5,}"
      /></label>
      <label>歌名<input v-model="model.songName" required /></label>
      <label>歌手<input v-model="model.artists" /></label>
    </div>

    <fieldset class="category-group">
      <legend>歌曲分类</legend>
      <p class="hint">与“通用分类”实时联动，选择上级后自动更新下级选项。</p>
      <div class="field-row category-row">
        <label
          >一级分类<select v-model="model.primaryCategory" required @change="selectPrimary">
            <option v-for="item in primaryOptions" :key="item.value" :value="item.value">
              {{ item.label }}
            </option>
          </select></label
        >
        <label
          >二级分类<select
            v-model="model.secondaryCategory"
            :disabled="!secondaryOptions.length"
            @change="selectSecondary"
          >
            <option :value="null">无</option>
            <option v-for="item in secondaryOptions" :key="item.value" :value="item.value">
              {{ item.label }}
            </option>
          </select></label
        >
        <label
          >三级分类<select
            v-model="model.tertiaryCategory"
            :disabled="!tertiaryOptions.length"
            @change="syncMaterialCategory"
          >
            <option :value="null">无</option>
            <option v-for="item in tertiaryOptions" :key="item.value" :value="item.value">
              {{ item.label }}
            </option>
          </select></label
        >
      </div>
      <div class="material-preview">
        <span>素材分类</span><strong>{{ model.materialCategory || '请选择歌曲分类' }}</strong>
      </div>
    </fieldset>

    <fieldset class="season-group">
      <legend>适用季节</legend>
      <p class="hint">可多选；选择“通用”时自动清除其他季节。</p>
      <div class="season-options">
        <label v-for="season in seasonOptions" :key="season" class="season-option"
          ><input v-model="selectedSeasons" type="checkbox" :value="season" />{{ season }}</label
        >
      </div>
    </fieldset>

    <label>歌词<textarea v-model="model.lyrics" rows="8" placeholder="歌曲完整歌词" /></label>

    <label class="atmosphere-field"
      >氛围基调<textarea
        v-model="model.atmosphere"
        rows="4"
        placeholder="例如：柔和暖色调 | 青春校园场景 | 带有距离感的镜头"
      />
    </label>
    <label
      >人物设定<textarea
        v-model="model.characterSetting"
        rows="4"
        placeholder="例如：年龄、形象、情感特征；无需人物时填写“无需人物”"
      />
    </label>
    <label>状态<input v-model.number="model.status" type="number" step="1" required /> </label>
    <div class="footer">
      <button type="button" :disabled="busy" @click="emit('cancel')">取消</button
      ><button class="primary" type="submit" :disabled="busy">
        {{ busy ? '保存中…' : '保存' }}
      </button>
    </div>
  </form>
</template>

<style scoped>
.editor {
  display: grid;
  gap: 18px;
  padding: 20px 24px 24px;
  overflow-y: auto;
}
.field-row {
  display: grid;
  gap: 14px;
}
.identity-row,
.category-row {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
label {
  display: grid;
  gap: 7px;
  color: var(--text-regular);
  font-weight: 600;
}
input,
select,
textarea {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  font: inherit;
}
input:focus,
select:focus,
textarea:focus {
  border-color: var(--primary);
  outline: none;
}
fieldset {
  min-width: 0;
  margin: 0;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-muted);
}
legend {
  padding: 0 6px;
  color: var(--text);
  font-weight: 700;
}
.hint {
  margin: -2px 0 13px;
  color: var(--text-secondary);
  font-size: var(--font-sm);
}
.material-preview {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--primary-light);
}
.material-preview span {
  color: var(--text-secondary);
}
.material-preview strong {
  color: var(--primary);
}
.season-options {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.season-option {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-pill);
  background: var(--surface);
  cursor: pointer;
}
.season-option input {
  width: auto;
  margin: 0;
  accent-color: var(--primary);
}
.atmosphere-field textarea {
  resize: vertical;
}
.footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.footer button {
  padding: 9px 18px;
  border: 1px solid var(--border-dark);
  border-radius: var(--radius-sm);
  background: var(--surface);
  cursor: pointer;
}
.footer .primary {
  border-color: var(--primary);
  background: var(--primary);
  color: var(--surface);
}
@media (max-width: 760px) {
  .identity-row,
  .category-row {
    grid-template-columns: 1fr;
  }
}
</style>
