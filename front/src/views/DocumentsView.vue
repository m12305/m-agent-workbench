<template>
  <div class="docs-view">
    <div class="doc-panel">
      <!-- Upload scope -->
      <div class="scope-row">
        <span>范围</span>
        <select v-model="uploadScope" :disabled="!store.isAdmin">
          <option value="private">私有</option>
          <option value="shared">共享</option>
        </select>
      </div>

      <!-- Upload zone -->
      <div class="upload-zone"
        :class="{ dragover }"
        @dragover.prevent="dragover = true"
        @dragleave="dragover = false"
        @drop.prevent="onDrop"
        @click="$refs.fileInput.click()">
        拖拽文件到此处或点击上传
        <small>txt · md · pdf (&le;20MB)</small>
      </div>
      <input ref="fileInput" type="file" hidden accept=".txt,.md,.pdf" @change="onFileChange">

      <!-- Doc list -->
      <div class="scroll-list">
        <div v-if="!store.docs.length" class="empty-note">暂无文档</div>
        <div v-for="d in store.docs" :key="d.document_id"
          class="entry"
          @click="copyId(d.document_id)">
          <span class="title">{{ d.filename }}</span>
          <span class="scope-chip">{{ d.scope }}</span>
          <span class="badge" :class="d.status">{{ d.status }}</span>
          <span class="meta">{{ fmtSize(d.file_size) }}</span>
          <span class="dl" title="下载" @click.stop="download(d)">&darr;</span>
          <span class="del" title="删除" @click.stop="doDelete(d)">&times;</span>
        </div>
      </div>
    </div>

    <!-- Main area placeholder when on documents tab -->
    <div class="docs-empty">
      <p style="color:var(--faint);">选择或上传文档</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useAppStore } from '../stores/app.js'
import { api } from '../api.js'

const store = useAppStore()
const uploadScope = ref('private')
const dragover = ref(false)
const fileInput = ref(null)

function fmtSize(b) {
  if (!b) return '0B'
  return b < 1024 ? `${b}B` : b < 1024*1024 ? `${(b/1024).toFixed(1)}KB` : `${(b/(1024*1024)).toFixed(1)}MB`
}

async function upload(file) {
  if (!store.connected) { store.toast('请先连接'); return }
  if (!file) return
  try {
    await store.uploadDoc(file, uploadScope.value)
    if (fileInput.value) fileInput.value.value = ''
  } catch (e) { store.toast('上传失败: ' + e.message) }
}

function onDrop(e) {
  dragover.value = false
  if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0])
}
function onFileChange(e) {
  if (e.target.files[0]) upload(e.target.files[0])
}

async function download(d) {
  try {
    await api.downloadDoc(d.document_id, d.filename)
  } catch (e) { store.toast('下载失败: ' + e.message) }
}

async function doDelete(d) {
  if (!confirm('删除此文档？')) return
  try { await store.deleteDoc(d.document_id) } catch (e) { store.toast('删除失败: ' + e.message) }
}

function copyId(id) {
  navigator.clipboard?.writeText(id)
  store.toast('ID 已复制: ' + id, 'info')
}
</script>

<style scoped>
.docs-view { display: flex; flex: 1; overflow: hidden; }
.doc-panel { width: var(--sidebar-w); flex-shrink: 0; border-right: 1px solid var(--rule); background: var(--surface); display: flex; flex-direction: column; padding: var(--space-sm); overflow: hidden; }

.scope-row { display: flex; gap: 8px; margin-bottom: var(--space-sm); flex-shrink: 0; align-items: center; font-size: var(--text-xs); color: var(--muted); }
.scope-row select { background: var(--surface); border: 1px solid var(--rule); color: var(--ink); border-radius: 4px; padding: 4px 8px; font-size: var(--text-xs); font-family: var(--sans); cursor: pointer; }

.upload-zone { border: 2px dashed var(--rule); border-radius: var(--radius); padding: 20px 16px; text-align: center; color: var(--muted); cursor: pointer; margin-bottom: var(--space-sm); flex-shrink: 0; font-size: var(--text-sm); transition: all .2s; background: var(--stack); }
.upload-zone:hover, .upload-zone.dragover { border-color: var(--cobalt); color: var(--cobalt); background: #ECF0FA; }
.upload-zone small { display: block; margin-top: 5px; opacity: 0.7; font-size: var(--text-xs); }

.scroll-list { flex: 1; overflow-y: auto; }

.entry { padding: 10px 12px; border-radius: var(--radius); cursor: pointer; margin-bottom: 2px; display: flex; align-items: center; gap: 8px; font-size: var(--text-sm); transition: background .12s; border: 1px solid transparent; }
.entry:hover { background: var(--stack); }
.title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; font-weight: 470; }
.meta { font-size: var(--text-xs); color: var(--muted); white-space: nowrap; flex-shrink: 0; font-feature-settings: "tnum"; }
.dl, .del { flex-shrink: 0; opacity: 0; transition: opacity .12s; cursor: pointer; padding: 2px; line-height: 1; font-size: 0.9rem; font-weight: 500; }
.dl { color: var(--cobalt); }
.del { color: var(--markup); }
.entry:hover .dl, .entry:hover .del { opacity: 1; }

.scope-chip { font-size: 0.6rem; padding: 1px 6px; border-radius: 3px; flex-shrink: 0; font-weight: 550; letter-spacing: 0.3px; text-transform: uppercase; border: 1px solid var(--rule); color: var(--muted); }
.badge { font-size: 0.625rem; padding: 2px 8px; border-radius: 10px; font-weight: 600; white-space: nowrap; flex-shrink: 0; letter-spacing: 0.3px; text-transform: uppercase; }
.badge.queued, .badge.uploaded { background: #E8EDF8; color: var(--cobalt); }
.badge.parsing, .badge.chunking, .badge.embedding { background: #FEF3C7; color: #92400E; }
.badge.indexed, .badge.done { background: #E3F5ED; color: #1A7A4C; }
.badge.failed { background: #FDE8E8; color: #9B1C1C; }

.docs-empty { flex: 1; display: flex; align-items: center; justify-content: center; }
</style>
