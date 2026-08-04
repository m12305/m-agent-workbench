<template>
  <div class="chat-view">
    <!-- Sidebar content: sessions -->
    <SessionList />
    <!-- Main: messages + input -->
    <div class="chat-main">
      <!-- Context bar -->
      <div class="ctx-bar">
        <select v-model="store.scope">
          <option value="hybrid">全部知识</option>
          <option value="private">仅私有</option>
          <option value="shared">仅共享</option>
        </select>
      </div>

      <!-- Messages -->
      <div ref="msgList" class="msg-list">
        <div v-if="!store.connected" class="empty-state">
          <div class="wordmark-lg">m<span>·</span>K</div>
          <p>企业知识助手 — 连接你的文档，用自然语言提问</p>
          <p class="colophon">配置 API 端点与密钥后点击「连接」开始</p>
        </div>
        <div v-else-if="!store.activeSid && !messages.length" class="empty-state">
          <p style="color:var(--muted)">新建或选择一个会话开始对话</p>
        </div>
        <template v-for="m in messages" :key="m.created_at + m.role">
          <ChatMessage :msg="m" />
        </template>
        <!-- Streaming placeholder -->
        <div v-if="streaming" class="msg-wrap">
          <div class="msg assistant">
            <div class="byline">Assistant</div>
            <div v-html="renderedStream"></div>
            <span class="spin" v-if="!streamText"></span>
          </div>
        </div>
      </div>

      <!-- Input -->
      <ChatInput />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, provide } from 'vue'
import { useAppStore } from '../stores/app.js'
import { api } from '../api.js'
import { marked } from 'marked'
import SessionList from '../components/SessionList.vue'
import ChatMessage from '../components/ChatMessage.vue'
import ChatInput from '../components/ChatInput.vue'

marked.setOptions({ breaks: true })
const store = useAppStore()
const msgList = ref(null)

// Local message state for active session
const messages = ref([])
const streaming = ref(false)
const streamText = ref('')
const renderedStream = computed(() => marked.parse(streamText.value || '') || '')

// Load messages when active session changes
watch(() => store.activeSid, async (sid) => {
  if (!sid) { messages.value = []; return }
  try {
    messages.value = await api.getMessages(sid)
    await nextTick(() => scrollBottom())
  } catch (e) {
    store.toast('加载消息失败: ' + e.message)
  }
})

function scrollBottom() {
  if (msgList.value) msgList.value.scrollTop = msgList.value.scrollHeight
}

// Expose for ChatInput to call
async function sendMessage(query) {
  if (!query.trim() || store.sending) return
  if (!store.activeSid) await store.createSession()
  if (!store.activeSid) return

  store.sending = true
  const scope = store.scope

  // Add user message locally
  messages.value.push({ role: 'user', content: query, created_at: new Date().toISOString() })
  await nextTick(() => scrollBottom())

  try {
    streaming.value = true
    streamText.value = ''
    let full = ''

    for await (const chunk of api.chatStream(query, store.activeSid, scope)) {
      if (chunk.text) {
        full += chunk.text
        streamText.value = full
        await nextTick(() => scrollBottom())
      }
    }

    // Finalize
    messages.value.push({ role: 'assistant', content: full, created_at: new Date().toISOString() })
    streamText.value = ''
    streaming.value = false
    await nextTick(() => scrollBottom())
    store.loadSessions()
  } catch (e) {
    streaming.value = false
    streamText.value = ''
    store.toast('发送失败: ' + e.message)
  } finally {
    store.sending = false
  }
}

defineExpose({ sendMessage })
provide('sendMessage', sendMessage)
</script>

<style scoped>
.chat-view { display: flex; flex: 1; overflow: hidden; }
.chat-main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

.ctx-bar {
  padding: 10px 24px; border-bottom: 1px solid var(--rule);
  background: var(--paper); display: flex; gap: var(--space-sm);
  align-items: center; flex-shrink: 0;
}
.ctx-bar select {
  background: var(--surface); border: 1px solid var(--rule); color: var(--ink);
  border-radius: 5px; padding: 5px 10px; font-size: var(--text-xs);
  font-family: var(--sans); cursor: pointer;
}

.msg-list {
  flex: 1; overflow-y: auto; padding: var(--space-xl) 0;
  display: flex; flex-direction: column; align-items: center;
  gap: var(--space-lg);
}

/* Empty state */
.empty-state { color: var(--muted); text-align: center; margin-top: 120px; max-width: 420px; }
.wordmark-lg { font-size: 4rem; font-weight: 640; color: var(--ink); letter-spacing: -1.5px; margin-bottom: var(--space-lg); line-height: 1; }
.wordmark-lg span { color: var(--cobalt); }
.colophon { font-family: var(--mono); font-size: 0.7rem; color: var(--faint); margin-top: var(--space-lg); letter-spacing: 0.3px; }

/* Messages */
.msg-wrap { width: 100%; max-width: 720px; padding: 0 var(--space-md); }
.msg { max-width: 65ch; padding: var(--space-md) var(--space-lg); border-radius: 10px; font-size: var(--text-base); line-height: 1.72; animation: fadeUp .3s ease-out; position: relative; }
.msg.assistant { margin-left: 0; margin-right: auto; background: transparent; color: var(--ink); border-bottom-left-radius: 3px; }
.byline { font-size: 0.625rem; color: var(--faint); margin-bottom: var(--space-sm); font-weight: 600; letter-spacing: 0.8px; text-transform: uppercase; }
</style>
