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
        self._lock = asyncio.Lock()

    @staticmethod
    def _hash(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    async def create(self, user_id: str, key_hash: str, prefix: str) -> ApiKey:
        async with self._lock:
            entry = ApiKey(key_hash=key_hash, prefix=prefix, user_id=user_id)
            self._keys[prefix] = entry
            return entry

    async def validate(self, api_key: str) -> Identity | None:
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

    async def get_many(self, document_ids: list[str]) -> list[Document]:
        return [self._docs[doc_id] for doc_id in document_ids if doc_id in self._docs]

    async def list_by_user(self, user_id: str) -> list[Document]:
        return [d for d in self._docs.values() if d.user_id == user_id]

    async def list_by_user_paginated(
        self,
        user_id: str,
        *,
        offset: int,
        limit: int,
        search: str | None = None,
        scope: str | None = None,
        statuses: list[str] | None = None,
    ) -> tuple[list[Document], int]:
        docs = [d for d in self._docs.values() if d.user_id == user_id]
        if search:
            needle = search.casefold()
            docs = [d for d in docs if needle in d.filename.casefold()]
        if scope:
            docs = [d for d in docs if d.scope == scope]
        if statuses:
            allowed_statuses = set(statuses)
            docs = [d for d in docs if d.status in allowed_statuses]

        docs.sort(
            key=lambda doc: (doc.updated_at, doc.document_id),
            reverse=True,
        )
        total = len(docs)
        return docs[offset:offset + limit], total

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

    async def get_many(self, task_ids: list[str]) -> list[TaskRecord]:
        return [self._tasks[task_id] for task_id in task_ids if task_id in self._tasks]

    async def list_by_document(self, document_id: str) -> list[TaskRecord]:
        return [t for t in self._tasks.values() if t.document_id == document_id]

    async def list_incomplete(self) -> list[TaskRecord]:
        return [
            task for task in self._tasks.values()
            if task.status not in {"done", "failed"}
        ]
