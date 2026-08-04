<template>
  <div class="app-shell">
    <TopBar />
    <div class="body">
      <Sidebar />
      <main class="main">
        <router-view />
      </main>
    </div>
    <Toast />
  </div>
</template>

<script setup>
import TopBar from './components/TopBar.vue'
import Sidebar from './components/Sidebar.vue'
import Toast from './components/Toast.vue'
</script>

<style scoped>
.app-shell { height: 100%; display: flex; flex-direction: column; }
.body { display: flex; flex: 1; overflow: hidden; height: calc(100% - 42px); }
.main { flex: 1; overflow: hidden; background: var(--paper); display: flex; flex-direction: column; }
</style>
