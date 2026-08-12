"""
===========================================================================
MultiAgentService — MainAgent 的 FastAPI 服务包装
===========================================================================

与 ChatService 相同的模式:
  - 按 user_id 缓存 MainAgent 实例
  - 异步流式输出 → SSE events
  - thread_id = "{user_id}:{session_id}"

使用:
    from ..agents.multi_agent import SubAgentRegistry
    registry = SubAgentRegistry()
    # ... 注册 subagent 类型 ...
    service = MultiAgentService(sub_agent_registry=registry)
===========================================================================
"""

import asyncio
import hashlib
import logging
import threading
from pathlib import Path
from typing import AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage

from ...agents.multi_agent.main_agent import MainAgent
from ...agents.multi_agent.sub_agent_registry import SubAgentRegistry
from ...agents.multi_agent.events import AgentRunCancelled

logger = logging.getLogger("server.multi_agent_service")


class MultiAgentService:
    """MainAgent 服务包装

    管理 MainAgent 实例的缓存和生命周期。
    """

    def __init__(
        self,
        sub_agent_registry: SubAgentRegistry | None = None,
        store_type: str = "memory",
        sqlite_path: str | None = None,
    ):
        self._agents: dict[str, MainAgent] = {}
        self._registry = sub_agent_registry or SubAgentRegistry()
        self._store_type = store_type
        self._sqlite_path = sqlite_path
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._active_runs: dict[str, threading.Event] = {}

    # ── Agent 管理 ──

    def _get_or_create_agent(self, user_id: str) -> MainAgent:
        """按需获取或创建用户的 MainAgent 实例"""
        if user_id not in self._agents:
            agent = MainAgent(
                name=f"orchestrator-{user_id[:8]}",
                sub_agent_registry=self._registry,
                store_type=self._store_type,
                sqlite_path=self._sqlite_path_for_user(user_id),
            )
            agent.initialize()
            self._agents[user_id] = agent
            logger.info("新 MainAgent 实例: user=%s", user_id[:8])
        return self._agents[user_id]

    def close_user(self, user_id: str):
        """释放用户的 MainAgent 实例"""
        prefix = f"{user_id}:"
        for thread_id in [key for key in self._active_runs if key.startswith(prefix)]:
            self.cancel_run(thread_id)
        agent = self._agents.pop(user_id, None)
        if agent:
            agent.close()
        for thread_id in [key for key in self._session_locks if key.startswith(prefix)]:
            self._session_locks.pop(thread_id, None)

    # ── 同步执行 ──

    def chat(
        self,
        user_id: str,
        session_id: str,
        query: str,
    ) -> str:
        """同步问答 — 返回完整回答文本"""
        agent = self._get_or_create_agent(user_id)
        tid = self._make_tid(user_id, session_id)
        return agent.run(query, thread_id=tid)

    # ── 流式执行 ──

    async def chat_stream(
        self,
        user_id: str,
        session_id: str,
        query: str,
    ) -> AsyncGenerator[dict, None]:
        """异步流式问答 — 逐事件 yield SSE dict

        Yields:
            dict: {event: str, data: dict}
        """
        agent = self._get_or_create_agent(user_id)
        tid = self._make_tid(user_id, session_id)

        # 同一会话只允许一个图执行，避免重复提交造成 checkpoint 写竞争。
        session_lock = self._session_locks.setdefault(tid, asyncio.Lock())
        async with session_lock:
            cancellation_event = threading.Event()
            self._active_runs[tid] = cancellation_event
            try:
                async for event in agent.arun_stream(
                    query,
                    thread_id=tid,
                    cancellation_event=cancellation_event,
                ):
                    yield event
            except (asyncio.CancelledError, GeneratorExit):
                cancellation_event.set()
                raise
            except AgentRunCancelled:
                logger.info("Multi-agent run cancelled for user=%s", user_id[:8])
            except Exception as e:
                logger.exception("Multi-agent stream error for user=%s", user_id[:8])
                yield {
                    "event": "error",
                    "data": {
                        "code": "AGENT_ERROR",
                        "message": str(e),
                        "agent": "main",
                    },
                }
            finally:
                cancellation_event.set()
                if self._active_runs.get(tid) is cancellation_event:
                    self._active_runs.pop(tid, None)

    def cancel_run(self, thread_id: str) -> bool:
        """Cooperatively stop the active graph run for a thread."""
        cancellation_event = self._active_runs.get(thread_id)
        if cancellation_event is None:
            return False
        cancellation_event.set()
        return True

    def get_session_messages(self, user_id: str, session_id: str) -> list:
        """Return the task/final-answer pair without orchestration internals."""
        agent = self._get_or_create_agent(user_id)
        if agent._graph is None:
            return []

        tid = self._make_tid(user_id, session_id)
        state = agent._graph.get_state({"configurable": {"thread_id": tid}})
        if not state or not state.values:
            return []

        user_task = state.values.get("user_task", "")
        final_answer = state.values.get("synthesized_answer", "")
        visible = []
        if user_task:
            visible.append(HumanMessage(content=str(user_task)))
        if final_answer:
            visible.append(AIMessage(content=str(final_answer)))
        return visible

    # ── 注册 subagent ──

    @property
    def registry(self) -> SubAgentRegistry:
        return self._registry

    # ── 辅助 ──

    @staticmethod
    def _make_tid(user_id: str, session_id: str) -> str:
        """构造 LangGraph thread_id"""
        return f"{user_id}:{session_id}"

    def _sqlite_path_for_user(self, user_id: str) -> str | None:
        """从配置的基础文件名派生稳定的用户独立 SQLite 文件。"""
        if self._store_type != "sqlite":
            return self._sqlite_path

        configured_path = self._sqlite_path or "./data/multi_agent.db"
        if configured_path == ":memory:":
            return configured_path

        base_path = Path(configured_path)
        suffix = base_path.suffix or ".db"
        user_key = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]
        return str(base_path.with_name(f"{base_path.stem}-{user_key}{suffix}"))

    def close_all(self):
        """关闭所有用户实例"""
        for user_id in list(self._agents.keys()):
            self.close_user(user_id)
        self._session_locks.clear()
        for cancellation_event in self._active_runs.values():
            cancellation_event.set()
        self._active_runs.clear()
