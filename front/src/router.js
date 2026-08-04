import { createRouter, createWebHashHistory } from 'vue-router'
import ChatView from './views/ChatView.vue'

const routes = [
  { path: '/', name: 'chat', component: ChatView },
  { path: '/documents', name: 'documents', component: () => import('./views/DocumentsView.vue') },
  { path: '/admin', name: 'admin', component: () => import('./views/AdminView.vue') },
  { path: '/system', name: 'system', component: () => import('./views/SystemView.vue') },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
