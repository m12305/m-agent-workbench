<template>
  <div class="sys-view">
    <div class="sys-panel">
      <div v-if="!store.connected" class="empty-note">连接后检查系统状态</div>
      <template v-else>
        <!-- Service Status -->
        <div class="sys-card">
          <h4>服务状态</h4>
          <div class="sys-row" v-for="r in rows" :key="r[0]">
            <span class="label">{{ r[0] }}</span>
            <span class="value" :class="r[2]">{{ r[1] }}</span>
          </div>
        </div>

        <!-- Connection Info -->
        <div class="sys-card">
          <h4>连接信息</h4>
          <div class="sys-row"><span class="label">用户</span><span class="value">{{ store.userName }}</span></div>
          <div class="sys-row"><span class="label">用户 ID</span><span class="value">{{ store.userId }}</span></div>
          <div class="sys-row"><span class="label">角色</span><span class="value">{{ store.role }}</span></div>
          <div class="sys-row"><span class="label">端点</span><span class="value">{{ store.base }}</span></div>
          <div class="sys-row"><span class="label">会话数</span><span class="value">{{ store.sessions.length }}</span></div>
          <div class="sys-row"><span class="label">文档数</span><span class="value">{{ store.docs.length }}</span></div>
        </div>
      </template>
    </div>

    <div class="sys-empty">
      <p style="color:var(--faint);">系统状态监控</p>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useAppStore } from '../stores/app.js'

const store = useAppStore()

const rows = computed(() => {
  const h = store.health || {}
  return [
    ['Chat Agent', 'ok', 'good'],
    ['Embedding', h.embedding || 'unknown', h.embedding === 'ok' ? 'good' : 'warn'],
    ['Milvus', h.milvus || 'unknown', h.milvus === 'ok' ? 'good' : 'warn'],
    ['Retrieval', h.retrieval || 'unknown', h.retrieval === 'ok' ? 'good' : 'warn'],
  ]
})
</script>

<style scoped>
.sys-view { display: flex; flex: 1; overflow: hidden; }
.sys-panel { width: var(--sidebar-w); flex-shrink: 0; border-right: 1px solid var(--rule); background: var(--surface); padding: var(--space-sm); overflow-y: auto; }

.sys-card { background: var(--stack); border-radius: var(--radius); padding: 14px; margin-bottom: var(--space-sm); border: 1px solid var(--rule); }
.sys-card h4 { font-size: var(--text-xs); margin-bottom: 10px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.6px; }
.sys-row { display: flex; justify-content: space-between; align-items: center; font-size: var(--text-sm); padding: 5px 0; border-bottom: 1px solid rgba(0,0,0,0.04); }
.sys-row:last-child { border-bottom: none; }
.label { color: var(--muted); }
.value { font-family: var(--mono); font-size: var(--text-xs); font-weight: 500; }
.value.good { color: #1A7A4C; }
.value.warn { color: #92400E; }
.value.bad { color: #9B1C1C; }

.sys-empty { flex: 1; display: flex; align-items: center; justify-content: center; }
</style>
