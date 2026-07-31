<script setup lang="ts">
import { computed, ref } from 'vue'
import { useProjectStore } from '../stores/project'
import AppIcon from './AppIcon.vue'

const store = useProjectStore()

const activeStyle = ref('全部')
const styles = computed(() => ['全部', ...new Set(store.digitalHumans.map((d) => d.style))])
const filtered = computed(() =>
  activeStyle.value === '全部'
    ? store.digitalHumans
    : store.digitalHumans.filter((d) => d.style === activeStyle.value),
)

// 生成数字人：调用真实异步生图接口，成功后新卡片加入资产库
const genOpen = ref(false)
const genName = ref('')
const genStyle = ref('')
const genDesc = ref('')
const genError = ref('')
const canGen = computed(() => !!genName.value.trim() && !!genDesc.value.trim())

const submitGen = async () => {
  if (!canGen.value || store.dhGenerating) return
  genError.value = ''
  try {
    await store.generateDigitalHuman({
      name: genName.value.trim(),
      style: genStyle.value.trim() || '自定义',
      description: genDesc.value.trim(),
    })
    genOpen.value = false
    genName.value = ''
    genStyle.value = ''
    genDesc.value = ''
    activeStyle.value = '全部'
  } catch (e) {
    genError.value = e instanceof Error ? e.message : '生成失败，请稍后重试'
  }
}

// 编辑数字人：点击头像打开，可查看/修改提示词、重新生成形象、删除数字人
const editId = ref<string | null>(null)
const editing = computed(() => store.digitalHumans.find((d) => d.id === editId.value))
const editName = ref('')
const editStyle = ref('')
const editDesc = ref('')
const editPrompt = ref('')
const editError = ref('')
const regenBusy = computed(() => !!editing.value && store.dhRegeneratingId === editing.value.id)

const openEdit = (id: string) => {
  const dh = store.digitalHumans.find((d) => d.id === id)
  if (!dh) return
  editId.value = id
  editName.value = dh.name
  editStyle.value = dh.style
  editDesc.value = dh.description
  editPrompt.value = dh.avatarPrompt ?? ''
  editError.value = ''
}

const closeEdit = () => {
  if (regenBusy.value) return
  editId.value = null
}

/** 把表单草稿写回 store（含 localStorage 持久化） */
const applyEdit = () => {
  if (!editing.value) return
  store.updateDigitalHuman(editing.value.id, {
    name: editName.value.trim() || editing.value.name,
    style: editStyle.value.trim() || '自定义',
    description: editDesc.value.trim() || editing.value.description,
    avatarPrompt: editPrompt.value.trim(),
  })
}

const saveEdit = () => {
  applyEdit()
  editId.value = null
}

/** 用当前提示词重新生成形象，成功后图片本地化存储并替换头像 */
const regenAvatar = async () => {
  if (!editing.value || regenBusy.value || !editPrompt.value.trim()) return
  editError.value = ''
  applyEdit()
  try {
    await store.regenerateDigitalHumanAvatar(editing.value.id, editPrompt.value.trim())
  } catch (e) {
    editError.value = e instanceof Error ? e.message : '生成失败，请稍后重试'
  }
}

const removeDh = () => {
  if (!editing.value || regenBusy.value) return
  if (!window.confirm(`确定删除数字人「${editing.value.name}」？将同时从角色阵容与所有分镜中移除`)) return
  store.deleteDigitalHuman(editing.value.id)
  editId.value = null
}
</script>

