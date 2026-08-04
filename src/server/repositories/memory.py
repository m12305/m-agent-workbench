"""内存存储实现"""

import asyncio
import hashlib
import uuid
from datetime import datetime

from .base import (
    User,
    ApiKey,
    Session,
    Identity,
    Document,
    ChunkRecord,
    TaskRecord,
)

class InMemoryUserRepo:
    def __init__(self):
        self._users: dict[str, User] = {}
        self._lock = asyncio.Lock()

    async def create(self, name: str, role: str) -> User:
        async with self._lock:
            user = User(
                user_id=str(uuid.uuid4())[:8],
                name=name,
                role=role,
            )
            self._users[user.user_id] = user
            return user

    async def get_by_id(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    async def list_all(self) -> list[User]:
        return list(self._users.values())

    async def delete(self, user_id: str) -> None:
        self._users.pop(user_id, None)


class InMemoryApiKeyRepo:
    def __init__(self):
        self._keys: dict[str, ApiKey] = {}     # prefix → ApiKey
        self._plain_map: dict[str, str] = {}   # plain_key → prefix
        self._lock = asyncio.Lock()

    @staticmethod
    def _hash(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    @staticmethod
    def _prefix(key: str) -> str:
        return key[:11] + "***" + key[-4:]

    async def create(self, user_id: str, key_hash: str, prefix: str) -> ApiKey:
        async with self._lock:
            entry = ApiKey(key_hash=key_hash, prefix=prefix, user_id=user_id)
            self._keys[prefix] = entry
            return entry

    async def register_plain(self, plain_key: str, prefix: str) -> None:
        """注册明文 Key → prefix 映射 (仅用于静态配置)"""
        self._plain_map[plain_key] = prefix

    async def validate(self, api_key: str) -> Identity | None:
        # 1. 通过明文映射 (静态配置的 Key)
        prefix = self._plain_map.get(api_key)
        if prefix and prefix in self._keys:
            entry = self._keys[prefix]
            if entry.revoked_at is None:
                return Identity(
                    user_id=entry.user_id,
                    role="user",
                    api_key_prefix=entry.prefix,
                )

        # 2. 通过哈希匹配 (动态创建的 Key)
        key_hash = self._hash(api_key)
        for entry in self._keys.values():
            if entry.key_hash == key_hash and entry.revoked_at is None:
                return Identity(
                    user_id=entry.user_id,
                    role="user",
                    api_key_prefix=entry.prefix,
                )
        return None

    async def revoke(self, prefix: str) -> None:
        if entry := self._keys.get(prefix):
            entry.revoked_at = datetime.utcnow()

    async def list_by_user(self, user_id: str) -> list[ApiKey]:
        return [e for e in self._keys.values() if e.user_id == user_id]


class InMemorySessionRepo:
    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def create(self, user_id: str, title: str | None) -> Session:
        async with self._lock:
            session = Session(
                session_id=str(uuid.uuid4()),
                user_id=user_id,
                title=title,
            )
            self._sessions[session.session_id] = session
            return session

    async def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def list_by_user(self, user_id: str) -> list[Session]:
        return [
            s for s in self._sessions.values()
            if s.user_id == user_id
        ]

    async def update(self, session_id: str, **kwargs) -> Session | None:
        if session := self._sessions.get(session_id):
            for k, v in kwargs.items():
                if hasattr(session, k):
                    setattr(session, k, v)
            session.updated_at = datetime.utcnow()
            return session
        return None

    async def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


# ═══════════════════════════════════════════════════════════════
# Document
# ═══════════════════════════════════════════════════════════════

class InMemoryDocumentRepo:
    def __init__(self):
        self._docs: dict[str, Document] = {}
        self._lock = asyncio.Lock()

    async def create(self, doc: Document) -> Document:
        async with self._lock:
            self._docs[doc.document_id] = doc
            return doc

    async def get(self, document_id: str) -> Document | None:
        return self._docs.get(document_id)

    async def list_by_user(self, user_id: str) -> list[Document]:
        return [d for d in self._docs.values() if d.user_id == user_id]

    async def update(self, document_id: str, **kwargs) -> Document | None:
        if doc := self._docs.get(document_id):
            for k, v in kwargs.items():
                if hasattr(doc, k):
                    setattr(doc, k, v)
            doc.updated_at = datetime.utcnow()
            return doc
        return None

    async def delete(self, document_id: str) -> None:
        self._docs.pop(document_id, None)


# ═══════════════════════════════════════════════════════════════
# Chunk
# ═══════════════════════════════════════════════════════════════

class InMemoryChunkRepo:
    def __init__(self):
        self._chunks: dict[str, list[ChunkRecord]] = {}
        self._lock = asyncio.Lock()

    async def batch_save(self, chunks: list[ChunkRecord]) -> None:
        async with self._lock:
            for c in chunks:
                self._chunks.setdefault(c.document_id, []).append(c)

    async def get_by_document(self, document_id: str) -> list[ChunkRecord]:
        return self._chunks.get(document_id, [])

    async def delete_by_document(self, document_id: str, user_id: str = "") -> None:
        self._chunks.pop(document_id, None)


# ═══════════════════════════════════════════════════════════════
# Task
# ═══════════════════════════════════════════════════════════════

class InMemoryTaskRepo:
    def __init__(self):
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = asyncio.Lock()

    async def save(self, task: TaskRecord) -> None:
        async with self._lock:
            self._tasks[task.task_id] = task

    async def get(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    async def list_by_document(self, document_id: str) -> list[TaskRecord]:
        return [t for t in self._tasks.values() if t.document_id == document_id]
