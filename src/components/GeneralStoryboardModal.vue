<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { GeneralStoryboardRequest, ShotGenOptions } from '../types'
import { useProjectStore } from '../stores/project'
import AppIcon from './AppIcon.vue'
import { MAX_VIDEO_DURATION, MIN_VIDEO_DURATION } from '../mediaConstraints'

const store = useProjectStore()
const genre = ref('')
const secondary = ref('')
const tertiary = ref('')
const season = ref('秋')
const singer = ref('')
const ageGroup = ref('青年')
const visualStyle = ref('电影写实')
const ratio = ref<ShotGenOptions['ratio']>('16:9')
const emptyShotCount = ref(5)
const characterShotCount = ref(5)
const totalDuration = ref(100)
const extraRequirement = ref('')
const selectedHumanIds = ref<string[]>([])

const genreOption = computed(() => store.generalStoryboardOptions?.genres.find((item) => item.value === genre.value))
const secondaryOptions = computed(() => genreOption.value?.children ?? [])
const secondaryOption = computed(() => secondaryOptions.value.find((item) => item.value === secondary.value))
const tertiaryOptions = computed(() => secondaryOption.value?.children ?? [])
const totalShots = computed(() => Math.max(0, emptyShotCount.value) + Math.max(0, characterShotCount.value))
const minimumTotalDuration = computed(() => totalShots.value * MIN_VIDEO_DURATION)
const maximumTotalDuration = computed(() => totalShots.value * MAX_VIDEO_DURATION)
const averageDuration = computed(() => totalShots.value ? Math.round(totalDuration.value / totalShots.value * 10) / 10 : 0)
const durationIsValid = computed(() => totalDuration.value >= minimumTotalDuration.value && totalDuration.value <= maximumTotalDuration.value)
const canSubmit = computed(() => !!genre.value && !!secondary.value && totalShots.value > 0 && durationIsValid.value)

const reset = () => {
  const options = store.generalStoryboardOptions
  genre.value = options?.genres[0]?.value ?? ''
  secondary.value = options?.genres[0]?.children?.[0]?.value ?? ''
  tertiary.value = options?.genres[0]?.children?.[0]?.children?.[0]?.value ?? ''
  season.value = options?.seasons.includes('秋') ? '秋' : (options?.seasons[0] ?? '')
  ageGroup.value = options?.ageGroups.includes('青年') ? '青年' : (options?.ageGroups[0] ?? '')
  visualStyle.value = options?.visualStyles.includes('电影写实') ? '电影写实' : (options?.visualStyles[0] ?? '')
  ratio.value = options?.ratios[0] ?? '16:9'
  singer.value = ''
  emptyShotCount.value = 5
  characterShotCount.value = 5
  totalDuration.value = 100
  extraRequirement.value = ''
  selectedHumanIds.value = [...store.castIds]
}