<template>
  <Teleport to="body">
    <div v-if="store.libraryOpen" class="lib-mask" @click.self="store.closeLibrary()">
      <div class="lib-modal">
        <header class="lib-header">
          <div>
            <h3>数字人资产库 · 角色阵容</h3>
            <p class="lib-hint">点击卡片加入/移出本 MV 的角色阵容，全片统一使用同一批角色；每个分镜再从阵容中挑选出演角色（可空镜头 / 可多人）</p>
          </div>
          <div class="header-actions">
            <button class="btn-gen-dh" :disabled="store.dhGenerating" @click="genOpen = !genOpen">
              <AppIcon name="sparkles" :size="14" /> 生成数字人
            </button>
            <button class="close-btn" title="关闭" @click="store.closeLibrary()"><AppIcon name="close" :size="15" /></button>
          </div>
        </header>

        <!-- 生成数字人表单（真实生图接口） -->
        <div v-if="genOpen" class="gen-panel">
          <div class="gen-row">
            <input v-model="genName" class="gen-input gen-name" placeholder="角色名称（必填）" />
            <input v-model="genStyle" class="gen-input gen-style" list="dh-style-options" placeholder="风格，如：韩系青春" />
            <datalist id="dh-style-options">
              <option v-for="s in styles.slice(1)" :key="s" :value="s" />
            </datalist>
          </div>
          <textarea
            v-model="genDesc"
            class="gen-desc"
            rows="2"
            placeholder="形象描述提示词（必填），例如：22岁短发女生，穿 oversize 卫衣，元气笑容，阳光温暖…"
          />
          <div class="gen-actions">
            <span v-if="genError" class="gen-error">{{ genError }}</span>
            <button class="gen-submit" :disabled="!canGen || store.dhGenerating" @click="submitGen">
              <span v-if="store.dhGenerating" class="spinner light" />
              <AppIcon v-else name="sparkles" :size="14" />
              {{ store.dhGenerating ? '正在生成形象（约需半分钟）…' : '开始生成' }}
            </button>
          </div>
        </div>

        <!-- 当前阵容 -->
        <div class="cast-bar">
          <span class="cast-label">当前阵容（{{ store.castHumans.length }}）：</span>
          <template v-if="store.castHumans.length">
            <span v-for="dh in store.castHumans" :key="dh.id" class="cast-chip">
              <img :src="dh.avatar" :alt="dh.name" />
              {{ dh.name }}
              <button class="cast-remove" title="移出阵容" @click="store.toggleCast(dh.id)"><AppIcon name="close" :size="10" /></button>
            </span>
          </template>
          <span v-else class="cast-empty">暂无角色，所有分镜将以空镜头生成</span>
        </div>

        <!-- 风格筛选 -->
        <div class="style-tabs">
          <button
            v-for="s in styles"
            :key="s"
            class="style-tab"
            :class="{ active: activeStyle === s }"
            @click="activeStyle = s"
          >
            {{ s }}
          </button>
        </div>

        <!-- 数字人卡片 -->
        <div class="dh-grid">
          <div
            v-for="dh in filtered"
            :key="dh.id"
            class="dh-card"
            :class="{ active: store.castIds.includes(dh.id) }"
            @click="store.toggleCast(dh.id)"
          >
            <div class="dh-portrait" title="点击编辑数字人" @click.stop="openEdit(dh.id)">
              <img :src="dh.avatar" :alt="dh.name" />
              <span v-if="store.castIds.includes(dh.id)" class="dh-check"><AppIcon name="check" :size="11" /> 已入阵容</span>
              <span class="dh-edit-badge"><AppIcon name="edit" :size="11" /> 编辑</span>
            </div>
            <div class="dh-info">
              <div class="dh-name-row">
                <strong>{{ dh.name }}</strong>
                <span class="dh-style">{{ dh.style }}</span>
              </div>
              <p class="dh-desc">{{ dh.description }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 数字人编辑弹窗：查看/修改提示词、重新生成形象、删除 -->
    <div v-if="editing" class="dh-edit-mask" @click.self="closeEdit">
      <div class="dh-edit-modal">
        <header class="edit-head">
          <h3><AppIcon name="edit" :size="15" /> 编辑数字人 · {{ editing.name }}</h3>
          <button class="close-btn" title="关闭" @click="closeEdit"><AppIcon name="close" :size="15" /></button>
        </header>
        <div class="edit-body">
          <div class="edit-portrait">
            <img :src="editing.avatar" :alt="editing.name" />
            <div v-if="regenBusy" class="edit-regen-mask">
              <span class="spinner light" />
              正在重新生成形象…
            </div>
          </div>
          <div class="edit-form">
            <div class="edit-row">
              <div class="edit-col">
                <label class="edit-label">名称</label>
                <input v-model="editName" class="gen-input" />
              </div>
              <div class="edit-col">
                <label class="edit-label">风格</label>
                <input v-model="editStyle" class="gen-input" list="dh-style-options" />
              </div>
            </div>
            <label class="edit-label">形象描述</label>
            <textarea v-model="editDesc" class="gen-desc" rows="2" />
            <label class="edit-label">生成提示词（修改后可重新生成形象，图片自动本地化存储）</label>
            <textarea v-model="editPrompt" class="gen-desc edit-prompt" rows="5" />
            <span v-if="editError" class="gen-error">{{ editError }}</span>
          </div>
        </div>
        <footer class="edit-foot">
          <button class="edit-delete" :disabled="regenBusy" @click="removeDh">
            <AppIcon name="trash" :size="13" /> 删除数字人
          </button>
          <div class="edit-foot-right">
            <button class="edit-cast" :class="{ in: store.castIds.includes(editing.id) }" @click="store.toggleCast(editing.id)">
              <AppIcon :name="store.castIds.includes(editing.id) ? 'check' : 'users'" :size="13" />
              {{ store.castIds.includes(editing.id) ? '已在阵容 · 点击移出' : '加入当前阵容' }}
            </button>
            <button class="edit-regen" :disabled="regenBusy || !editPrompt.trim()" @click="regenAvatar">
              <span v-if="regenBusy" class="spinner" />
              <AppIcon v-else name="sparkles" :size="13" />
              {{ regenBusy ? '生成中（约需半分钟）…' : '重新生成形象' }}
            </button>
            <button class="edit-save" :disabled="regenBusy" @click="saveEdit">保存</button>
          </div>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.lib-mask {
  position: fixed;
  inset: 0;
  z-index: 120;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.lib-modal {
  width: 860px;
  max-width: 100%;
  max-height: 90vh;
  background: #fff;
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.25);
}
.lib-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 18px 22px 12px;
  border-bottom: 1px solid var(--border);
}
.lib-header h3 {
  margin: 0;
  font-size: 17px;
}
.lib-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.close-btn {
  border: none;
  background: transparent;
  font-size: 16px;
  color: var(--text-secondary);
  cursor: pointer;
}
.close-btn:hover {
  color: var(--text);
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.btn-gen-dh {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--primary);
  background: var(--primary-light);
  color: var(--primary);
  border-radius: 16px;
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.btn-gen-dh:hover:not(:disabled) {
  background: var(--primary);
  color: #fff;
}
.btn-gen-dh:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 生成数字人表单 */
.gen-panel {
  margin: 12px 22px 0;
  padding: 12px 14px;
  border: 1px dashed var(--primary);
  border-radius: 12px;
  background: var(--primary-light);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.gen-row {
  display: flex;
  gap: 8px;
}
.gen-input {
  border: 1px solid var(--border-dark);
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 13px;
  font-family: inherit;
  color: var(--text);
  outline: none;
  background: #fff;
}
.gen-input:focus {
  border-color: var(--primary);
}
.gen-name {
  flex: 0 0 180px;
  min-width: 0;
}
.gen-style {
  flex: 1;
  min-width: 0;
}
.gen-desc {
  border: 1px solid var(--border-dark);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
  font-family: inherit;
  color: var(--text);
  outline: none;
  resize: vertical;
  background: #fff;
}
.gen-desc:focus {
  border-color: var(--primary);
}
.gen-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}
.gen-error {
  font-size: 12px;
  color: #d43a1a;
  margin-right: auto;
}
.gen-submit {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: var(--primary);
  color: #fff;
  border-radius: 8px;
  padding: 8px 18px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s;
}
.gen-submit:hover:not(:disabled) {
  opacity: 0.88;
}
.gen-submit:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* 当前阵容 */
.cast-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 12px 22px 0;
}
.cast-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
}
.cast-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--primary);
  background: var(--primary-light);
  color: var(--primary);
  border-radius: 16px;
  padding: 3px 8px 3px 4px;
  font-size: 13px;
}
.cast-chip img {
  width: 22px;
  height: 28px;
  border-radius: 6px;
  object-fit: cover;
}
.cast-remove {
  border: none;
  background: transparent;
  color: var(--primary);
  display: inline-flex;
  align-items: center;
  cursor: pointer;
  padding: 0 2px;
}
.cast-empty {
  font-size: 13px;
  color: var(--text-secondary);
}

