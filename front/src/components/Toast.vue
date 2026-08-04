<template>
  <Teleport to="body">
    <div class="toast-container">
      <div v-for="t in store.toasts" :key="t.id" class="toast" :class="t.type">
        {{ t.msg }}
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { useAppStore } from '../stores/app.js'
const store = useAppStore()
</script>

<style scoped>
.toast-container {
  position: fixed; top: 50px; right: 20px; z-index: 999;
  display: flex; flex-direction: column; gap: 6px; pointer-events: none;
}
.toast {
  padding: 10px 16px; border-radius: 8px; font-size: var(--text-sm);
  animation: fadeIn .25s; max-width: 400px; pointer-events: auto;
  box-shadow: 0 4px 16px rgba(0,0,0,0.1); font-weight: 500;
}
.toast.err { background: #FDE8E8; color: #9B1C1C; border: 1px solid #F4C7C7; }
.toast.ok  { background: #E3F5ED; color: #1A7A4C; border: 1px solid #B7E4CF; }
.toast.info { background: #E8EDF8; color: var(--cobalt); border: 1px solid #CED8F5; }
@keyframes fadeIn { from { opacity:0; transform: translateX(24px); } to { opacity:1; } }
</style>
