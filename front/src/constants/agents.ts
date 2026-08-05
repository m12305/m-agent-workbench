import { PhChatCircleDots as ChatCircleDots } from '@phosphor-icons/vue'
import type { Component } from 'vue'

export interface AgentDefinition {
  id: string
  name: string
  shortName: string
  description: string
  routeName: string
  icon: Component
  capabilities: string[]
}

export const agents: AgentDefinition[] = [
  {
    id: 'chat',
    name: 'Chat Agent',
    shortName: '对话',
    description: '结合私有与共享知识库，完成检索增强问答。',
    routeName: 'chat',
    icon: ChatCircleDots,
    capabilities: ['多轮会话', '流式回答', 'RAG 检索'],
  },
]
