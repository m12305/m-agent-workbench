"""问答服务 — ChatAgent 异步包装 + 知识库检索 + Query 改写 + 多用户管理"""

import logging
from ...agents import ChatAgent

logger = logging.getLogger("server.chat_service")


class ChatService:
    """ChatAgent 的异步包装。

    - 按 user_id 缓存 ChatAgent 实例
    - thread_id = "{user_id}:{session_id}" 实现 Checkpointer 层会话隔离
    - 注入知识库检索结果到上下文 (如果配置了 retrieval)
    - 传递会话历史到检索服务 (用于 context-aware query 改写)
    """

    def __init__(self, retrieval_service=None):
        self._agents: dict[str, ChatAgent] = {}
        self._retrieval = retrieval_service  # RetrievalService | AdvancedRetrievalService | None

    @staticmethod
    def _make_tid(user_id: str, session_id: str) -> str:
        """构造 LangGraph thread_id: user_id + session_id 共同索引"""
        return f"{user_id}:{session_id}"

    def _get_or_create_agent(self, user_id: str) -> ChatAgent:
        """获取或创建用户的 ChatAgent 实例"""
        if user_id not in self._agents:
            agent = ChatAgent(
                name=f"api-{user_id[:8]}",
                stream=True,
            )
            agent.initialize()
            self._agents[user_id] = agent
            logger.info("新 Agent 实例: user=%s", user_id[:8])
        return self._agents[user_id]

    def _get_session_messages(
        self, user_id: str, session_id: str, max_rounds: int = 6,
    ) -> list:
        """从 LangGraph Checkpointer 读取最近 N 轮会话消息。

        只取最近 max_rounds 轮，避免上下文过长导致:
          - Query 改写 prompt 膨胀
          - Token 浪费

        Args:
            user_id: 用户 ID
            session_id: 会话 ID
            max_rounds: 最大轮数 (每轮=user+assistant, 默认 6 轮 = 12 条)

        Returns:
            最近的 LangChain message 对象列表
        """
        try:
            agent = self._get_or_create_agent(user_id)
            tid = self._make_tid(user_id, session_id)
            info = agent.get_session_info(tid)

            if not info.get("has_state"):
                return []

            config = {"configurable": {"thread_id": tid}}
            state = agent._graph.get_state(config)
            messages = state.values.get("messages", []) if state.values else []

            # 只取最近 max_rounds * 2 条 (user + assistant 各算一条)
            max_messages = max_rounds * 2
            if len(messages) > max_messages:
                return messages[-max_messages:]
            return messages
        except Exception as e:
            logger.debug("读取会话消息失败 (新会话?): %s", e)
            return []

    async def chat(
        self, user_id: str, session_id: str, query: str, scope: str = "hybrid"
    ) -> str:
        """同步问答 — 先检索知识库，再调用 ChatAgent"""
        enhanced_query = await self._build_query(
            query, scope, user_id, session_id,
        )
        agent = self._get_or_create_agent(user_id)
        tid = self._make_tid(user_id, session_id)
        return await agent.achat(enhanced_query, thread_id=tid)

    async def chat_stream(
        self, user_id: str, session_id: str, query: str, scope: str = "hybrid"
    ):
        """SSE 流式问答 — 先检索知识库，再流式输出"""
        enhanced_query = await self._build_query(
            query, scope, user_id, session_id,
        )
        agent = self._get_or_create_agent(user_id)
        tid = self._make_tid(user_id, session_id)
        async for chunk in agent.achat_stream(enhanced_query, thread_id=tid):
            yield chunk

    async def _build_query(
        self, query: str, scope: str, user_id: str, session_id: str = "",
    ) -> str:
        """构建增强查询: 用户问题 + 知识库检索结果。

        1. 提取会话上下文 (用于 query 改写)
        2. 调用检索服务 (基本检索或高级改写检索)
        3. 格式化检索结果为上下文注入 prompt

        如果没有配置检索服务，直接返回原 query。
        """
        if not self._retrieval:
            return query

        try:
            # 提取会话消息 (用于上下文改写)
            messages = []
            if session_id:
                messages = self._get_session_messages(user_id, session_id)

            # 调用检索
            from .advanced_retrieval import AdvancedRetrievalService

            if isinstance(self._retrieval, AdvancedRetrievalService):
                # 高阶检索: 传递 messages 用于 query 改写
                hits = await self._retrieval.search(
                    query=query,
                    scope=scope,
                    user_id=user_id,
                    messages=messages,
                )
            else:
                # 基础检索
                hits = await self._retrieval.search(
                    query=query,
                    scope=scope,
                    user_id=user_id,
                )

            if not hits:
                logger.debug("检索无结果: scope=%s", scope)
                return query

            from .retrieval_service import RetrievalService
            context = RetrievalService.format_context(hits)
            enhanced = (
                f"请根据以下知识库内容回答用户问题。如果知识库内容不足以回答，"
                f"请如实说明。\n\n"
                f"{context}\n"
                f"---\n"
                f"用户问题: {query}"
            )
            logger.debug("检索增强: hits=%d, chars=%d", len(hits), len(enhanced))
            return enhanced

        except Exception as e:
            logger.warning("检索失败，降级为普通对话: %s", e)
            return query
