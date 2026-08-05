import { createRouter, createWebHistory } from 'vue-router'
import { STORAGE_KEYS } from '../api/client'

import AppShell from '../components/layout/AppShell.vue'
import AdminView from '../views/AdminView.vue'
import AgentHubView from '../views/AgentHubView.vue'
import ChatView from '../views/ChatView.vue'
import ConnectView from '../views/ConnectView.vue'
import KnowledgeView from '../views/KnowledgeView.vue'
import SystemView from '../views/SystemView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/connect', name: 'connect', component: ConnectView },
    {
      path: '/',
      component: AppShell,
      meta: { requiresAuth: true },
      children: [
        { path: '', redirect: { name: 'agents' } },
        { path: 'apps', name: 'agents', component: AgentHubView },
        { path: 'apps/chat/:sessionId?', name: 'chat', component: ChatView, props: true },
        { path: 'knowledge', name: 'knowledge', component: KnowledgeView },
        { path: 'admin', name: 'admin', component: AdminView, meta: { adminOnly: true } },
        { path: 'system', name: 'system', component: SystemView },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  const key = localStorage.getItem(STORAGE_KEYS.apiKey)
  if (to.meta.requiresAuth && !key) return { name: 'connect', query: { redirect: to.fullPath } }
  if (to.name === 'connect' && key) return true
  return true
})

export default router
