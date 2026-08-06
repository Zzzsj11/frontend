<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useProjectStore } from '../stores/project'
import type { SongProject, SongTask } from '../types'
import AppIcon from './AppIcon.vue'
import { confirmDialog } from '../composables/useConfirmDialog'

const store = useProjectStore()

/** 折叠的歌曲目录 id 集合（默认全部展开） */
const collapsed = ref<Set<string>>(new Set())
const toggleCollapse = (songId: string) => {
  const next = new Set(collapsed.value)
  next.has(songId) ? next.delete(songId) : next.add(songId)
  collapsed.value = next
}

// 新建歌曲项目：内联输入框
const creating = ref(false)
const newName = ref('')
const createBusy = ref(false)
const createError = ref('')
const submitCreate = async () => {
  const name = newName.value.trim()
  if (!name || createBusy.value) return
  createBusy.value = true
  createError.value = ''
  try {
    const song = await store.createSongProject(name)
    const nextCollapsed = new Set(collapsed.value)
    nextCollapsed.delete(song.id)
    collapsed.value = nextCollapsed
    await store.selectSongTask(song.id, null)
    creating.value = false
    newName.value = ''
  } catch (err) {
    createError.value = err instanceof Error ? err.message : '创建失败，请稍后重试'
  } finally {
    createBusy.value = false
  }
}

const pickTask = (songId: string, taskId: string) => {
  if (store.songSwitching) return
  store.selectSongTask(songId, taskId)
}

// 重命名输入框挂载时自动聚焦选中
const autoFocus = (el: unknown) => {
  if (el instanceof HTMLInputElement) {
    el.focus()
  }
}

// ---------- 歌曲项目(目录)：重命名 / 删除 ----------
const editingSongId = ref<string | null>(null)
const editingSongName = ref('')
const startRenameSong = (song: SongProject) => {
  editingSongId.value = song.id
  editingSongName.value = song.name
}
const commitRenameSong = () => {
  if (editingSongId.value) store.renameSongProject(editingSongId.value, editingSongName.value)
  editingSongId.value = null
}
const cancelRenameSong = () => {
  editingSongId.value = null
}
const removeSong = async (song: SongProject) => {
  if (await confirmDialog({ title: '删除歌曲项目', message: `确定删除歌曲项目「${song.name}」？其下所有子项目将一并删除。`, confirmText: '删除', danger: true }))
    store.deleteSongProject(song.id)
}

// ---------- 子项目(任务)：重命名 / 删除 ----------
const editingTaskId = ref<string | null>(null)
const editingTaskName = ref('')
const startRenameTask = (task: SongTask) => {
  editingTaskId.value = task.id
  editingTaskName.value = task.title
}
const commitRenameTask = (songId: string) => {
  if (editingTaskId.value) store.renameSongTask(songId, editingTaskId.value, editingTaskName.value)
  editingTaskId.value = null
}
const cancelRenameTask = () => {
  editingTaskId.value = null
}
const removeTask = async (songId: string, task: SongTask) => {
  if (await confirmDialog({ title: '删除子项目', message: `确定删除子项目「${task.title}」？`, confirmText: '删除', danger: true })) store.deleteSongTask(songId, task.id)
}

const startStoryboard = async (songId: string, type: 'ass' | 'general') => {
  await store.selectSongTask(songId, null)
  type === 'ass' ? store.openMagic() : store.openGeneralStoryboard()
}

onMounted(() => {
  store.loadSongProjects()
})
</script>

