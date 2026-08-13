<script setup lang="ts">
import { computed, ref } from 'vue'
import { useProjectStore } from '../stores/project'
import AppIcon from './AppIcon.vue'
import BaseModal from './base/BaseModal.vue'
import CharacterPortrait from './CharacterPortrait.vue'
import ImageZoom from './ImageZoom.vue'
import { confirmDialog } from '../composables/useConfirmDialog'

const store = useProjectStore()

const activeStyle = ref('全部')
const styles = computed(() => ['全部', ...store.allDhStyles])
const filtered = computed(() =>
  activeStyle.value === '全部'
    ? store.digitalHumans
    : store.digitalHumans.filter((d) => d.style === activeStyle.value),
)

// 风格分类管理：增删改查（分类独立于数字人存在，重命名/删除会同步更新所属数字人）
const styleManaging = ref(false)
const styleAdding = ref(false)
const styleNewName = ref('')
const styleEditingName = ref<string | null>(null)
const styleEditValue = ref('')

// 行内输入框挂载时自动聚焦选中
const autoFocus = (el: unknown) => {
  if (el instanceof HTMLInputElement) {
    el.focus()
    el.select()
  }
}

const toggleStyleManaging = () => {
  styleManaging.value = !styleManaging.value
  styleEditingName.value = null
  styleAdding.value = false
}

const confirmAddStyle = () => {
  const name = styleNewName.value.trim()
  if (name) store.addDhStyle(name)
  styleAdding.value = false
  styleNewName.value = ''
}

const cancelAddStyle = () => {
  styleNewName.value = ''
  styleAdding.value = false
}

const startRenameStyle = (s: string) => {
  styleEditingName.value = s
  styleEditValue.value = s
}

const confirmRenameStyle = () => {
  const oldName = styleEditingName.value
  if (!oldName) return
  styleEditingName.value = null
  const newName = styleEditValue.value.trim()
  if (newName && newName !== oldName && store.renameDhStyle(oldName, newName)) {
    if (activeStyle.value === oldName) activeStyle.value = newName
  }
}

const cancelRenameStyle = () => {
  styleEditingName.value = null
}

const removeStyle = async (s: string) => {
  const count = store.digitalHumans.filter((d) => d.style === s).length
  const msg = count
    ? `确定删除分类「${s}」？该分类下的 ${count} 个数字人将归入「未分类」`
    : `确定删除分类「${s}」？`
  if (
    !(await confirmDialog({
      title: '删除风格分类',
      message: msg,
      confirmText: '删除',
      danger: true,
    }))
  )
    return
  store.deleteDhStyle(s)
  if (activeStyle.value === s) activeStyle.value = '全部'
}

// 上传自定义数字人：自备头像 + 名称/风格（名称、风格为必填，头像/描述可选）
const uploadOpen = ref(false)
const upName = ref('')
const upStyle = ref('')
const upDesc = ref('')
const upAvatar = ref('')
const upFileRef = ref<HTMLInputElement>()
const uploadError = ref('')
const canUpload = computed(() => !!upName.value.trim() && !!upStyle.value.trim())

const openUpload = () => {
  uploadOpen.value = !uploadOpen.value
  if (uploadOpen.value) {
    uploadError.value = ''
  }
}

// 选择头像：等比缩放到 3:4 竖版范围内并转 data URL，提交时上传 TOS
const onUpAvatarChange = (e: Event) => {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file || !file.type.startsWith('image/')) return
  const url = URL.createObjectURL(file)
  const img = new Image()
  img.onload = () => {
    const ratio = Math.min(600 / img.width, 800 / img.height, 1)
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(img.width * ratio)
    canvas.height = Math.round(img.height * ratio)
    canvas.getContext('2d')?.drawImage(img, 0, 0, canvas.width, canvas.height)
    upAvatar.value = canvas.toDataURL('image/jpeg', 0.85)
    URL.revokeObjectURL(url)
  }
  img.src = url
}