/* 风格筛选 */
.style-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  padding: 12px 22px 0;
}
.style-tab {
  border: 1px solid var(--border-dark);
  border-radius: 16px;
  background: #fff;
  color: var(--text);
  font-size: 13px;
  padding: 5px 14px;
  cursor: pointer;
  transition: all 0.15s;
}
.style-tab:hover {
  border-color: var(--primary);
  color: var(--primary);
}
.style-tab.active {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

/* 数字人卡片 */
.dh-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  padding: 16px 22px 22px;
  overflow-y: auto;
}
.dh-card {
  border: 2px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.15s, transform 0.1s, box-shadow 0.15s;
  background: #fff;
}
.dh-card:hover {
  border-color: rgba(255, 90, 44, 0.5);
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.08);
}
.dh-card.active {
  border-color: var(--primary);
}
.dh-portrait {
  position: relative;
  aspect-ratio: 3 / 4;
  background: #f5f5f5;
}
.dh-portrait img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.dh-check {
  position: absolute;
  top: 8px;
  right: 8px;
  background: var(--primary);
  color: #fff;
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.dh-edit-badge {
  position: absolute;
  left: 8px;
  bottom: 8px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  opacity: 0;
  transition: opacity 0.15s;
  pointer-events: none;
}
.dh-portrait:hover .dh-edit-badge {
  opacity: 1;
}
.dh-info {
  padding: 8px 10px 10px;
}
.dh-name-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.dh-name-row strong {
  font-size: 14px;
}
.dh-style {
  font-size: 11px;
  color: var(--primary);
  background: var(--primary-light);
  padding: 2px 8px;
  border-radius: 8px;
  white-space: nowrap;
}
.dh-desc {
  margin: 5px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 数字人编辑弹窗 */
.dh-edit-mask {
  position: fixed;
  inset: 0;
  z-index: 130;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.dh-edit-modal {
  width: 640px;
  max-width: 100%;
  max-height: 90vh;
  background: #fff;
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}
.edit-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--border);
}
.edit-head h3 {
  margin: 0;
  font-size: 16px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.edit-body {
  display: flex;
  gap: 16px;
  padding: 16px 20px;
  overflow-y: auto;
}
.edit-portrait {
  position: relative;
  flex: 0 0 200px;
  aspect-ratio: 3 / 4;
  align-self: flex-start;
  border-radius: 12px;
  overflow: hidden;
  background: #f5f5f5;
}
.edit-portrait img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.edit-regen-mask {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.edit-form {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.edit-row {
  display: flex;
  gap: 10px;
}
.edit-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.edit-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
  margin-top: 4px;
}
.edit-prompt {
  flex: 1;
}
.edit-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 20px 16px;
  border-top: 1px solid var(--border);
}
.edit-foot-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.edit-delete {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid #d43a1a;
  background: #fff;
  color: #d43a1a;
  border-radius: 8px;
  padding: 7px 14px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}
.edit-delete:hover:not(:disabled) {
  background: #d43a1a;
  color: #fff;
}
.edit-delete:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.edit-regen {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--primary);
  background: var(--primary-light);
  color: var(--primary);
  border-radius: 8px;
  padding: 7px 14px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.edit-cast {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border-dark);
  background: #fff;
  color: var(--text);
  border-radius: 8px;
  padding: 7px 14px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.edit-cast:hover {
  border-color: var(--primary);
  color: var(--primary);
}
.edit-cast.in {
  border-color: var(--primary);
  background: var(--primary-light);
  color: var(--primary);
}
.edit-regen:hover:not(:disabled) {
  background: var(--primary);
  color: #fff;
}
.edit-regen:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.edit-save {
  border: none;
  background: var(--primary);
  color: #fff;
  border-radius: 8px;
  padding: 8px 22px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s;
}
.edit-save:hover:not(:disabled) {
  opacity: 0.88;
}
.edit-save:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
</style>
