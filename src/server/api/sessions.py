"""CRUD /api/v1/sessions"""

from fastapi import APIRouter, Depends

from ..schemas import CreateSessionRequest, UpdateSessionRequest, SessionResponse, MessageView
from ..deps import get_identity, get_session_service, get_chat_service
from ..repositories.base import Identity
from ..services.session_service import SessionService
from ..services.chat_service import ChatService

router = APIRouter()


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=201,
)
async def create_session(
    body: CreateSessionRequest,
    identity: Identity = Depends(get_identity),
    session_service: SessionService = Depends(get_session_service),
):
    """创建新会话"""
    session = await session_service.create_session(
        user_id=identity.user_id,
        title=body.title,
    )
    return SessionResponse(
        session_id=session.session_id,
        title=session.title,
        message_count=session.message_count,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.get(
    "/sessions",
    response_model=list[SessionResponse],
)
async def list_sessions(
    identity: Identity = Depends(get_identity),
    session_service: SessionService = Depends(get_session_service),
):
    """列出当前用户的所有会话"""
    sessions = await session_service.list_sessions(identity.user_id)
    return [
        SessionResponse(
            session_id=s.session_id,
            title=s.title,
            message_count=s.message_count,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]


@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[MessageView],
)
async def get_messages(
    session_id: str,
    identity: Identity = Depends(get_identity),
    session_service: SessionService = Depends(get_session_service),
    chat_service: ChatService = Depends(get_chat_service),
):
    """获取会话消息历史"""
    # 验证会话属于当前用户
    session = await session_service.get_session(session_id)
    if session.user_id != identity.user_id:
        from ..exceptions import NotFoundError
        raise NotFoundError("会话", session_id)

    # 从 ChatAgent Checkpointer 读取消息
    agent = chat_service._get_or_create_agent(identity.user_id)
    tid = chat_service._make_tid(identity.user_id, session_id)
    info = agent.get_session_info(tid)

    messages: list[MessageView] = []
    if info["has_state"]:
        config = {"configurable": {"thread_id": tid}}
        state = agent._graph.get_state(config)
        from langchain_core.messages import HumanMessage, AIMessage
        from datetime import datetime

        stored_messages = state.values.get("messages", [])
        for msg in chat_service.visible_messages(stored_messages):
            if isinstance(msg, HumanMessage):
                messages.append(MessageView(
                    role="user", content=str(msg.content),
                    created_at=datetime.utcnow(),
                ))
            elif isinstance(msg, AIMessage):
                messages.append(MessageView(
                    role="assistant", content=str(msg.content),
                    created_at=datetime.utcnow(),
                ))
    return messages


@router.patch(
    "/sessions/{session_id}",
    response_model=SessionResponse,
)
async def update_session(
    body: UpdateSessionRequest,
    session_id: str,
    identity: Identity = Depends(get_identity),
    session_service: SessionService = Depends(get_session_service),
):
    """重命名会话"""
    session = await session_service.rename_session(
        identity.user_id, session_id, body.title,
    )
    return SessionResponse(
        session_id=session.session_id,
        title=session.title,
        message_count=session.message_count,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=204,
)
async def delete_session(
    session_id: str,
    identity: Identity = Depends(get_identity),
    session_service: SessionService = Depends(get_session_service),
):
    """删除会话"""
    await session_service.delete_session(identity.user_id, session_id)
