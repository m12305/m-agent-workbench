import { defineStore } from 'pinia'
import { api, getSavedApiBase, normalizeApiBase, STORAGE_KEYS } from '../api/client'
import type {
  DocumentRecord,
  DocumentScope,
  Identity,
  IndexTask,
  KnowledgeScope,
  ReadyHealth,
  Session,
} from '../types/api'

interface ToastItem {
  id: number
  title: string
  message?: string
  tone: 'success' | 'error' | 'info'
}

const activePolls = new Set<string>()
const delay = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms))

export const useAppStore = defineStore('app', {
  state: () => ({
    apiBase: getSavedApiBase(),
    apiKey: localStorage.getItem(STORAGE_KEYS.apiKey) || '',
    connected: false,
    connecting: false,
    connectionError: '',
    identity: null as Identity | null,
    health: null as ReadyHealth | null,
    healthCheckedAt: null as string | null,

    sessions: [] as Session[],
    activeSessionId: null as string | null,
    sessionsLoading: false,
    sessionsError: '',

    documents: [] as DocumentRecord[],
    documentsLoading: false,
    documentsError: '',
    tasks: {} as Record<string, IndexTask>,
    uploadProgress: 0,

    knowledgeScope: (localStorage.getItem(STORAGE_KEYS.scope) || 'hybrid') as KnowledgeScope,
    streamEnabled: localStorage.getItem(STORAGE_KEYS.stream) !== 'false',
    toasts: [] as ToastItem[],
  }),

  getters: {
    isAdmin: (state) => state.identity?.role === 'admin',
    activeSession: (state) => state.sessions.find((item) => item.session_id === state.activeSessionId) || null,
    userDisplayName: (state) => state.identity?.name || '未连接',
    apiKeyMasked: (state) => state.apiKey ? `${state.apiKey.slice(0, 8)}••••${state.apiKey.slice(-4)}` : '',
  },

  actions: {
    notify(title: string, message = '', tone: ToastItem['tone'] = 'info') {
      const id = Date.now() + Math.floor(Math.random() * 1000)
      this.toasts.push({ id, title, message, tone })
      window.setTimeout(() => this.dismissToast(id), 4200)
    },

    dismissToast(id: number) {
      this.toasts = this.toasts.filter((item) => item.id !== id)
    },

    savePreferences() {
      localStorage.setItem(STORAGE_KEYS.apiBase, normalizeApiBase(this.apiBase))
      localStorage.setItem(STORAGE_KEYS.apiKey, this.apiKey.trim())
      localStorage.setItem(STORAGE_KEYS.scope, this.knowledgeScope)
      localStorage.setItem(STORAGE_KEYS.stream, String(this.streamEnabled))
    },

    async connect(base?: string, key?: string) {
      this.connecting = true
      this.connectionError = ''
      this.apiBase = normalizeApiBase(base ?? this.apiBase)
      this.apiKey = (key ?? this.apiKey).trim()
      this.savePreferences()
      try {
        this.identity = await api.me()
        this.connected = true
        const results = await Promise.allSettled([
          this.refreshHealth(),
          this.loadSessions(false),
          this.loadDocuments(false),
        ])
        const unavailable = results.filter((result) => result.status === 'rejected').length
        this.notify('连接成功', unavailable ? '部分服务暂不可用，可在系统状态中查看。' : `你好，${this.identity.name}`, 'success')
      } catch (error) {
        this.connected = false
        this.identity = null
        this.connectionError = error instanceof Error ? error.message : '连接失败'
        throw error
      } finally {
        this.connecting = false
      }
    },

    async bootstrap() {
      if (!this.apiKey) return
      await this.connect(this.apiBase, this.apiKey)
    },

    markDisconnected(message = '') {
      this.connected = false
      this.identity = null
      this.connectionError = message
      if (message) this.notify('连接已断开', message, 'error')
    },

    disconnect() {
      localStorage.removeItem(STORAGE_KEYS.apiKey)
      this.apiKey = ''
      this.identity = null
      this.connected = false
      this.sessions = []
      this.documents = []
      this.activeSessionId = null
      activePolls.clear()
    },

    setKnowledgeScope(scope: KnowledgeScope) {
      this.knowledgeScope = scope
      localStorage.setItem(STORAGE_KEYS.scope, scope)
    },

    setStreamEnabled(enabled: boolean) {
      this.streamEnabled = enabled
      localStorage.setItem(STORAGE_KEYS.stream, String(enabled))
    },

    async refreshHealth() {
      this.health = await api.healthReady()
      this.healthCheckedAt = new Date().toISOString()
      return this.health
    },

    async loadSessions(showError = true) {
      this.sessionsLoading = true
      this.sessionsError = ''
      try {
        this.sessions = await api.listSessions()
        if (this.activeSessionId && !this.sessions.some((item) => item.session_id === this.activeSessionId)) {
          this.activeSessionId = null
        }
      } catch (error) {
        this.sessionsError = error instanceof Error ? error.message : '会话加载失败'
        if (showError) this.notify('无法加载会话', this.sessionsError, 'error')
        throw error
      } finally {
        this.sessionsLoading = false
      }
    },

    async createSession(title?: string | null) {
      const session = await api.createSession(title)
      this.sessions.unshift(session)
      this.activeSessionId = session.session_id
      return session
    },

    async deleteSession(sessionId: string) {
      await api.deleteSession(sessionId)
      this.sessions = this.sessions.filter((item) => item.session_id !== sessionId)
      if (this.activeSessionId === sessionId) this.activeSessionId = null
      this.notify('会话已删除', '', 'success')
    },

    async loadDocuments(showError = true) {
      this.documentsLoading = true
      this.documentsError = ''
      try {
        this.documents = await api.listDocuments()
      } catch (error) {
        this.documentsError = error instanceof Error ? error.message : '文档加载失败'
        if (showError) this.notify('无法加载知识库', this.documentsError, 'error')
        throw error
      } finally {
        this.documentsLoading = false
      }
    },

    async uploadDocument(file: File, scope: DocumentScope) {
      const result = await api.uploadDocument(file, scope)
      this.notify('文件已进入处理队列', result.filename, 'success')
      await this.loadDocuments(false).catch(() => undefined)
      void this.pollTask(result.task_id, result.document_id)
      return result
    },

    async pollTask(taskId: string, documentId: string) {
      if (activePolls.has(taskId)) return
      activePolls.add(taskId)
      try {
        for (let attempt = 0; attempt < 120 && activePolls.has(taskId); attempt += 1) {
          const task = await api.getTask(taskId)
          this.tasks[documentId] = task
          if (task.status === 'done') {
            await this.loadDocuments(false).catch(() => undefined)
            this.notify('索引已完成', '', 'success')
            return
          }
          if (task.status === 'failed') {
            await this.loadDocuments(false).catch(() => undefined)
            this.notify('索引失败', task.error_message || '请检查服务配置', 'error')
            return
          }
          if (attempt % 2 === 1) await this.loadDocuments(false).catch(() => undefined)
          await delay(attempt < 10 ? 1500 : 3000)
        }
      } catch (error) {
        this.notify('任务状态更新失败', error instanceof Error ? error.message : '', 'error')
      } finally {
        activePolls.delete(taskId)
      }
    },

    async deleteDocument(documentId: string) {
      await api.deleteDocument(documentId)
      this.documents = this.documents.filter((item) => item.document_id !== documentId)
      delete this.tasks[documentId]
      this.notify('文档已删除', '', 'success')
    },
  },
})