// 未上传头像时，用「名称首字 + 风格配色」生成 3:4 竖版占位头像
const initialsAvatar = (name: string, style: string): string => {
  const ch = name.trim().charAt(0) || '?'
  const palette = ['var(--primary)', '#3b82f6', '#10b981', '#8b5cf6', '#ef4444', '#f59e0b']
  let hash = 0
  for (const c of name + style) hash = (hash * 31 + c.charCodeAt(0)) >>> 0
  const bg = palette[hash % palette.length]
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400">` +
    `<rect width="300" height="400" fill="${bg}"/>` +
    `<text x="150" y="205" font-size="150" fill="#fff" text-anchor="middle" ` +
    `dominant-baseline="central" font-family="sans-serif" font-weight="600">${ch}</text></svg>`
  return 'data:image/svg+xml,' + encodeURIComponent(svg)
}

const submitUpload = async () => {
  if (!canUpload.value || store.dhGenerating) return
  const name = upName.value.trim()
  const style = upStyle.value.trim()
  uploadError.value = ''
  try {
    await store.addCustomDigitalHuman({
      name,
      style,
      description: upDesc.value.trim(),
      avatar: upAvatar.value || initialsAvatar(name, style),
    })
    // 生成完成后才清空
    uploadOpen.value = false
    upName.value = ''
    upStyle.value = ''
    upDesc.value = ''
    upAvatar.value = ''
    activeStyle.value = '全部'
  } catch (error) {
    uploadError.value = error instanceof Error ? error.message : '数字人上传失败，请稍后重试'
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

// 大图预览
const previewImage = ref<{ src: string; alt: string } | null>(null)
const showPreview = (dh: { originalAvatar?: string; avatar: string; name: string }) => {
  previewImage.value = { src: dh.originalAvatar || dh.avatar, alt: dh.name }
}
const closePreview = () => {
  previewImage.value = null
}

window.addEventListener('keydown', (e: KeyboardEvent) => {
  if (e.key === 'Escape' && previewImage.value) closePreview()
})

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

/** 把表单草稿写回 store，并同步保存到后端 */
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

/** 用当前提示词重新生成形象，成功后图片本地化存储并替换头像（会覆盖当前形象，需二次确认） */
const regenAvatar = async () => {
  if (!editing.value || regenBusy.value || !editPrompt.value.trim()) return
  if (
    !(await confirmDialog({
      title: '重新生成数字人形象',
      message: `确定重新生成「${editing.value.name}」的形象？当前形象将被覆盖。`,
      confirmText: '重新生成',
    }))
  )
    return
  editError.value = ''
  applyEdit()
  try {
    await store.regenerateDigitalHumanAvatar(editing.value.id, editPrompt.value.trim())
  } catch (e) {
    editError.value = e instanceof Error ? e.message : '生成失败，请稍后重试'
  }
}

const removeDh = async () => {
  if (!editing.value || regenBusy.value) return
  if (
    !(await confirmDialog({
      title: '删除数字人',
      message: `确定删除数字人「${editing.value.name}」？将同时从角色阵容与所有视频中移除。`,
      confirmText: '删除',
      danger: true,
    }))
  )
    return
  store.deleteDigitalHuman(editing.value.id)
  editId.value = null
}
</script>

<template>
  <BaseModal
    :open="store.libraryOpen"
    width="860px"
    max-height="90vh"
    aria-label="数字人资产库"
    @close="store.closeLibrary()"
  >
    <template #title>数字人资产库 · 角色阵容</template>
    <template #actions>
      <button class="btn-upload-dh" @click="openUpload">
        <AppIcon name="image" :size="14" /> 上传数字人
      </button>
    </template>
    <p class="lib-hint">
      悬停人物卡片可加入/移出阵容、看大图或查看详情；阵容为全片统一角色，
      每个视频再从阵容中挑选出演角色（可空镜头 / 可多人）
    </p>

    <!-- 风格分类候选项（生成 / 上传 / 编辑 三处共用） -->
    <datalist id="dh-style-options">
      <option v-for="s in styles.slice(1)" :key="s" :value="s" />
    </datalist>
    <div v-show="uploadOpen" class="gen-panel upload-panel">
      <div class="upload-body">
        <div
          class="upload-avatar"
          :class="{ filled: upAvatar, disabled: store.dhGenerating }"
          :title="
            store.dhGenerating ? '正在生成中，请稍候' : '点击上传人物参考图（将统一生成三视图）'
          "
          @click="!store.dhGenerating && upFileRef?.click()"
        >
          <img v-if="upAvatar" :src="upAvatar" alt="头像预览" />
          <template v-else>
            <AppIcon name="image" :size="24" />
            <span>上传人物参考图<br />（推荐）</span>
          </template>
        </div>
        <input ref="upFileRef" type="file" accept="image/*" hidden @change="onUpAvatarChange" />
        <div class="upload-fields">
          <div class="gen-row">
            <input
              v-model="upName"
              class="gen-input gen-name"
              placeholder="人物名称（必填）"
              :disabled="store.dhGenerating"
            />
            <input
              v-model="upStyle"
              class="gen-input gen-style"
              list="dh-style-options"
              placeholder="风格分类（必填）"
              :disabled="store.dhGenerating"
            />
          </div>
          <textarea
            v-model="upDesc"
            class="gen-desc"
            rows="2"
            placeholder="形象描述（可选）"
            :disabled="store.dhGenerating"
          />
        </div>
      </div>
      <div class="gen-actions">
        <span class="upload-tip"
          >参考图会先存入 TOS，再按系统人物样式生成正面、侧面、背面三视图</span
        >
        <button
          class="gen-submit"
          :disabled="!canUpload || store.dhGenerating"
          @click="submitUpload"
        >
          <span v-if="store.dhGenerating" class="spinner light" />
          <AppIcon v-else name="check" :size="14" />
          {{
            store.dhGenerating
              ? store.dhGeneratingPhase === 'uploading'
                ? '正在上传…'
                : '正在生成三视图…'
              : '添加到资产库'
          }}
        </button>
      </div>
      <p v-if="uploadError" class="error-tip" role="alert">{{ uploadError }}</p>
    </div>

    <!-- 当前阵容 -->
    <div class="cast-bar">
      <span class="cast-label">当前阵容（{{ store.castHumans.length }}）：</span>
      <template v-if="store.castHumans.length">
        <span v-for="dh in store.castHumans" :key="dh.id" class="cast-chip">
          <CharacterPortrait :src="dh.avatar" :alt="dh.name" />
          {{ dh.name }}
          <button class="cast-remove" title="移出阵容" @click="store.toggleCast(dh.id)">
            <AppIcon name="close" :size="10" />
          </button>
        </span>
      </template>
      <span v-else class="cast-empty">暂无角色，所有视频将以空镜头生成</span>
    </div>

    <!-- 风格筛选 + 分类管理（增删改查） -->
    <div class="style-tabs">
      <template v-for="s in styles" :key="s">
        <span v-if="styleEditingName === s" class="style-tab style-edit">
          <input
            :ref="autoFocus"
            v-model="styleEditValue"
            class="style-edit-input"
            @keyup.enter="confirmRenameStyle"
            @keyup.esc="cancelRenameStyle"
            @blur="confirmRenameStyle"
          />
        </span>
        <button
          v-else
          class="style-tab"
          :class="{ active: activeStyle === s, managing: styleManaging && s !== '全部' }"
          @click="activeStyle = s"
        >
          {{ s }}
          <template v-if="styleManaging && s !== '全部' && !store.systemDhStyles.includes(s)">
            <span class="style-op" title="重命名分类" @click.stop="startRenameStyle(s)">
              <AppIcon name="edit" :size="11" />
            </span>
            <span class="style-op danger" title="删除分类" @click.stop="removeStyle(s)">
              <AppIcon name="trash" :size="11" />
            </span>
          </template>
        </button>
      </template>
      <span v-if="styleAdding" class="style-tab style-edit">
        <input
          :ref="autoFocus"
          v-model="styleNewName"
          class="style-edit-input"
          placeholder="新分类名称，回车确认"
          @keyup.enter="confirmAddStyle"
          @keyup.esc="cancelAddStyle"
          @blur="confirmAddStyle"
        />
      </span>
      <button v-else class="style-tab style-add" title="新增分类" @click="styleAdding = true">
        <AppIcon name="plus" :size="12" /> 分类
      </button>
      <button
        class="style-tab style-manage"
        :class="{ on: styleManaging }"
        @click="toggleStyleManaging"
      >
        <AppIcon :name="styleManaging ? 'check' : 'edit'" :size="12" />
        {{ styleManaging ? '完成' : '管理分类' }}
      </button>
    </div>

    <!-- 数字人卡片 -->
    <div class="dh-grid">
      <div
        v-for="dh in filtered"
        :key="dh.id"
        class="dh-card"
        :class="{ active: store.castIds.includes(dh.id) }"
      >
        <div class="dh-portrait" title="点击查看大图" @click="showPreview(dh)">
          <CharacterPortrait :src="dh.avatar" :alt="dh.name" />
          <span v-show="store.castIds.includes(dh.id)" class="dh-check"
            ><AppIcon name="check" :size="11" /> 已入阵容</span
          >
          <!-- 底部滑入操作层：加入/移出阵容、大图、详情；点击图片其他区域 = 查看大图 -->
          <div class="dh-actions" @click.stop>
            <button
              class="dh-action"
              :class="store.castIds.includes(dh.id) ? 'danger' : 'primary'"
              @click.stop="store.toggleCast(dh.id)"
            >
              <AppIcon :name="store.castIds.includes(dh.id) ? 'close' : 'plus'" :size="13" />
              {{ store.castIds.includes(dh.id) ? '移出阵容' : '加入阵容' }}
            </button>
            <div class="dh-action-row">
              <button class="dh-action small" @click.stop="showPreview(dh)">
                <AppIcon name="zoom-in" :size="12" /> 大图
              </button>
              <button class="dh-action small" @click.stop="openEdit(dh.id)">
                <AppIcon name="user" :size="12" /> 详情
              </button>
            </div>
          </div>
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
  </BaseModal>

  <!-- 数字人编辑弹窗：查看/修改提示词、重新生成形象、删除 -->
  <BaseModal
    :open="!!editing"
    level="nested"
    width="640px"
    max-height="90vh"
    :aria-label="`编辑数字人 · ${editing?.name ?? ''}`"
    @close="closeEdit"
  >
    <template #title>
      <AppIcon name="edit" :size="15" /> 编辑数字人 · {{ editing?.name }}
    </template>
    <template v-if="editing">
      <div class="edit-body">
        <div class="edit-portrait" title="点击查看大图" @click="showPreview(editing)">
          <img :src="editing.originalAvatar || editing.avatar" :alt="editing.name" />
          <ImageZoom
            :src="editing.originalAvatar || editing.avatar"
            :alt="`${editing.name} · 原图预览`"
          />
          <div v-if="regenBusy" class="edit-regen-mask">
            <span class="spinner light" />
            正在重新生成形象…
          </div>
        </div>
        <div class="edit-form">
          <div class="edit-row">
            <div class="edit-col">
              <label class="edit-label">名称</label>
              <input v-model="editName" class="gen-input" :disabled="editing.readOnly" />
            </div>
            <div class="edit-col">
              <label class="edit-label">风格</label>
              <input
                v-model="editStyle"
                class="gen-input"
                list="dh-style-options"
                :disabled="editing.readOnly"
              />
            </div>
          </div>
          <label class="edit-label">形象描述</label>
          <textarea v-model="editDesc" class="gen-desc" rows="2" :disabled="editing.readOnly" />
          <label class="edit-label">生成提示词（修改后可重新生成形象，图片自动存储到 TOS）</label>
          <textarea
            v-model="editPrompt"
            class="gen-desc edit-prompt"
            rows="5"
            :disabled="editing.readOnly"
          />
          <span v-if="editing.readOnly" class="readonly-tip"
            >系统人物为全局只读资产，所有用户均可使用，但不能编辑、重新生成或删除。</span
          >
          <span v-if="editError" class="gen-error">{{ editError }}</span>
        </div>
      </div>
    </template>
    <template v-if="editing" #footer>
      <button v-if="!editing.readOnly" class="edit-delete" :disabled="regenBusy" @click="removeDh">
        <AppIcon name="trash" :size="13" /> 删除数字人
      </button>
      <div class="edit-foot-right">
        <button
          class="edit-cast"
          :class="{ in: store.castIds.includes(editing.id) }"
          @click="store.toggleCast(editing.id)"
        >
          <AppIcon :name="store.castIds.includes(editing.id) ? 'check' : 'users'" :size="13" />
          {{ store.castIds.includes(editing.id) ? '已在阵容 · 点击移出' : '加入当前阵容' }}
        </button>
        <button
          v-if="!editing.readOnly"
          class="edit-regen"
          :disabled="regenBusy || !editPrompt.trim()"
          @click="regenAvatar"
        >
          <span v-if="regenBusy" class="spinner" />
          <AppIcon v-else name="sparkles" :size="13" />
          {{ regenBusy ? '生成中（约需半分钟）…' : '重新生成形象' }}
        </button>
        <button v-if="!editing.readOnly" class="edit-save" :disabled="regenBusy" @click="saveEdit">
          保存
        </button>
        <button v-else class="edit-save" @click="closeEdit">关闭</button>
      </div>
    </template>
  </BaseModal>

  <!-- 大图预览 -->
  <Teleport to="body">
    <div v-if="previewImage" class="preview-mask" @click.self="closePreview">
      <div class="preview-dialog">
        <button class="preview-close" @click="closePreview">
          <AppIcon name="close" :size="18" />
        </button>
        <img :src="previewImage.src" :alt="previewImage.alt" />
        <span>{{ previewImage.alt }}</span>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.lib-hint {
  margin: 12px 22px 0;
  font-size: var(--font-sm);
  color: var(--text-secondary);
}
.btn-gen-dh {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--primary);
  background: var(--primary-light);
  color: var(--primary);
  border-radius: var(--radius-lg);
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
.btn-upload-dh {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border-dark);
  background: #fff;
  color: var(--text);
  border-radius: var(--radius-lg);
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.btn-upload-dh:hover {
  border-color: var(--primary);
  color: var(--primary);
}

/* 生成数字人表单 */
.gen-panel {
  margin: 12px 22px 0;
  padding: 12px 14px;
  border: 1px dashed var(--primary);
  border-radius: var(--radius-md);
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
  border-radius: var(--radius-sm);
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
  border-radius: var(--radius-sm);
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
  font-size: var(--font-sm);
  color: var(--primary-active);
  margin-right: auto;
}
.gen-submit {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: var(--primary);
  color: #fff;
  border-radius: var(--radius-sm);
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

/* 上传自定义数字人 */
.upload-panel {
  gap: 10px;
}
.upload-body {
  display: flex;
  gap: 12px;
  align-items: stretch;
}
.upload-avatar {
  flex: 0 0 90px;
  aspect-ratio: 3 / 4;
  border: 1.5px dashed var(--primary);
  border-radius: var(--radius-sm);
  background: #fff;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 11px;
  line-height: 1.4;
  color: var(--text-secondary);
  text-align: center;
  cursor: pointer;
  overflow: hidden;
  transition: border-color 0.15s;
  position: relative;
}
.upload-avatar:hover {
  border-color: var(--primary);
  color: var(--primary);
}
.upload-avatar.filled {
  border-style: solid;
}
.upload-avatar.disabled {
  cursor: not-allowed;
  opacity: 0.65;
}
.upload-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.reference-remove {
  position: absolute;
  top: 5px;
  right: 5px;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.62);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.upload-fields {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.upload-fields .gen-desc {
  flex: 1;
}
.upload-tip {
  font-size: var(--font-sm);
  color: var(--text-secondary);
  margin-right: auto;
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
  border-radius: var(--radius-lg);
  padding: 3px 8px 3px 4px;
  font-size: 13px;
}
.cast-chip img {
  width: 22px;
  height: 28px;
  border-radius: var(--radius-sm);
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
  border-radius: var(--radius-lg);
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
.style-tab.managing {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.style-op {
  display: inline-flex;
  align-items: center;
  opacity: 0.7;
  transition:
    opacity 0.15s,
    color 0.15s;
}
.style-op:hover {
  opacity: 1;
  color: var(--primary);
}
.style-op.danger:hover {
  color: var(--primary-active);
}
.style-tab.active .style-op:hover {
  color: #fff;
}
.style-add,
.style-manage {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-style: dashed;
  color: var(--text-secondary);
}
.style-manage.on {
  border-style: solid;
  border-color: var(--primary);
  background: var(--primary-light);
  color: var(--primary);
}
.style-edit {
  display: inline-flex;
  padding: 0;
  border-color: var(--primary);
  background: #fff;
}
.style-edit-input {
  width: 130px;
  border: none;
  outline: none;
  background: transparent;
  font-size: 13px;
  font-family: inherit;
  color: var(--text);
  padding: 5px 12px;
}

/* 数字人卡片 */
.dh-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 14px;
  padding: 16px 22px 22px;
  flex: 1 1 auto;
  min-height: 200px;
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-gutter: stable;
}
.dh-card {
  border: 2px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
  background: #fff;
  min-height: 200px;
}
.dh-card:hover {
  border-color: rgba(255, 90, 44, 0.5);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.08);
}
.dh-card.active {
  border-color: var(--primary);
}
.dh-portrait {
  position: relative;
  aspect-ratio: 16 / 9;
  background: var(--surface-muted);
  overflow: hidden;
  cursor: pointer;
}
.dh-portrait img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}
.dh-check {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 2;
  background: var(--primary);
  color: #fff;
  font-size: 11px;
  padding: 3px 8px;
  border-radius: var(--radius-sm);
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
/* 底部滑入操作层：默认滑出头像下缘（由 overflow 裁剪）；hover / 键盘聚焦（focus-within）时滑入，触屏（无 hover）常驻 */
.dh-actions {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 16px 8px 8px;
  background: linear-gradient(to top, rgba(12, 12, 15, 0.82), rgba(12, 12, 15, 0));
  transform: translateY(100%);
  transition: transform 0.18s ease;
}
.dh-portrait:hover .dh-actions,
.dh-actions:focus-within {
  transform: translateY(0);
}
@media (hover: none) {
  .dh-actions {
    transform: translateY(0);
  }
}
.dh-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.92);
  color: var(--text);
  font-size: var(--font-sm);
  padding: 6px 14px;
  cursor: pointer;
  font-family: inherit;
  transition:
    color 0.15s,
    background 0.15s;
}
.dh-action:hover {
  background: #fff;
  color: var(--primary);
}
.dh-action.primary {
  background: var(--primary);
  color: #fff;
}
.dh-action.primary:hover {
  background: var(--primary-hover);
  color: #fff;
}
.dh-action.danger {
  background: var(--danger);
  color: #fff;
}
.dh-action.danger:hover {
  background: var(--danger-active);
  color: #fff;
}
.dh-action-row {
  display: flex;
  gap: 8px;
}
.dh-action.small {
  padding: 4px 10px;
  font-size: 11px;
}
.readonly-tip {
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: var(--primary-light);
  color: #a85d29;
  font-size: var(--font-sm);
}
.edit-form :disabled {
  background: #f5f3f1;
  color: #887d74;
  cursor: not-allowed;
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
  font-size: var(--font-md);
}
.dh-style {
  font-size: 11px;
  color: var(--primary);
  background: var(--primary-light);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  white-space: nowrap;
}
.dh-desc {
  margin: 5px 0 0;
  font-size: var(--font-sm);
  color: var(--text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 数字人编辑弹窗 */
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
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--surface-muted);
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
  font-size: var(--font-sm);
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
  font-size: var(--font-sm);
  font-weight: 700;
  color: var(--text-secondary);
  margin-top: 4px;
}
.edit-prompt {
  flex: 1;
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
  margin-right: auto;
  border: 1px solid var(--primary-active);
  background: #fff;
  color: var(--primary-active);
  border-radius: var(--radius-sm);
  padding: 7px 14px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}
.edit-delete:hover:not(:disabled) {
  background: var(--primary-active);
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
  border-radius: var(--radius-sm);
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
  border-radius: var(--radius-sm);
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
  border-radius: var(--radius-sm);
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
.cast-chip .character-portrait {
  width: 22px;
  height: 28px;
  border-radius: var(--radius-sm);
}
.dh-portrait .character-portrait {
  width: 100%;
  height: 100%;
  border-radius: inherit;
}

/* 大图预览 */
.preview-mask {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 28px;
  background: rgba(12, 12, 15, 0.82);
  backdrop-filter: blur(4px);
}
.preview-dialog {
  position: relative;
  display: flex;
  max-width: min(1200px, 92vw);
  max-height: 92vh;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid rgba(255, 255, 255, 0.28);
  border-radius: var(--radius-lg);
  background: #19191c;
  box-shadow: 0 28px 90px rgba(0, 0, 0, 0.55);
}
.preview-dialog img {
  display: block;
  max-width: 100%;
  max-height: calc(92vh - 58px);
  object-fit: contain;
  border-radius: var(--radius-sm);
  background: var(--border);
}
.preview-dialog span {
  color: #fff;
  text-align: center;
  font-size: var(--font-sm);
}
.preview-close {
  position: absolute;
  top: 18px;
  right: 18px;
  z-index: 1;
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.62);
  color: #fff;
  cursor: pointer;
  transition:
    background 0.15s,
    transform 0.15s;
}
.preview-close:hover {
  background: var(--primary);
  transform: scale(1.08);
}
</style>
