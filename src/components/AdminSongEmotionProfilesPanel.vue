<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  createSongEmotion,
  deleteSongEmotion,
  listSongEmotions,
  updateSongEmotion,
  type SongEmotionInput,
  type SongEmotionProfile,
} from '../api/adminSongEmotions'
import { fetchGeneralStoryboardOptions } from '../api/domain'
import type { GeneralStoryboardOptions } from '../types'
import BaseModal from './base/BaseModal.vue'
import SongEmotionEditor from './SongEmotionEditor.vue'

const emptyForm = (): SongEmotionInput => ({
  songCode: '',
  songName: '',
  artists: '',
  primaryCategory: null,
  secondaryCategory: null,
  tertiaryCategory: null,
  materialCategory: '',
  seasons: '',
  atmosphere: '',
})
const items = ref<SongEmotionProfile[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const keyword = ref('')
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const open = ref(false)
const editing = ref(false)
const confirmingCode = ref('')
const form = ref<SongEmotionInput>(emptyForm())
const options = ref<GeneralStoryboardOptions | null>(null)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const query = new URLSearchParams({
      limit: String(pageSize),
      offset: String((page.value - 1) * pageSize),
    })
    if (keyword.value.trim()) query.set('q', keyword.value.trim())
    const result = await listSongEmotions(query)
    items.value = result.items
    total.value = result.total
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}
const loadOptions = async () => {
  try {
    options.value = await fetchGeneralStoryboardOptions()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '分类和季节选项加载失败'
  }
}
onMounted(() => {
  void load()
  void loadOptions()
})
const search = () => {
  page.value = 1
  void load()
}
const clearSearch = () => {
  keyword.value = ''
  page.value = 1
  void load()
}
const turnPage = (delta: number) => {
  page.value = Math.min(pageCount.value, Math.max(1, page.value + delta))
  void load()
}
const selectPage = (event: Event) => {
  const selected = Number((event.target as HTMLSelectElement).value)
  page.value = Math.min(pageCount.value, Math.max(1, selected || 1))
  void load()
}
const showCreate = () => {
  form.value = emptyForm()
  editing.value = false
  open.value = true
}
const showEdit = (item: SongEmotionProfile) => {
  form.value = { ...item }
  editing.value = true
  open.value = true
  confirmingCode.value = ''
}
const close = () => {
  if (!busy.value) open.value = false
}
const save = async () => {
  if (!/^\d{5,}$/.test(form.value.songCode) || !form.value.songName.trim()) {
    error.value = '歌曲编号至少 5 位数字，歌名不能为空'
    return
  }
  busy.value = true
  error.value = ''
  try {
    if (!form.value.materialCategory.trim())
      form.value.materialCategory = [
        form.value.primaryCategory,
        form.value.secondaryCategory,
        form.value.tertiaryCategory,
      ]
        .filter(Boolean)
        .join('-')
    if (editing.value) await updateSongEmotion(form.value)
    else await createSongEmotion(form.value)
    open.value = false
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    busy.value = false
  }
}
const remove = async (songCode: string) => {
  busy.value = true
  error.value = ''
  try {
    await deleteSongEmotion(songCode)
    confirmingCode.value = ''
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '删除失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="panel">
    <div class="toolbar">
      <form class="search" @submit.prevent="search">
        <div class="search-input">
          <input v-model="keyword" placeholder="搜索编号、歌名或歌手" aria-label="搜索歌曲情感库" />
          <button
            v-if="keyword"
            class="clear-search"
            type="button"
            aria-label="清空搜索"
            title="清空搜索"
            @click="clearSearch"
          >
            ×
          </button>
        </div>
        <button type="submit">查询</button>
      </form>
      <button class="primary" type="button" @click="showCreate">新增歌曲</button>
    </div>
    <div class="list-meta">
      <span>歌曲情感数据</span>
      <div class="pager top-pager">
        <span>共 {{ total }} 条</span>
        <button :disabled="page === 1" @click="turnPage(-1)">上一页</button>
        <label class="page-picker"
          >第
          <select :value="page" aria-label="顶部选择页码" @change="selectPage">
            <option v-for="pageNumber in pageCount" :key="pageNumber" :value="pageNumber">
              {{ pageNumber }}
            </option>
          </select>
          / {{ pageCount }} 页</label
        >
        <button :disabled="page * pageSize >= total" @click="turnPage(1)">下一页</button>
      </div>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loading">加载中…</p>
    <div v-else class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>歌曲编号</th>
            <th>歌名</th>
            <th>歌手</th>
            <th>分类</th>
            <th>季节</th>
            <th>更新时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.songCode">
            <td>{{ item.songCode }}</td>
            <td>{{ item.songName }}</td>
            <td>{{ item.artists || '-' }}</td>
            <td>
              {{
                [item.primaryCategory, item.secondaryCategory, item.tertiaryCategory]
                  .filter(Boolean)
                  .join(' / ') || '-'
              }}
            </td>
            <td>{{ item.seasons || '-' }}</td>
            <td>{{ new Date(item.updatedAt).toLocaleString() }}</td>
            <td class="actions">
              <button type="button" @click="showEdit(item)">编辑</button>
              <template v-if="confirmingCode === item.songCode">
                <button
                  class="danger"
                  type="button"
                  :disabled="busy"
                  @click="remove(item.songCode)"
                >
                  确认删除
                </button>
                <button type="button" @click="confirmingCode = ''">取消</button>
              </template>
              <button v-else class="danger" type="button" @click="confirmingCode = item.songCode">
                删除
              </button>
            </td>
          </tr>
          <tr v-if="!items.length">
            <td colspan="7" class="empty">暂无数据</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="pager">
      <span>共 {{ total }} 条</span
      ><button :disabled="page === 1" @click="turnPage(-1)">上一页</button
      ><label class="page-picker"
        >第
        <select :value="page" aria-label="底部选择页码" @change="selectPage">
          <option v-for="pageNumber in pageCount" :key="pageNumber" :value="pageNumber">
            {{ pageNumber }}
          </option>
        </select>
        / {{ pageCount }} 页</label
      >
      ><button :disabled="page * pageSize >= total" @click="turnPage(1)">下一页</button>
    </div>
    <BaseModal
      :open="open"
      :loading="busy"
      :title="editing ? '编辑歌曲情感' : '新增歌曲情感'"
      width="760px"
      @close="close"
    >
      <SongEmotionEditor
        v-model="form"
        :editing="editing"
        :busy="busy"
        :options="options"
        @submit="save"
        @cancel="close"
      />
    </BaseModal>
  </div>
</template>

<style scoped>
.toolbar,
.search,
.pager,
.actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.list-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 0 8px;
  border-bottom: 1px solid var(--border);
}
.list-meta > span {
  color: var(--text);
  font-weight: 700;
}
.toolbar {
  justify-content: space-between;
}
.search-input {
  position: relative;
}
.search-input input {
  width: 280px;
  padding-right: 38px;
}
.clear-search {
  position: absolute;
  top: 50%;
  right: 8px;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  color: var(--text-secondary);
  font-size: 20px;
  line-height: 22px;
  transform: translateY(-50%);
}
.clear-search:hover {
  background: var(--surface-muted);
  color: var(--text);
}
input {
  padding: 9px 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
}
button {
  padding: 7px 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
}
button.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: var(--surface);
}
.danger {
  color: var(--danger);
}
.table-scroll {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  padding: 10px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  white-space: nowrap;
}
.empty {
  text-align: center;
  color: var(--text-secondary);
}
.pager {
  justify-content: flex-end;
  color: var(--text-secondary);
}
.page-picker {
  display: flex;
  align-items: center;
  gap: 5px;
}
.page-picker select {
  min-width: 58px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
}
.error {
  color: var(--danger);
}
</style>
