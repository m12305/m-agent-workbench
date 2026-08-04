"""认证服务 — Key 校验, 用户/API Key 管理"""

import hashlib
import secrets
import logging
from datetime import datetime

from ..repositories.base import (
    UserRepository, ApiKeyRepository, Identity,
)
from ..exceptions import AuthorizationError, NotFoundError

logger = logging.getLogger("server.auth_service")

STATIC_KEY_PREFIX = "sk-static"


class AuthService:
    """认证服务

    支持两种 Key 来源:
    1. 静态配置 (ADMIN_API_KEYS / USER_API_KEYS 环境变量)
    2. 动态创建 (POST /api/v1/api-keys)
    """

    def __init__(
        self,
        user_repo: UserRepository,
        api_key_repo: ApiKeyRepository,
        admin_keys: list[str] | None = None,
        user_keys: list[str] | None = None,
    ):
        self._user_repo = user_repo
        self._api_key_repo = api_key_repo
        self._admin_keys = set(admin_keys or [])
        self._user_keys = set(user_keys or [])
        # 静态 Key → Identity 的映射
        self._static_identities: dict[str, Identity] = {}

    async def initialize(self) -> None:
        """注册静态配置的 Key (启动时调用)"""
        for key in self._admin_keys:
            await self._register_static_key(key, "admin")
        for key in self._user_keys:
            await self._register_static_key(key, "user")
        count = len(self._admin_keys) + len(self._user_keys)
        if count > 0:
            logger.info("已加载 %d 个静态 API Key", count)

    async def _register_static_key(self, plain_key: str, role: str) -> None:
        """注册一个静态 Key"""
        user_id = f"{STATIC_KEY_PREFIX}-{role}-{hashlib.md5(plain_key.encode()).hexdigest()[:6]}"
        prefix = self._key_prefix(plain_key)
        key_hash = self._hash_key(plain_key)

        # 确保用户存在
        existing = await self._user_repo.get_by_id(user_id)
        if not existing:
            await self._user_repo.create(
                name=f"Static {role} ({prefix})",
                role=role,
            )

        # 注册 Key
        await self._api_key_repo.create(user_id, key_hash, prefix)
        # 同时注册明文映射 (用于 validate_key)
        if hasattr(self._api_key_repo, 'register_plain'):
            await self._api_key_repo.register_plain(plain_key, prefix)

        self._static_identities[plain_key] = Identity(
            user_id=user_id,
            role=role,
            api_key_prefix=prefix,
        )

    @staticmethod
    def _hash_key(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    @staticmethod
    def _key_prefix(key: str) -> str:
        return key[:11] + "***" + key[-4:]

    async def validate_key(self, api_key: str) -> Identity | None:
        """校验 API Key，返回 Identity 或 None"""
        # 1. 先查静态映射
        if identity := self._static_identities.get(api_key):
            return identity

        # 2. 查动态创建的 Key
        return await self._api_key_repo.validate(api_key)

    async def create_user(self, name: str, role: str) -> dict:
        """创建用户"""
        user = await self._user_repo.create(name=name, role=role)
        return {
            "user_id": user.user_id,
            "name": user.name,
            "role": user.role,
            "created_at": user.created_at,
        }

    async def create_api_key(self, user_id: str) -> dict:
        """为用户生成 API Key (返回完整 Key 仅此一次)"""
        user = await self._user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("用户", user_id)

        plain_key = f"sk-{secrets.token_hex(16)}"
        key_hash = self._hash_key(plain_key)
        prefix = self._key_prefix(plain_key)

        await self._api_key_repo.create(user_id, key_hash, prefix)
        if hasattr(self._api_key_repo, 'register_plain'):
            await self._api_key_repo.register_plain(plain_key, prefix)

        return {
            "key": plain_key,
            "prefix": prefix,
            "created_at": datetime.utcnow(),
        }

    async def revoke_key(self, prefix: str) -> None:
        """撤销 API Key"""
        await self._api_key_repo.revoke(prefix)

    async def list_users(self) -> list[dict]:
        """列出所有用户"""
        users = await self._user_repo.list_all()
        return [
            {"user_id": u.user_id, "name": u.name, "role": u.role,
             "created_at": u.created_at}
            for u in users
        ]

    async def get_user(self, user_id: str) -> dict:
        """获取用户详情"""
        user = await self._user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("用户", user_id)
        return {
            "user_id": user.user_id, "name": user.name,
            "role": user.role, "created_at": user.created_at,
        }

    async def delete_user(self, user_id: str) -> None:
        """删除用户 (同步清理其 API Keys)"""
        user = await self._user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("用户", user_id)
        # 撤销该用户所有 API Key
        keys = await self._api_key_repo.list_by_user(user_id)
        for k in keys:
            if not k.revoked_at:
                await self._api_key_repo.revoke(k.prefix)
        await self._user_repo.delete(user_id)

    async def list_user_keys(self, user_id: str) -> list[dict]:
        """列出用户的所有 API Key"""
        keys = await self._api_key_repo.list_by_user(user_id)
        return [
            {"prefix": k.prefix, "user_id": k.user_id,
             "created_at": k.created_at, "revoked_at": k.revoked_at}
            for k in keys
        ]

    async def require_admin(self, user_id: str) -> None:
        """确保用户是 admin，否则抛出 AuthorizationError"""
        user = await self._user_repo.get_by_id(user_id)
        if not user or user.role != "admin":
            raise AuthorizationError("需要管理员权限")
