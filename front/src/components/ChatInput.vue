<template>
  <div class="input-area">
    <div class="inner">
      <label class="chk-stream"><input type="checkbox" v-model="stream" checked> 流式</label>
      <textarea ref="ta" v-model="text" rows="1"
        placeholder="提出问题，Enter 发送，Shift+Enter 换行…"
        @keydown="onKey" @input="autoResize"></textarea>
      <button :disabled="store.sending" @click="send">发送</button>
    </div>
  </div>
</template>

<script setup>
import { ref, inject } from 'vue'
import { useAppStore } from '../stores/app.js'

const store = useAppStore()
const text = ref('')
const stream = ref(true)
const ta = ref(null)

// Inject the send function from ChatView
const sendMessage = inject('sendMessage')

function autoResize() {
  if (ta.value) {
    ta.value.style.height = 'auto'
    ta.value.style.height = Math.min(ta.value.scrollHeight, 160) + 'px'
  }
}

function onKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

async function send() {
  const q = text.value.trim()
  if (!q) return
  text.value = ''
  if (ta.value) ta.value.style.height = 'auto'
  await sendMessage(q)
}
</script>

<style scoped>
.input-area { padding: var(--space-md) var(--space-lg); border-top: 1px solid var(--rule); background: var(--paper); flex-shrink: 0; display: flex; justify-content: center; }
.inner { display: flex; gap: var(--space-sm); align-items: flex-end; width: 100%; max-width: 752px; }
textarea {
  flex: 1; background: var(--surface); border: 1.5px solid var(--rule);
  color: var(--ink); border-radius: 10px; padding: 11px 16px;
  font-size: var(--text-base); font-family: var(--sans);
  resize: none; outline: none; min-height: 44px; max-height: 160px;
  transition: border-color .2s; line-height: 1.5;
}
textarea:focus { border-color: var(--cobalt); box-shadow: 0 0 0 3px #3451C715; }
button {
  padding: 11px 22px; border-radius: 10px; border: none;
  background: var(--cobalt); color: #fff; cursor: pointer;
  font-size: var(--text-sm); font-weight: 600; white-space: nowrap;
  transition: background .15s, opacity .15s; font-family: var(--sans);
}
button:hover { background: var(--cobalt-h); }
button:disabled { opacity: .4; cursor: not-allowed; }
.chk-stream { display: flex; align-items: center; gap: 5px; font-size: var(--text-xs); color: var(--muted); cursor: pointer; user-select: none; white-space: nowrap; }
.chk-stream input { accent-color: var(--cobalt); }
</style>
