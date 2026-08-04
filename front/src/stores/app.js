import { defineStore } from 'pinia'
import { api } from '../api.js'

export const useAppStore = defineStore('app', {
  state: () => ({
    // Connection
    base: localStorage.getItem('mka_base') || '/api/v1',
    key: localStorage.getItem('mka_key') || '',
    connected: false,
    connecting: false,

    // User
    userId: '',
    userName: '',
    role: '',

    // Health
    health: null,

    // Sessions
    sessions: [],
    activeSid: null,

    // Docs
    docs: [],

    // Toasts
    toasts: [],

    // Input
    scope: 'hybrid',
    sending: false,
  }),

  getters: {
    isAdmin: (s) => s.role === 'admin',
  },

  actions: {
    saveConfig() {
      localStorage.setItem('mka_base', this.base)
      localStorage.setItem('mka_key', this.key)
    },

    toast(msg, type = 'err') {
      const id = Date.now() + Math.random()
      this.toasts.push({ id, msg, type })
      setTimeout(() => {
        this.toasts = this.toasts.filter(t => t.id !== id)
      }, 3600)
    },

    async connect() {
      this.saveConfig()
      this.connecting = true
      try {
        const [me, ready] = await Promise.all([
          api.me(),
          api.health(),
        ])
        this.connected = true
        this.userId = me.user_id
        this.userName = me.name
        this.role = me.role
        this.health = ready?.checks || null
        this.toast('已连接 · ' + me.name, 'ok')
        // Load initial data
        await Promise.all([
          this.loadSessions(),
          this.loadDocs(),
        ])
      } catch (e) {
        this.connected = false
        this.health = null
        this.toast('连接失败: ' + e.message)
        throw e
      } finally {
        this.connecting = false
      }
    },

    // ── Sessions ──
    async loadSessions() {
      try {
        this.sessions = await api.listSessions()
      } catch (e) {
        this.toast('加载会话失败: ' + e.message)
      }
    },

    async createSession() {
      const s = await api.createSession(null)
      this.sessions.unshift(s)
      this.activeSid = s.session_id
      this.toast('会话已创建', 'ok')
      return s
    },

    async deleteSession(sid) {
      await api.deleteSession(sid)
      this.sessions = this.sessions.filter(s => s.session_id !== sid)
      if (this.activeSid === sid) this.activeSid = null
      this.toast('会话已删除', 'ok')
    },

    // ── Docs ──
    async loadDocs() {
      try {
        this.docs = await api.listDocs()
      } catch (e) {
        this.toast('加载文档失败: ' + e.message)
      }
    },

    async uploadDoc(file, scope) {
      const data = await api.uploadDoc(file, scope)
      this.toast(`已上传: ${data.filename} [${data.scope}]`, 'ok')
      await this.loadDocs()
      // Poll task
      await this.pollTask(data.task_id)
      return data
    },

    async deleteDoc(id) {
      await api.deleteDoc(id)
      this.docs = this.docs.filter(d => d.document_id !== id)
      this.toast('文档已删除', 'ok')
    },

    async pollTask(taskId) {
      let attempts = 0
      const check = async () => {
        if (attempts > 120) return
        attempts++
        try {
          const t = await api.getTask(taskId)
          if (t.status === 'indexed') {
            this.toast('索引完成', 'ok')
            await this.loadDocs()
            return
          }
          if (t.status === 'failed') {
            this.toast(`处理失败: ${t.error_message || '未知错误'}`)
            await this.loadDocs()
            return
          }
          setTimeout(check, 2000)
        } catch (_) { setTimeout(check, 3000) }
      }
      setTimeout(check, 1500)
    },

    // ── Admin ──
    async loadUsers() {
      return api.listUsers()
    },

    async createUser(name, role) {
      await api.createUser(name, role)
      this.toast(`用户已创建: ${name} [${role}]`, 'ok')
    },

    async deleteUser(id, name) {
      await api.deleteUser(id)
      this.toast(`用户已删除: ${name}`, 'ok')
    },

    async loadUserKeys(uid) {
      return api.listUserKeys(uid)
    },

    async createKey(uid) {
      const k = await api.createKey(uid)
      this.toast(`Key 已生成 — 仅此一次: ${k.key}`, 'ok')
      navigator.clipboard?.writeText(k.key)
      return k
    },

    async revokeKey(prefix) {
      await api.revokeKey(prefix)
      this.toast('Key 已撤销', 'ok')
    },
  },
})
