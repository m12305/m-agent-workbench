"""会话服务 — 会话元数据管理"""

import logging
from ..repositories.base import SessionRepository, Session
from ..exceptions import NotFoundError

logger = logging.getLogger("server.session_service")


class SessionService:
    """会话管理

    会话元数据 (所有权, 标题, 统计) 由 Repository 管理.
    消息正文由 LangGraph Checkpointer (MemorySaver) 以
    thread_id = "{user_id}:{session_id}" 管理.
    """

    def __init__(self, session_repo: SessionRepository):
        self._repo = session_repo

    async def create_session(
        self, user_id: str, title: str | None = None
    ) -> Session:
        session = await self._repo.create(user_id=user_id, title=title)
        logger.info("会话创建: %s (user=%s)", session.session_id, user_id)
        return session

    async def get_session(self, session_id: str) -> Session:
        session = await self._repo.get(session_id)
        if not session:
            raise NotFoundError("会话", session_id)
        return session

    async def list_sessions(self, user_id: str) -> list[Session]:
        return await self._repo.list_by_user(user_id)

    async def delete_session(self, user_id: str, session_id: str) -> None:
        session = await self.get_session(session_id)
        if session.user_id != user_id:
            raise NotFoundError("会话", session_id)
        await self._repo.delete(session_id)
        logger.info("会话已删除: %s", session_id)

    async def rename_session(
        self, user_id: str, session_id: str, title: str | None,
    ) -> Session:
        """重命名会话 — 验证所有权后更新标题"""
        session = await self.get_session(session_id)
        if session.user_id != user_id:
            raise NotFoundError("会话", session_id)
        updated = await self._repo.update(session_id, title=title)
        if not updated:
            raise NotFoundError("会话", session_id)
        logger.info("会话已重命名: %s → %r", session_id, title)
        return updated

    async def bump_message_count(self, session_id: str) -> None:
        """问答后更新消息计数和时间戳"""
        session = await self._repo.get(session_id)
        if session:
            await self._repo.update(
                session_id,
                message_count=session.message_count + 2,  # user + assistant
            )
