"""
===========================================================================
多智能体 API 路由
===========================================================================

POST /api/v1/multi-agent/chat/stream  — SSE 流式多智能体问答

事件类型 (分级展示):
  start, analyzing, analysis_done, plan_created,
  dispatching, subagent_start, subagent_plan, subagent_step,
  subagent_progress, subagent_done,
  synthesizing, synthesis_done,
  tool_call, token, error, done
===========================================================================
"""

import json
import logging
import asyncio

from fastapi import APIRouter, Depends, Request, BackgroundTasks
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ..deps import get_identity, get_session_service
from ..repositories.base import Identity
from ..services.multi_agent_service import MultiAgentService
from ..services.session_service import SessionService

logger = logging.getLogger("server.api.multi_agent")

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════════════════

class MultiAgentRequest(BaseModel):
    """多智能体问答请求"""
    query: str = Field(
        min_length=1, max_length=4000,
        description="用户任务描述",
    )
    session_id: str | None = Field(
        default=None,
        description="会话 ID (不传则自动创建新会话)",
    )


# ═══════════════════════════════════════════════════════════════════════
# 依赖注入 helper
# ═══════════════════════════════════════════════════════════════════════

async def get_multi_agent_service(request: Request) -> MultiAgentService:
    """从 app.state 获取 MultiAgentService"""
    return request.app.state.multi_agent_service


# ═══════════════════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════════════════

@router.post("/multi-agent/chat/stream")
async def multi_agent_chat_stream(
    body: MultiAgentRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    identity: Identity = Depends(get_identity),
    multi_agent_service: MultiAgentService = Depends(get_multi_agent_service),
    session_service: SessionService = Depends(get_session_service),
):
    """多智能体 SSE 流式问答

    与 /chat/stream 相同的 SSE 模式, 但事件类型更丰富:
      - plan_created:  编排计划已生成
      - dispatching:   正在调度 subagent
      - subagent_*:    subagent 内部事件 (分级展示)
      - synthesizing:  正在综合结果
      - token:         LLM 文本增量
    """
    # 创建或验证会话
    session_id = body.session_id
    if session_id:
        session = await session_service.get_session(session_id)
        if session is None or session.user_id != identity.user_id:
            return EventSourceResponse(
                _error_stream("SESSION_NOT_FOUND", "会话不存在或无权访问")
            )
    else:
        session = await session_service.create_session(
            user_id=identity.user_id,
            title=body.query[:50],
        )
        session_id = session.session_id

    async def event_generator():
        # 开始事件
        yield {
            "event": "start",
            "data": json.dumps({"session_id": session_id}, ensure_ascii=False),
        }

        try:
            async for event in multi_agent_service.chat_stream(
                user_id=identity.user_id,
                session_id=session_id,
                query=body.query,
            ):
                if await request.is_disconnected():
                    multi_agent_service.cancel_run(
                        multi_agent_service._make_tid(identity.user_id, session_id)
                    )
                    return
                event_type = event.get("event", "message")
                data = event.get("data", {})
                yield {
                    "event": event_type,
                    "data": json.dumps(data, ensure_ascii=False, default=str),
                }
        except (GeneratorExit, asyncio.CancelledError):
            multi_agent_service.cancel_run(
                multi_agent_service._make_tid(identity.user_id, session_id)
            )
            raise
        except Exception as e:
            logger.exception("Multi-agent stream error")
            yield {
                "event": "error",
                "data": json.dumps({
                    "code": "AGENT_ERROR",
                    "message": str(e),
                    "agent": "main",
                }, ensure_ascii=False),
            }

        # 结束事件
        if await request.is_disconnected():
            multi_agent_service.cancel_run(
                multi_agent_service._make_tid(identity.user_id, session_id)
            )
            return
        yield {
            "event": "done",
            "data": json.dumps({"session_id": session_id}, ensure_ascii=False),
        }

        # 更新会话消息计数
        background_tasks.add_task(
            session_service.bump_message_count, session_id
        )

    return EventSourceResponse(event_generator())


@router.post("/multi-agent/chat/{session_id}/cancel")
async def cancel_multi_agent_run(
    session_id: str,
    identity: Identity = Depends(get_identity),
    multi_agent_service: MultiAgentService = Depends(get_multi_agent_service),
    session_service: SessionService = Depends(get_session_service),
):
    """Cooperatively cancel the active run owned by the current user."""
    session = await session_service.get_session(session_id)
    if session is None or session.user_id != identity.user_id:
        return {"cancelled": False}
    cancelled = multi_agent_service.cancel_run(
        multi_agent_service._make_tid(identity.user_id, session_id)
    )
    return {"cancelled": cancelled}


async def _error_stream(code: str, message: str):
    """生成错误事件流"""
    yield {
        "event": "error",
        "data": json.dumps({"code": code, "message": message}, ensure_ascii=False),
    }
    yield {
        "event": "done",
        "data": json.dumps({"session_id": None}, ensure_ascii=False),
    }
