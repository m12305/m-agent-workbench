<template>
  <div class="page-scroll knowledge-page">
    <PageHeader title="知识库" description="上传资料并跟踪索引状态，为 Agent 提供可检索的上下文。">
      <template #actions>
        <button class="button secondary" type="button" :disabled="store.documentsLoading" @click="refresh">
          <ArrowClockwise :size="18" :class="{ spinning: store.documentsLoading }" /> 刷新
        </button>
        <button class="button primary" type="button" @click="openPicker"><UploadSimple :size="18" weight="bold" /> 上传文档</button>
      </template>
    </PageHeader>

    <section class="knowledge-overview" aria-label="知识库概览">
      <div><span class="overview-icon"><Files :size="21" /></span><dl><dt>全部文档</dt><dd>{{ store.documents.length }}</dd></dl></div>
      <div><span class="overview-icon"><CheckCircle :size="21" /></span><dl><dt>可检索</dt><dd>{{ indexedCount }}</dd></dl></div>
      <div><span class="overview-icon"><Stack :size="21" /></span><dl><dt>内容分块</dt><dd>{{ totalChunks }}</dd></dl></div>
      <div><span class="overview-icon"><HardDrives :size="21" /></span><dl><dt>存储用量</dt><dd>{{ formatSize(totalSize) }}</dd></dl></div>
    </section>

    <section
      class="upload-dropzone"
      :class="{ dragover, disabled: uploading }"
      @dragenter.prevent="onDragEnter"
      @dragover.prevent
      @dragleave.prevent="onDragLeave"
      @drop.prevent="onDrop"
      @click="openPicker"
    >
      <input ref="fileInput" type="file" multiple hidden accept=".txt,.md,.pdf,text/plain,text/markdown,application/pdf" @change="onFilesSelected" />
      <div class="dropzone-icon"><CloudArrowUp :size="28" weight="duotone" /></div>
      <div><strong>{{ uploading ? '正在上传并创建索引任务' : '拖放文件到这里' }}</strong><span>支持 TXT、Markdown、PDF，单个文件不超过 20 MB</span></div>
      <label class="scope-control" @click.stop>
        <span>存储范围</span>
        <select v-model="uploadScope" :disabled="!store.isAdmin || uploading">
          <option value="private">仅自己可用</option>
          <option v-if="store.isAdmin" value="shared">团队共享</option>
        </select>
      </label>
    </section>

    <div v-if="uploadQueue.length" class="upload-queue" aria-live="polite">
      <div v-for="item in uploadQueue" :key="item.id" class="upload-queue-item">
        <FileText :size="19" aria-hidden="true" />
        <span><strong>{{ item.name }}</strong><small>{{ item.message }}</small></span>
        <StatusBadge :status="item.status" :label="item.status === 'done' ? '已提交' : item.status === 'failed' ? '失败' : '上传中'" />
      </div>
    </div>

    <section class="content-section document-section">
      <div class="section-toolbar">
        <div class="section-title"><h2>文档</h2><span>{{ filteredDocuments.length }} 项</span></div>
        <div class="document-filters">
          <label class="search-field wide"><MagnifyingGlass :size="17" /><input v-model="search" type="search" placeholder="搜索文件名" aria-label="搜索文档" /></label>
          <select v-model="scopeFilter" class="toolbar-select" aria-label="按范围筛选">
            <option value="all">全部范围</option><option value="private">私有</option><option value="shared">共享</option>
          </select>
          <select v-model="statusFilter" class="toolbar-select" aria-label="按状态筛选">
            <option value="all">全部状态</option><option value="indexed">可检索</option><option value="processing">处理中</option><option value="failed">失败</option>
          </select>
        </div>
      </div>

      <div v-if="store.documentsError" class="inline-alert is-error">
        <WarningCircle :size="19" weight="fill" /><span><strong>知识库服务暂不可用</strong>{{ store.documentsError }}</span>
        <button type="button" @click="refresh">重试</button>
      </div>

      <div v-if="store.documentsLoading && !store.documents.length" class="document-skeleton">
        <span v-for="index in 5" :key="index"></span>
      </div>
      <EmptyState v-else-if="!filteredDocuments.length" :icon="FileSearch" :title="store.documents.length ? '没有匹配的文档' : '知识库还是空的'" :description="store.documents.length ? '调整搜索词或筛选条件。' : '上传第一份资料，索引完成后即可在对话中检索。'">
        <button v-if="!store.documents.length" class="button secondary" type="button" @click="openPicker"><UploadSimple :size="18" /> 选择文件</button>
      </EmptyState>
      <div v-else class="document-table-wrap">
        <table class="document-table">
          <thead><tr><th>文档</th><th>范围</th><th>状态</th><th>分块</th><th>更新于</th><th><span class="sr-only">操作</span></th></tr></thead>
          <tbody>
            <tr v-for="document in filteredDocuments" :key="document.document_id" @click="showDocument(document)">
              <td><div class="file-cell"><span class="file-icon"><FilePdf v-if="document.filename.toLowerCase().endsWith('.pdf')" :size="21" /><MarkdownLogo v-else-if="document.filename.toLowerCase().endsWith('.md')" :size="21" /><FileText v-else :size="21" /></span><span><strong>{{ document.filename }}</strong><small>{{ formatSize(document.file_size) }} · {{ document.mime_type }}</small></span></div></td>
              <td><StatusBadge :status="document.scope" /></td>
              <td><StatusBadge :status="taskStatus(document)" :show-dot="isProcessing(document.status)" /></td>
              <td><span class="tabular">{{ document.chunk_count || '0' }}</span></td>
              <td><span class="date-cell">{{ formatDate(document.updated_at) }}</span></td>
              <td><button class="icon-button quiet" type="button" aria-label="打开文档详情" @click.stop="showDocument(document)"><DotsThree :size="20" weight="bold" /></button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <BaseModal :open="Boolean(selectedDocument)" title="文档详情" :description="selectedDocument?.filename" width="560px" @close="selectedDocument = null">
      <div v-if="detailLoading" class="detail-loading"><span></span><span></span><span></span></div>
      <div v-else-if="selectedDocument" class="document-detail">
        <div class="document-detail-status"><span class="file-icon large"><FileText :size="25" /></span><div><strong>{{ selectedDocument.filename }}</strong><span>{{ formatSize(selectedDocument.file_size) }}</span></div><StatusBadge :status="taskStatus(selectedDocument)" /></div>
        <dl class="detail-grid">
          <div><dt>文档 ID</dt><dd><code>{{ selectedDocument.document_id }}</code><button type="button" @click="copyId"><Copy :size="15" />复制</button></dd></div>
          <div><dt>知识范围</dt><dd>{{ selectedDocument.scope === 'shared' ? '团队共享' : '仅自己可用' }}</dd></div>
          <div><dt>内容分块</dt><dd>{{ selectedDocument.chunk_count }}</dd></div>
          <div><dt>文件类型</dt><dd>{{ selectedDocument.mime_type }}</dd></div>
          <div><dt>创建时间</dt><dd>{{ formatFullDate(selectedDocument.created_at) }}</dd></div>
          <div><dt>最后更新</dt><dd>{{ formatFullDate(selectedDocument.updated_at) }}</dd></div>
        </dl>
        <div v-if="selectedDocument.error_message" class="inline-alert is-error"><WarningCircle :size="19" /><span>{{ selectedDocument.error_message }}</span></div>
      </div>
      <template #footer>
        <button class="button danger ghost-danger" type="button" @click="requestDelete(selectedDocument!)"><Trash :size="18" /> 删除</button>
        <span class="footer-spacer"></span>
        <button class="button secondary" type="button" @click="download(selectedDocument!)"><DownloadSimple :size="18" /> 下载原文件</button>
      </template>
    </BaseModal>

    <ConfirmDialog :open="Boolean(documentToDelete)" title="删除这份文档？" description="原文件、索引和向量数据都会被清理，此操作无法撤销。" :detail="documentToDelete?.filename" :busy="deleting" @cancel="documentToDelete = null" @confirm="confirmDelete" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { PhArrowClockwise as ArrowClockwise, PhCheckCircle as CheckCircle, PhCloudArrowUp as CloudArrowUp, PhCopy as Copy, PhDotsThree as DotsThree, PhDownloadSimple as DownloadSimple, PhFilePdf as FilePdf, PhFileSearch as FileSearch, PhFiles as Files, PhFileText as FileText, PhHardDrives as HardDrives, PhMagnifyingGlass as MagnifyingGlass, PhMarkdownLogo as MarkdownLogo, PhStack as Stack, PhTrash as Trash, PhUploadSimple as UploadSimple, PhWarningCircle as WarningCircle } from '@phosphor-icons/vue'