<template>
  <aside class="panel song-sidebar">
    <div class="sidebar-top">
      <button class="create-btn" @click="creating = !creating">
        <AppIcon name="plus" :size="14" />
        创建歌曲项目
      </button>

      <div v-if="creating" class="create-form">
        <input
          :ref="autoFocus"
          v-model="newName"
          class="create-input"
          placeholder="歌曲名称，回车创建"
          :disabled="createBusy"
          @keyup.enter="submitCreate"
          @keyup.esc="creating = false"
        />
        <button class="create-ok" :disabled="!newName.trim() || createBusy" @click="submitCreate">
          <span v-if="createBusy" class="spinner light" />
          <template v-else>创建</template>
        </button>
      </div>
      <p v-if="creating && createError" class="create-error">{{ createError }}</p>

      <div class="section-title">
        歌曲项目
        <span v-if="store.songSwitching" class="spinner side-spinner" />
      </div>
    </div>

    <div class="song-list">
      <div v-if="store.songProjectsLoading" class="sidebar-state skeleton-list" aria-label="正在加载歌曲项目">
        <span v-for="i in 4" :key="i" class="skeleton-row" />
      </div>

      <div v-else-if="store.songProjectsError" class="sidebar-state">
        <AppIcon name="folder" :size="24" />
        <p>{{ store.songProjectsError }}</p>
        <button class="state-btn" @click="store.loadSongProjects()">重新加载</button>
      </div>

      <div v-else-if="!store.songProjects.length" class="sidebar-state">
        <AppIcon name="folder" :size="26" />
        <p>还没有歌曲项目</p>
        <button class="state-btn" @click="creating = true">创建第一个项目</button>
      </div>

      <div
        v-for="song in store.songProjects"
        v-show="!store.songProjectsLoading && !store.songProjectsError"
        :key="song.id"
        class="song-group"
      >
        <div class="song-folder" :class="{ current: song.id === store.activeSongId }">
          <input
            v-if="editingSongId === song.id"
            :ref="autoFocus"
            v-model="editingSongName"
            class="rename-input"
            @keyup.enter="commitRenameSong"
            @keyup.esc="cancelRenameSong"
            @blur="commitRenameSong"
            @click.stop
          />
          <template v-else>
            <button
              class="folder-main"
              :aria-expanded="!collapsed.has(song.id)"
              @click="toggleCollapse(song.id)"
            >
              <AppIcon
                name="chevron-right"
                :size="13"
                class="folder-chevron"
                :class="{ expanded: !collapsed.has(song.id) }"
              />
              <AppIcon name="folder" :size="14" />
              <span class="song-name">{{ song.name }}</span>
              <span v-if="song.artist" class="song-artist">{{ song.artist }}</span>
            </button>
            <span class="row-actions">
              <button class="row-act" title="重命名" @click.stop="startRenameSong(song)">
                <AppIcon name="edit" :size="12" />
              </button>
              <button class="row-act danger" title="删除" @click.stop="removeSong(song)">
                <AppIcon name="trash" :size="12" />
              </button>
            </span>
          </template>
        </div>

        <template v-if="!collapsed.has(song.id)">
          <div
            v-for="task in song.tasks"
            :key="task.id"
            class="task-item"
            :class="{ active: song.id === store.activeSongId && task.id === store.activeTaskId }"
          >
            <input
              v-if="editingTaskId === task.id"
              :ref="autoFocus"
              v-model="editingTaskName"
              class="rename-input task-rename"
              @keyup.enter="commitRenameTask(song.id)"
              @keyup.esc="cancelRenameTask"
              @blur="commitRenameTask(song.id)"
              @click.stop
            />
            <template v-else>
              <button
                class="task-main"
                :disabled="store.songSwitching"
                @click="pickTask(song.id, task.id)"
              >
                <span class="task-dot" />
                <span class="task-title">{{ task.title }}</span>
                <span class="task-time">{{ task.updatedAt }}</span>
              </button>
              <span class="row-actions">
                <button class="row-act" title="重命名" @click.stop="startRenameTask(task)">
                  <AppIcon name="edit" :size="12" />
                </button>
                <button class="row-act danger" title="删除" @click.stop="removeTask(song.id, task)">
                  <AppIcon name="trash" :size="12" />
                </button>
              </span>
            </template>
          </div>
          <div v-if="!song.tasks.length" class="task-empty">
            <span>暂无分镜任务</span>
            <div class="empty-actions">
              <button @click="startStoryboard(song.id, 'ass')">ASS 分镜</button>
              <button @click="startStoryboard(song.id, 'general')">通用分镜</button>
            </div>
          </div>
        </template>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.song-sidebar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 10px;
  overflow: hidden;
}
.sidebar-top {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex-shrink: 0;
}
.create-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  border: 1px solid var(--border-dark);
  background: #fff;
  color: var(--text);
  border-radius: 10px;
  padding: 9px 12px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.create-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}
