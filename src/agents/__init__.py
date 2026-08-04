"""Agent 层 — ChatAgent 与可扩展的 Agent 基类

记忆架构:
  - 短期记忆: LangGraph Checkpointer (MemorySaver / PostgresSaver)
  - 长期记忆: LangGraph Store (InMemoryStore / PostgresStore)
  - 会话隔离: 通过 thread_id 实现
"""
from .base import BaseAgent
from .chat_agent import ChatAgent

__all__ = ["BaseAgent", "ChatAgent"]