import { api } from '../api/client'
import { useAppStore } from '../stores/app'
import type { DocumentRecord, DocumentScope } from '../types/api'
import PageHeader from '../components/layout/PageHeader.vue'
import BaseModal from '../components/feedback/BaseModal.vue'
import ConfirmDialog from '../components/feedback/ConfirmDialog.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import StatusBadge from '../components/ui/StatusBadge.vue'

interface UploadQueueItem { id: number; name: string; status: 'queued' | 'done' | 'failed'; message: string }

const store = useAppStore()
const fileInput = ref<HTMLInputElement | null>(null)
const uploadScope = ref<DocumentScope>('private')
const dragover = ref(false)
const dragDepth = ref(0)
const uploading = ref(false)
const uploadQueue = ref<UploadQueueItem[]>([])
const search = ref('')
const scopeFilter = ref('all')
const statusFilter = ref('all')
const selectedDocument = ref<DocumentRecord | null>(null)
const documentToDelete = ref<DocumentRecord | null>(null)
const detailLoading = ref(false)
const deleting = ref(false)

const indexedCount = computed(() => store.documents.filter((item) => item.status === 'indexed').length)
const totalChunks = computed(() => store.documents.reduce((total, item) => total + item.chunk_count, 0))
const totalSize = computed(() => store.documents.reduce((total, item) => total + item.file_size, 0))
const filteredDocuments = computed(() => store.documents.filter((document) => {
  const matchesSearch = document.filename.toLowerCase().includes(search.value.trim().toLowerCase())
  const matchesScope = scopeFilter.value === 'all' || document.scope === scopeFilter.value
  const matchesStatus = statusFilter.value === 'all'
    || (statusFilter.value === 'processing' && isProcessing(document.status))
    || document.status === statusFilter.value
  return matchesSearch && matchesScope && matchesStatus
}))