.create-form {
  display: flex;
  gap: 6px;
}
.create-error {
  margin: -5px 4px 0;
  color: #e53935;
  font-size: 11px;
}
.create-input {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--border-dark);
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 13px;
  font-family: inherit;
  color: var(--text);
  outline: none;
}
.create-input:focus {
  border-color: var(--primary);
}
.create-ok {
  border: none;
  background: var(--primary);
  color: #fff;
  border-radius: 8px;
  padding: 0 14px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.create-ok:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
  padding: 2px 6px 0;
}
.side-spinner {
  width: 12px;
  height: 12px;
}
.song-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 2px;
}
.song-group {
  display: flex;
  flex-direction: column;
}
.song-folder {
  display: flex;
  align-items: center;
  color: var(--text-secondary);
  border-radius: 8px;
  transition: background 0.12s;
  position: relative;
}
.folder-main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 7px;
  border: none;
  background: transparent;
  color: inherit;
  border-radius: 8px;
  padding: 7px 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
}
.song-folder:hover {
  background: rgba(0, 0, 0, 0.045);
}
.song-folder.current {
  color: var(--text);
  background: rgba(255, 90, 44, 0.055);
  box-shadow: inset 3px 0 0 var(--primary);
}
.folder-chevron {
  color: var(--text-secondary);
  transition: transform 0.15s, color 0.15s;
}
.folder-chevron.expanded {
  transform: rotate(90deg);
}
.song-folder.current .folder-chevron {
  color: var(--primary);
}
.song-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.song-artist {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-secondary);
  white-space: nowrap;
  max-width: 62px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.task-item {
  display: flex;
  align-items: center;
  color: var(--text);
  border-radius: 8px;
  transition: background 0.12s;
}
.song-folder + .task-item,
.song-folder + .task-empty {
  margin-top: 6px;
}
.task-item + .task-item {
  margin-top: 3px;
}
.task-main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  border: none;
  background: transparent;
  color: inherit;
  border-radius: 8px;
  padding: 7px 8px 7px 14px;
  font-size: 13px;
  font-weight: inherit;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
}
.task-item:hover {
  background: rgba(0, 0, 0, 0.045);
}
.task-item.active {
  background: var(--primary-light);
  color: var(--primary);
  font-weight: 600;
}
.task-main:disabled {
  cursor: wait;
  opacity: 0.7;
}
.task-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--border-dark);
  flex-shrink: 0;
}
.task-item.active .task-dot {
  background: var(--primary);
}
.task-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-time {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.task-item.active .task-time {
  color: var(--primary);
}
.task-empty {
  margin: 4px 6px 8px 14px;
  padding: 8px;
  border: 1px dashed var(--border-dark);
  border-radius: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}
.empty-actions {
  display: flex;
  gap: 5px;
  margin-top: 7px;
}
.empty-actions button,
.state-btn {
  border: 1px solid rgba(255, 90, 44, 0.35);
  border-radius: 7px;
  background: var(--primary-light);
  color: var(--primary);
  padding: 5px 7px;
  font-size: 11px;
  cursor: pointer;
}
.empty-actions button:hover,
.state-btn:hover {
  border-color: var(--primary);
  background: rgba(255, 90, 44, 0.14);
}
.sidebar-state {
  min-height: 150px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 18px 10px;
  color: var(--text-secondary);
  text-align: center;
}
.sidebar-state p {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
}
.skeleton-list {
  align-items: stretch;
  justify-content: flex-start;
  gap: 10px;
}
.skeleton-row {
  display: block;
  height: 34px;
  border-radius: 8px;
  background: linear-gradient(90deg, #f2f2f2 25%, #fafafa 50%, #f2f2f2 75%);
  background-size: 200% 100%;
  animation: sidebar-shimmer 1.2s infinite linear;
}
@keyframes sidebar-shimmer {
  to { background-position: -200% 0; }
}
.row-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  padding-right: 6px;
  opacity: 0;
  transition: opacity 0.12s;
}
.song-folder:hover .row-actions,
.task-item:hover .row-actions,
.song-folder:focus-within .row-actions,
.task-item:focus-within .row-actions {
  opacity: 1;
}
.row-act {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.row-act:hover {
  background: rgba(0, 0, 0, 0.08);
  color: var(--text);
}
.row-act.danger:hover {
  background: rgba(229, 57, 53, 0.12);
  color: #e53935;
}
.row-act:focus-visible,
.folder-main:focus-visible,
.task-main:focus-visible,
.create-btn:focus-visible,
.empty-actions button:focus-visible,
.state-btn:focus-visible {
  outline: 2px solid rgba(255, 90, 44, 0.45);
  outline-offset: 1px;
}
.rename-input {
  flex: 1;
  min-width: 0;
  margin: 3px 6px;
  border: 1px solid var(--primary);
  border-radius: 6px;
  padding: 5px 8px;
  font-size: 13px;
  font-family: inherit;
  color: var(--text);
  background: #fff;
  outline: none;
}
.rename-input.task-rename {
  margin-left: 14px;
}
</style>
