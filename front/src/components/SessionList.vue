<template>
  <div class="session-panel">
    <button class="shelf-action" @click="store.createSession()">+ 新建会话</button>
    <div class="scroll-list">
      <div v-if="!store.sessions.length" class="empty-note">暂无会话</div>
      <div v-for="s in store.sessions" :key="s.session_id"
        class="entry" :class="{ active: s.session_id === store.activeSid }"
        @click="store.activeSid = s.session_id">
        <span class="title">{{ s.title || '未命名' }}</span>
        <span class="meta">{{ s.message_count || 0 }}</span>
        <span class="del" title="删除" @click.stop="doDelete(s)">&times;</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useAppStore } from '../stores/app.js'
const store = useAppStore()

async function doDelete(s) {
  if (!confirm('删除此会话？')) return
  try { await store.deleteSession(s.session_id) } catch (e) { store.toast('删除失败: ' + e.message) }
}
</script>

<style scoped>
.session-panel { display: flex; flex-direction: column; height: 100%; }
.shelf-action {
  width: 100%; padding: 9px 12px; border-radius: var(--radius);
  border: 1.5px dashed var(--rule); background: transparent;
  color: var(--cobalt); cursor: pointer; font-size: var(--text-xs);
  font-family: var(--sans); font-weight: 550; margin-bottom: var(--space-sm);
  flex-shrink: 0; transition: all .15s;
}
.shelf-action:hover { background: var(--stack); border-color: var(--cobalt); }
.scroll-list { flex: 1; overflow-y: auto; }

.entry {
  padding: 10px 12px; border-radius: var(--radius); cursor: pointer;
  margin-bottom: 2px; display: flex; align-items: center; gap: 8px;
  font-size: var(--text-sm); transition: background .12s; border: 1px solid transparent;
}
.entry:hover { background: var(--stack); }
.entry.active { background: #ECF0FA; border-color: #CED8F5; }
.title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; font-weight: 470; }
.meta { font-size: var(--text-xs); color: var(--muted); white-space: nowrap; flex-shrink: 0; font-feature-settings: "tnum"; }
.del { flex-shrink: 0; opacity: 0; transition: opacity .12s; cursor: pointer; padding: 2px; line-height: 1; font-size: 0.9rem; font-weight: 500; color: var(--markup); }
.entry:hover .del { opacity: 1; }
</style>
