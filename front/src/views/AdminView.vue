<template>
  <div class="admin-view">
    <div class="admin-panel">
      <!-- Create user -->
      <div class="create-row">
        <input v-model="newName" placeholder="用户名" spellcheck="false" @keydown.enter="createUser">
        <select v-model="newRole"><option value="user">user</option><option value="admin">admin</option></select>
        <button class="btn-sm" @click="createUser">创建</button>
      </div>

      <!-- User list -->
      <div class="scroll-list">
        <div v-if="!users.length && !loading" class="empty-note">{{ store.connected ? '暂无用户' : '连接后加载用户' }}</div>
        <div v-if="loading" class="empty-note"><span class="spin"></span> 加载中…</div>
        <div v-for="u in users" :key="u.user_id" class="user-card">
          <div class="row1">
            <span class="uname">{{ u.name }}</span>
            <span class="scope-chip">{{ u.role }}</span>
            <span class="meta">{{ fmtDate(u.created_at) }}</span>
            <button class="mini-btn" @click="genKey(u)">+Key</button>
            <button class="mini-btn danger" @click="deleteUser(u)">删除</button>
          </div>
          <div class="row2">
            <div v-if="!keyMap[u.user_id]?.length" style="font-size:var(--text-xs);color:var(--faint);">无 API Key</div>
            <div v-for="k in keyMap[u.user_id] || []" :key="k.prefix" class="key-row">
              <span class="kpre" :style="{ color: k.revoked_at ? 'var(--faint)' : 'var(--ink)' }">{{ k.prefix }}</span>
              <span class="kts">{{ fmtDate(k.created_at) }}</span>
              <span v-if="k.revoked_at" style="color:var(--markup);font-size:0.6rem;">已撤销</span>
              <button v-else class="mini-btn danger" @click="revokeKey(k)">撤销</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Main area -->
    <div class="admin-empty">
      <p style="color:var(--faint);">用户与 API Key 管理</p>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { useAppStore } from '../stores/app.js'

const store = useAppStore()
const users = ref([])
const loading = ref(false)
const keyMap = reactive({})
const newName = ref('')
const newRole = ref('user')

// Reload when connected
watch(() => store.connected, (v) => { if (v) loadUsers() }, { immediate: true })

async function loadUsers() {
  if (!store.connected || !store.isAdmin) return
  loading.value = true
  try {
    users.value = await store.loadUsers()
    // Load keys
    for (const u of users.value) {
      try { keyMap[u.user_id] = await store.loadUserKeys(u.user_id) }
      catch (_) { keyMap[u.user_id] = [] }
    }
  } catch (e) { store.toast('加载用户失败: ' + e.message) }
  loading.value = false
}

async function createUser() {
  const name = newName.value.trim()
  if (!name) { store.toast('请输入用户名'); return }
  try {
    await store.createUser(name, newRole.value)
    newName.value = ''
    await loadUsers()
  } catch (e) { store.toast('创建失败: ' + e.message) }
}

async function deleteUser(u) {
  if (!confirm(`删除用户 ${u.name}？\n其所有 API Key 将被撤销。`)) return
  try { await store.deleteUser(u.user_id, u.name); await loadUsers() }
  catch (e) { store.toast('删除失败: ' + e.message) }
}

async function genKey(u) {
  try {
    await store.createKey(u.user_id)
    await loadUsers()
  } catch (e) { store.toast('生成 Key 失败: ' + e.message) }
}

async function revokeKey(k) {
  if (!confirm(`撤销 Key ${k.prefix}？`)) return
  try { await store.revokeKey(k.prefix); await loadUsers() }
  catch (e) { store.toast('撤销失败: ' + e.message) }
}

function fmtDate(s) {
  if (!s) return ''
  return new Date(s).toLocaleDateString()
}
</script>

<style scoped>
.admin-view { display: flex; flex: 1; overflow: hidden; }
.admin-panel { width: var(--sidebar-w); flex-shrink: 0; border-right: 1px solid var(--rule); background: var(--surface); display: flex; flex-direction: column; padding: var(--space-sm); overflow: hidden; }

.create-row { display: flex; gap: 6px; margin-bottom: var(--space-sm); align-items: center; flex-shrink: 0; }
.create-row input, .create-row select { border: 1px solid var(--rule); border-radius: 4px; padding: 5px 8px; font-size: var(--text-xs); font-family: var(--sans); background: var(--surface); color: var(--ink); outline: none; }
.create-row input:focus, .create-row select:focus { border-color: var(--cobalt); }
.create-row input { flex: 1; }
.create-row select { width: 72px; }
.btn-sm { padding: 5px 12px; border-radius: var(--radius); border: 1.5px dashed var(--rule); background: transparent; color: var(--cobalt); cursor: pointer; font-size: var(--text-xs); font-family: var(--sans); font-weight: 550; flex-shrink: 0; transition: all .15s; }
.btn-sm:hover { background: var(--stack); border-color: var(--cobalt); }

.scroll-list { flex: 1; overflow-y: auto; }

.user-card { background: var(--stack); border: 1px solid var(--rule); border-radius: var(--radius); padding: 10px 12px; margin-bottom: 6px; }
.row1 { display: flex; align-items: center; gap: 8px; font-size: var(--text-sm); }
.uname { font-weight: 600; flex: 1; }
.meta { font-size: var(--text-xs); color: var(--muted); white-space: nowrap; }
.row2 { margin-top: 6px; font-size: var(--text-xs); color: var(--muted); }
.key-row { display: flex; align-items: center; gap: 6px; padding: 4px 0; font-size: var(--text-xs); }
.kpre { font-family: var(--mono); font-size: 0.7rem; flex: 1; }
.kts { color: var(--faint); margin-right: 6px; }

.mini-btn { font-size: 0.65rem; padding: 2px 8px; border-radius: 3px; border: 1px solid var(--rule); background: var(--surface); cursor: pointer; color: var(--muted); font-family: var(--sans); transition: all .12s; }
.mini-btn:hover { border-color: var(--cobalt); color: var(--cobalt); }
.mini-btn.danger:hover { border-color: var(--markup); color: var(--markup); }

.scope-chip { font-size: 0.6rem; padding: 1px 6px; border-radius: 3px; flex-shrink: 0; font-weight: 550; letter-spacing: 0.3px; text-transform: uppercase; border: 1px solid var(--rule); color: var(--muted); }

.admin-empty { flex: 1; display: flex; align-items: center; justify-content: center; }
</style>
