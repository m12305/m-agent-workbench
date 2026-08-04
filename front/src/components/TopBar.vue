<template>
  <header class="masthead">
    <span class="wordmark">m<span class="dot">·</span>Knowledge</span>
    <input v-model="store.base" class="fld" id="api-base" placeholder="http://localhost:8000/api/v1" spellcheck="false" @keydown.enter="connect">
    <input v-model="store.key" class="fld" id="api-key" type="password" placeholder="API Key" spellcheck="false" @keydown.enter="connect">
    <button class="btn-connect" :disabled="store.connecting" @click="connect">
      {{ store.connecting ? '连接中…' : '连接' }}
    </button>
    <span class="dot-status" :class="dotClass" :title="dotTitle"></span>
    <span class="health-pills">
      <span v-for="p in pills" :key="p[0]" class="pill" :class="p[1] ? 'up' : 'down'">{{ p[0] }}</span>
    </span>
    <span class="user-tag" v-if="store.connected">
      {{ store.userName }} <span class="role-chip" :class="store.role">{{ store.role }}</span>
    </span>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useAppStore } from '../stores/app.js'

const store = useAppStore()

const dotClass = computed(() => {
  if (store.connecting) return 'chk'
  if (store.connected) return 'ok'
  return 'off'
})
const dotTitle = computed(() => ({
  off: '未连接', chk: '检测中…', ok: '已连接', err: '连接失败',
})[dotClass.value])

const pills = computed(() => {
  const h = store.health || {}
  return [
    ['EMB', h.embedding === 'ok'],
    ['MIL', h.milvus === 'ok'],
    ['RET', h.retrieval === 'ok'],
  ]
})

async function connect() {
  if (store.connecting) return
  try { await store.connect() } catch (_) { /* toast already shown */ }
}
</script>

<style scoped>
.masthead {
  display: flex; align-items: center; gap: var(--space-sm);
  padding: 8px 20px; background: var(--surface);
  border-bottom: 1px solid var(--rule); flex-shrink: 0;
  font-size: var(--text-xs); color: var(--muted); z-index: 10;
}
.wordmark { font-weight: 640; font-size: var(--text-sm); color: var(--ink); letter-spacing: -0.2px; margin-right: var(--space-sm); }
.dot { color: var(--cobalt); }
.fld {
  border: 1px solid var(--rule); border-radius: 5px;
  padding: 5px 10px; font-size: var(--text-xs); font-family: var(--sans);
  color: var(--ink); background: var(--stack); outline: none;
  transition: border-color .15s, background .15s;
}
.fld:focus { border-color: var(--cobalt); background: var(--surface); }
#api-base { width: 200px; }
#api-key { width: 280px; font-family: var(--mono); font-size: 0.65rem; }
.btn-connect {
  padding: 5px 14px; border-radius: 5px; border: 1.5px solid var(--cobalt);
  background: transparent; color: var(--cobalt); cursor: pointer;
  font-size: var(--text-xs); font-weight: 600; white-space: nowrap;
  transition: all .18s; font-family: var(--sans);
}
.btn-connect:hover { background: var(--cobalt); color: #fff; }
.btn-connect:disabled { opacity: .5; cursor: not-allowed; }

.dot-status { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.dot-status.off { background: #C8CCD4; }
.dot-status.chk { background: var(--amber); animation: throb 1.2s infinite; }
.dot-status.ok { background: #22A66B; box-shadow: 0 0 6px #22A66B55; }
.dot-status.err { background: var(--markup); }
@keyframes throb { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }

.health-pills { display: flex; gap: 5px; margin-left: 4px; }
.pill { font-size: 0.625rem; padding: 2px 7px; border-radius: 3px; font-weight: 650; letter-spacing: 0.4px; text-transform: uppercase; }
.pill.up { background: #E3F5ED; color: #1A7A4C; }
.pill.down { background: #FEF3C7; color: #92400E; }

.user-tag { margin-left: auto; font-size: var(--text-xs); color: var(--muted); display: flex; align-items: center; gap: 8px; }
.role-chip {
  font-size: 0.625rem; padding: 2px 8px; border-radius: 10px;
  font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;
  background: var(--stack); border: 1px solid var(--rule); color: var(--muted);
}
.role-chip.admin { background: #EBF0FF; border-color: #C8D5F5; color: var(--cobalt); }
</style>
