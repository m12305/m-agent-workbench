<template>
  <div class="msg-wrap">
    <div class="msg" :class="msg.role">
      <div class="byline">{{ msg.role === 'user' ? 'You' : 'Assistant' }}</div>
      <div v-if="msg.role === 'assistant'" v-html="rendered"></div>
      <p v-else>{{ msg.content }}</p>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps({ msg: Object })

const rendered = computed(() => {
  if (!props.msg.content) return ''
  return marked.parse(props.msg.content) || ''
})
</script>

<style scoped>
.msg-wrap { width: 100%; max-width: 720px; padding: 0 var(--space-md); }
.msg { max-width: 65ch; padding: var(--space-md) var(--space-lg); border-radius: 10px; font-size: var(--text-base); line-height: 1.72; animation: fadeUp .3s ease-out; position: relative; }
.msg.user { margin-left: auto; margin-right: 0; background: var(--surface); border: 1px solid var(--rule); color: var(--ink); border-bottom-right-radius: 3px; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
.msg.assistant { margin-left: 0; margin-right: auto; background: transparent; color: var(--ink); border-bottom-left-radius: 3px; }
.byline { font-size: 0.625rem; color: var(--faint); margin-bottom: var(--space-sm); font-weight: 600; letter-spacing: 0.8px; text-transform: uppercase; }
.msg.user .byline { color: var(--muted); }

/* Markdown styles */
.msg.assistant :deep(h1) { font-size: var(--text-xl); font-weight: 620; letter-spacing: -0.5px; margin: var(--space-lg) 0 var(--space-sm); line-height: 1.25; }
.msg.assistant :deep(h2) { font-size: var(--text-lg); font-weight: 620; letter-spacing: -0.3px; margin: var(--space-lg) 0 var(--space-sm); padding-bottom: var(--space-xs); border-bottom: 1.5px solid var(--rule); }
.msg.assistant :deep(h3) { font-size: var(--text-md); font-weight: 600; margin: var(--space-md) 0 var(--space-xs); }
.msg.assistant :deep(p) { margin: 0 0 var(--space-sm); }
.msg.assistant :deep(p:last-child) { margin-bottom: 0; }
.msg.assistant :deep(ul), .msg.assistant :deep(ol) { padding-left: 1.5em; margin: var(--space-sm) 0; }
.msg.assistant :deep(li) { margin: 3px 0; }
.msg.assistant :deep(li::marker) { color: var(--cobalt); }
.msg.assistant :deep(blockquote) { border-left: 3px solid var(--cobalt); padding: var(--space-xs) var(--space-md); margin: var(--space-md) 0; color: var(--muted); background: #F7F8FB; border-radius: 0 4px 4px 0; font-style: italic; font-size: 0.95em; }
.msg.assistant :deep(pre) { background: #F2F3F7; padding: var(--space-md); border-radius: 8px; overflow-x: auto; margin: var(--space-md) 0; font-family: var(--mono); font-size: 0.8rem; line-height: 1.6; border: 1px solid var(--rule); color: #383D4A; }
.msg.assistant :deep(code) { font-family: var(--mono); font-size: 0.82em; background: #EEF0F5; padding: 2px 6px; border-radius: 3px; color: #4A3F6B; }
.msg.assistant :deep(pre code) { background: none; padding: 0; color: inherit; font-size: inherit; }
.msg.assistant :deep(table) { border-collapse: collapse; margin: var(--space-md) 0; width: 100%; font-size: var(--text-sm); }
.msg.assistant :deep(th) { background: var(--stack); border: 1px solid var(--rule); padding: 8px 12px; text-align: left; font-weight: 600; font-size: var(--text-xs); color: var(--muted); text-transform: uppercase; letter-spacing: 0.4px; }
.msg.assistant :deep(td) { border: 1px solid var(--rule); padding: 8px 12px; background: var(--surface); }
.msg.assistant :deep(a) { color: var(--teal); text-decoration: none; }
.msg.assistant :deep(strong) { font-weight: 620; }
</style>
