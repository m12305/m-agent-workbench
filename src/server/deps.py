"""FastAPI 依赖注入"""

from fastapi import Request, Depends

from .repositories.base import Identity
from .exceptions import AuthenticationError, AuthorizationError


async def get_identity(request: Request) -> Identity:
    """从 request.state 提取当前用户身份"""
    user_id = getattr(request.state, "user_id", None)
    role = getattr(request.state, "role", None)
    prefix = getattr(request.state, "api_key_prefix", None)

    if not user_id:
        raise AuthenticationError()

    return Identity(
        user_id=user_id,
        role=role or "user",
        api_key_prefix=prefix or "unknown",
    )


async def require_admin(identity: Identity = Depends(get_identity)) -> Identity:
    """要求 admin 角色"""
    if identity.role != "admin":
        raise AuthorizationError("需要管理员权限")
    return identity


def get_auth_service(request: Request):
    """获取 AuthService (从 app.state 注入)"""
    return request.app.state.auth_service


def get_session_service(request: Request):
    """获取 SessionService"""
    return request.app.state.session_service


def get_chat_service(request: Request):
    """获取 ChatService"""
    return request.app.state.chat_service