watch(() => store.generalStoryboardOpen, (open) => { if (open) reset() })
watch(() => store.generalStoryboardOptions, (options) => {
  if (store.generalStoryboardOpen && options && !genre.value) reset()
})
watch(genre, () => {
  secondary.value = secondaryOptions.value[0]?.value ?? ''
  tertiary.value = secondaryOptions.value[0]?.children?.[0]?.value ?? ''
})
watch(secondary, () => { tertiary.value = tertiaryOptions.value[0]?.value ?? '' })

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
    secondaryCategory: labelOf(secondary.value, secondaryOptions.value),
    tertiaryCategory: tertiary.value ? labelOf(tertiary.value, tertiaryOptions.value) : undefined,
    season: season.value,
    singer: singer.value.trim() || undefined,
    ageGroup: ageGroup.value,
    visualStyle: visualStyle.value,
    ratio: ratio.value,
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
  <Teleport to="body">
    <div v-if="store.generalStoryboardOpen" class="modal-mask" @click.self="store.closeGeneralStoryboard()">
      <div class="modal">
        <header class="modal-header">
          <h3><AppIcon name="movie" :size="18" />通用分镜</h3>
          <button class="close-btn" :disabled="store.generalStoryboardLoading" @click="store.closeGeneralStoryboard()">
            <AppIcon name="close" :size="13" />关闭
          </button>
        </header>

        <div class="modal-body">
          <p v-if="store.generalStoryboardError" class="error-tip">{{ store.generalStoryboardError }}</p>
          <p v-if="!store.generalStoryboardOptions && !store.generalStoryboardError" class="loading-tip">
            <span class="spinner" />正在加载生成选项…
          </p>

          <template v-if="store.generalStoryboardOptions">
            <section class="form-section">
              <h4>人物素材</h4>
              <div>
                <p class="field-label">从已有角色库选择 <span>（可多选，人物镜轮流使用）</span></p>
                <div class="cast-list">
                  <button v-for="human in store.digitalHumans" :key="human.id" class="cast-item" :class="{ active: selectedHumanIds.includes(human.id) }" @click="toggleHuman(human.id)">
                    <img :src="human.avatar" :alt="human.name" /><span>{{ human.name }}</span>
                    <AppIcon v-if="selectedHumanIds.includes(human.id)" name="check" :size="12" />
                  </button>
                  <span v-if="!store.digitalHumans.length" class="empty-cast">角色库暂无可选人物，请先到角色阵容中添加数字人</span>
                </div>
              </div>
            </section>

            <section class="form-section">
              <h4>音乐属性</h4>
              <div class="field-grid three">
                <label><span>曲风 *</span><select v-model="genre"><option v-for="item in store.generalStoryboardOptions.genres" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
                <label><span>二级分类 *</span><select v-model="secondary"><option v-for="item in secondaryOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
                <label><span>三级分类</span><select v-model="tertiary"><option value="">不指定</option><option v-for="item in tertiaryOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
              </div>
            </section>

            <section class="form-section">
              <h4>视觉与人物设定</h4>
              <div class="field-grid five">
                <label><span>季节</span><select v-model="season"><option v-for="item in store.generalStoryboardOptions.seasons" :key="item">{{ item }}</option></select></label>
                <label><span>歌手</span><input v-model="singer" placeholder="如：阿杜" /></label>
                <label><span>年龄段</span><select v-model="ageGroup"><option v-for="item in store.generalStoryboardOptions.ageGroups" :key="item">{{ item }}</option></select></label>
                <label><span>画面风格</span><select v-model="visualStyle"><option v-for="item in store.generalStoryboardOptions.visualStyles" :key="item">{{ item }}</option></select></label>
                <label><span>画幅</span><select v-model="ratio"><option v-for="item in store.generalStoryboardOptions.ratios" :key="item">{{ item }}</option></select></label>
              </div>
            </section>

            <section class="form-section">
              <h4>生成规模</h4>
              <div class="field-grid three">
                <label><span>空镜数量</span><input v-model.number="emptyShotCount" type="number" min="0" max="50" /></label>
                <label><span>人物镜数量</span><input v-model.number="characterShotCount" type="number" min="0" max="50" /></label>
                <label><span>总时长（秒）</span><input v-model.number="totalDuration" type="number" :min="minimumTotalDuration" :max="maximumTotalDuration" /></label>
              </div>
              <p class="estimate" :class="{ invalid: totalShots > 0 && !durationIsValid }">将生成 <strong>{{ totalShots }}</strong> 个分镜：{{ emptyShotCount }} 个空镜、{{ characterShotCount }} 个人物镜，平均每镜约 <strong>{{ averageDuration }} 秒</strong>；允许总时长 <strong>{{ minimumTotalDuration }}–{{ maximumTotalDuration }} 秒</strong>（每镜 4–15 秒）</p>
              <label class="extra-field"><span>额外要求（可选）</span><textarea v-model="extraRequirement" rows="3" placeholder="例如：雨夜、克制情绪、避免舞蹈场面，多使用缓慢运镜…" /></label>
            </section>
          </template>
        </div>

        <footer class="modal-footer">
          <button class="cancel-btn" :disabled="store.generalStoryboardLoading" @click="store.closeGeneralStoryboard()">取消</button>
          <button class="btn-primary" :disabled="!canSubmit || store.generalStoryboardLoading || !store.generalStoryboardOptions" @click="submit">
            <span v-if="store.generalStoryboardLoading" class="spinner light" />
            <AppIcon v-else name="sparkles" :size="15" />
            {{ store.generalStoryboardLoading ? '正在生成分镜脚本…' : '批量生成' }}
          </button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-mask{position:fixed;inset:0;z-index:100;background:rgba(0,0,0,.48);display:flex;align-items:center;justify-content:center;padding:24px}.modal{width:920px;max-width:100%;max-height:94vh;background:#fff;border-radius:16px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 24px 70px rgba(0,0,0,.28)}.modal-header{display:flex;align-items:center;justify-content:space-between;padding:18px 22px;border-bottom:1px solid var(--border)}.modal-header h3{margin:0;display:flex;align-items:center;gap:8px;font-size:18px}.modal-header h3 .app-icon{color:var(--primary)}.close-btn{border:0;background:none;color:var(--text-secondary);display:flex;align-items:center;gap:4px;cursor:pointer}.modal-body{padding:18px 22px;overflow-y:auto}.form-section{margin-bottom:20px}.form-section:last-child{margin-bottom:0}.form-section h4{margin:0 0 12px;padding-bottom:8px;border-bottom:1px solid var(--border);font-size:14px}.field-label{margin:0 0 8px;font-size:13px;font-weight:600}.field-label span,.extra-field>span{color:var(--text-secondary);font-weight:400}.people-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.upload-box,.cast-list{min-height:106px;border:1px dashed var(--border-dark);border-radius:10px;background:#fafafa;padding:10px}.upload-box{display:flex;align-items:center;justify-content:center;flex-direction:column;gap:7px;color:var(--text-secondary);cursor:pointer}.upload-box:hover{border-color:var(--primary);background:var(--primary-light)}.image-list,.cast-list{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.image-list{width:100%;border:0;padding:0;background:transparent}.image-thumb{width:58px;height:72px;position:relative;border-radius:8px;overflow:hidden}.image-thumb img{width:100%;height:100%;object-fit:cover}.image-thumb button{position:absolute;right:3px;top:3px;width:18px;height:18px;border:0;border-radius:50%;background:rgba(0,0,0,.6);color:#fff}.image-add{width:58px;height:72px;border:1px dashed var(--border-dark);border-radius:8px;background:#fff;color:var(--text-secondary)}.cast-item{position:relative;width:62px;border:1px solid var(--border);border-radius:9px;background:#fff;padding:4px;color:var(--text-secondary);cursor:pointer}.cast-item.active{border-color:var(--primary);color:var(--primary);background:var(--primary-light)}.cast-item img{width:100%;height:56px;object-fit:cover;border-radius:6px}.cast-item span{display:block;font-size:11px;overflow:hidden;white-space:nowrap}.cast-item .app-icon{position:absolute;right:5px;top:5px;background:var(--primary);color:#fff;border-radius:50%;padding:2px}.empty-cast{font-size:12px;color:var(--text-secondary)}.field-grid{display:grid;gap:12px}.field-grid.three{grid-template-columns:repeat(3,1fr)}.field-grid.five{grid-template-columns:repeat(5,1fr)}.field-grid label,.extra-field{display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--text-secondary)}select,input,textarea{width:100%;border:1px solid var(--border-dark);border-radius:9px;background:#fff;padding:9px 10px;font:inherit;color:var(--text);outline:none}select:focus,input:focus,textarea:focus{border-color:var(--primary)}textarea{resize:vertical}.estimate{margin:11px 0;padding:9px 12px;border-radius:8px;background:var(--primary-light);color:var(--text-secondary);font-size:12px}.estimate strong{color:var(--primary)}.modal-footer{display:flex;justify-content:flex-end;gap:10px;padding:14px 22px 18px;border-top:1px solid var(--border)}.cancel-btn{border:1px solid var(--border-dark);border-radius:20px;background:#fff;padding:9px 20px;cursor:pointer}.error-tip{padding:10px 12px;border-radius:8px;background:#fff0f0;color:#d33}.loading-tip{display:flex;align-items:center;justify-content:center;gap:8px;padding:40px;color:var(--text-secondary)}@media(max-width:760px){.people-grid,.field-grid.three,.field-grid.five{grid-template-columns:1fr 1fr}}@media(max-width:520px){.people-grid,.field-grid.three,.field-grid.five{grid-template-columns:1fr}}
.cast-list{max-height:210px;overflow-y:auto;align-content:flex-start}
.estimate.invalid{background:#fff0f0;color:#c33}.estimate.invalid strong{color:#c33}
</style>
