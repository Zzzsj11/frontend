<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useProjectStore } from '../stores/project'
import type { SongProject, SongTask } from '../types'
import AppIcon from './AppIcon.vue'

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
const submitCreate = async () => {
  const name = newName.value.trim()
  if (!name || createBusy.value) return
  createBusy.value = true
  try {
    await store.createSongProject(name)
    creating.value = false
    newName.value = ''
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
    el.select()
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
const removeSong = (song: SongProject) => {
  if (window.confirm(`确定删除歌曲项目「${song.name}」？其下所有子项目将一并删除`))
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
const removeTask = (songId: string, task: SongTask) => {
  if (window.confirm(`确定删除子项目「${task.title}」？`)) store.deleteSongTask(songId, task.id)
}

onMounted(() => {
  store.loadSongProjects()
})
</script>

<template>
  <aside class="panel song-sidebar">
    <button class="create-btn" @click="creating = !creating">
      <AppIcon name="plus" :size="14" />
      创建歌曲项目
    </button>

    <div v-if="creating" class="create-form">
      <input
        v-model="newName"
        class="create-input"
        placeholder="歌曲名称，回车创建"
        :disabled="createBusy"
        @keyup.enter="submitCreate"
      />
      <button class="create-ok" :disabled="!newName.trim() || createBusy" @click="submitCreate">
        <span v-if="createBusy" class="spinner light" />
        <template v-else>创建</template>
      </button>
    </div>

    <div class="section-title">
      歌曲项目
      <span v-if="store.songSwitching" class="spinner side-spinner" />
    </div>

    <div class="song-list">
      <div v-for="song in store.songProjects" :key="song.id" class="song-group">
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
            <button class="folder-main" @click="toggleCollapse(song.id)">
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
          <p v-if="!song.tasks.length" class="task-empty">暂无任务</p>
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
  overflow-y: auto;
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
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 0;
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
}
.task-item {
  display: flex;
  align-items: center;
  color: var(--text);
  border-radius: 8px;
  transition: background 0.12s;
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
  margin: 2px 0 6px;
  padding-left: 14px;
  font-size: 12px;
  color: var(--text-secondary);
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
.task-item:hover .row-actions {
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