onMounted(() => { if (!store.documents.length) void store.loadDocuments() })

function openPicker() { if (!uploading.value) fileInput.value?.click() }
function onDragEnter() { dragDepth.value += 1; dragover.value = true }
function onDragLeave() { dragDepth.value = Math.max(0, dragDepth.value - 1); if (!dragDepth.value) dragover.value = false }
function onDrop(event: DragEvent) { dragover.value = false; dragDepth.value = 0; void uploadFiles(Array.from(event.dataTransfer?.files || [])) }
function onFilesSelected(event: Event) { void uploadFiles(Array.from((event.target as HTMLInputElement).files || [])); (event.target as HTMLInputElement).value = '' }

async function uploadFiles(files: File[]) {
  if (!files.length || uploading.value) return
  const supported = files.filter((file) => /\.(txt|md|pdf)$/i.test(file.name) && file.size <= 20 * 1024 * 1024)
  if (supported.length !== files.length) store.notify('部分文件未加入队列', '仅支持 TXT、Markdown、PDF，且单个文件不能超过 20 MB。', 'error')
  if (!supported.length) return
  uploading.value = true
  const queue: UploadQueueItem[] = supported.map((file, index) => ({ id: Date.now() + index, name: file.name, status: 'queued', message: '等待上传' }))
  uploadQueue.value.push(...queue)
  for (let index = 0; index < supported.length; index += 1) {
    const file = supported[index]
    const item = queue[index]
    if (!file || !item) continue
    item.message = '正在发送文件'
    try {
      await store.uploadDocument(file, uploadScope.value)
      item.status = 'done'
      item.message = '已创建索引任务'
    } catch (error) {
      item.status = 'failed'
      item.message = error instanceof Error ? error.message : '上传失败'
    }
  }
  uploading.value = false
  window.setTimeout(() => { uploadQueue.value = uploadQueue.value.filter((item) => item.status !== 'done') }, 5000)
}

async function refresh() { await store.loadDocuments().catch(() => undefined) }
function isProcessing(status: string) { return ['uploaded', 'queued', 'parsing', 'chunking', 'embedding'].includes(status) }
function taskStatus(document: DocumentRecord) { return store.tasks[document.document_id]?.status || document.status }

async function showDocument(document: DocumentRecord) {
  selectedDocument.value = document
  detailLoading.value = true
  try { selectedDocument.value = await api.getDocument(document.document_id) }
  catch (error) { store.notify('无法获取文档详情', error instanceof Error ? error.message : '', 'error') }
  finally { detailLoading.value = false }
}

async function download(document: DocumentRecord) {
  try { await api.downloadDocument(document.document_id, document.filename) }
  catch (error) { store.notify('下载失败', error instanceof Error ? error.message : '', 'error') }
}

function requestDelete(document: DocumentRecord) { documentToDelete.value = document; selectedDocument.value = null }
async function confirmDelete() {
  if (!documentToDelete.value) return
  deleting.value = true
  try { await store.deleteDocument(documentToDelete.value.document_id); documentToDelete.value = null }
  catch (error) { store.notify('删除失败', error instanceof Error ? error.message : '', 'error') }
  finally { deleting.value = false }
}

async function copyId() {
  if (!selectedDocument.value) return
  await navigator.clipboard.writeText(selectedDocument.value.document_id)
  store.notify('文档 ID 已复制', '', 'success')
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}
function formatDate(value: string) { return new Date(value).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }) }
function formatFullDate(value: string) { return new Date(value).toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }) }
</script>
