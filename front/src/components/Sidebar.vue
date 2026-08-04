<template>
  <aside class="sidebar">
    <nav class="tab-bar">
      <button v-for="tab in tabs" :key="tab.id"
        :class="{ active: route.path === tab.route }"
        @click="navigate(tab)">{{ tab.label }}</button>
    </nav>
    <div class="panel">
      <slot />
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '../stores/app.js'

const router = useRouter()
const route = useRoute()
const store = useAppStore()

const tabs = computed(() => {
  const list = [
    { id: 'chat', label: '会话', route: '/' },
    { id: 'documents', label: '文档', route: '/documents' },
  ]
  if (store.isAdmin) {
    list.push({ id: 'admin', label: '管理', route: '/admin' })
  }
  list.push({ id: 'system', label: '系统', route: '/system' })
  return list
})

function navigate(tab) {
  router.push(tab.route)
}
</script>

<style scoped>
.sidebar {
  width: var(--sidebar-w); flex-shrink: 0;
  background: var(--surface); border-right: 1px solid var(--rule);
  display: flex; flex-direction: column; overflow: hidden;
}
.tab-bar { display: flex; border-bottom: 1px solid var(--rule); flex-shrink: 0; padding: 0 var(--space-sm); }
.tab-bar button {
  flex: 1; padding: 12px 0; background: none; border: none;
  color: var(--muted); cursor: pointer; font-size: var(--text-xs);
  font-family: var(--sans); font-weight: 520;
  border-bottom: 2px solid transparent; transition: all .15s;
}
.tab-bar button:hover { color: var(--ink); }
.tab-bar button.active { color: var(--cobalt); border-bottom-color: var(--cobalt); font-weight: 600; }
.panel { flex: 1; overflow-y: auto; padding: var(--space-sm); }
</style>
