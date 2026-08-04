"""存储层协议定义"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class User:
    user_id: str
    name: str
    role: str
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ApiKey:
    key_hash: str
    prefix: str
    user_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    revoked_at: datetime | None = None


@dataclass
class Identity:
    user_id: str
    role: str
    api_key_prefix: str


@dataclass
class Session:
    session_id: str
    user_id: str
    title: str | None
    message_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class UserRepository(Protocol):
    async def create(self, name: str, role: str) -> User: ...
    async def get_by_id(self, user_id: str) -> User | None: ...
    async def list_all(self) -> list[User]: ...
    async def delete(self, user_id: str) -> None: ...


class ApiKeyRepository(Protocol):
    async def create(self, user_id: str, key_hash: str, prefix: str) -> ApiKey: ...
    async def validate(self, api_key: str) -> Identity | None: ...
    async def revoke(self, prefix: str) -> None: ...
    async def list_by_user(self, user_id: str) -> list[ApiKey]: ...


class SessionRepository(Protocol):
    async def create(self, user_id: str, title: str | None) -> Session: ...
    async def get(self, session_id: str) -> Session | None: ...
    async def list_by_user(self, user_id: str) -> list[Session]: ...
    async def update(self, session_id: str, **kwargs) -> Session | None: ...
    async def delete(self, session_id: str) -> None: ...


# ═══════════════════════════════════════════════════════════════
# Document
# ═══════════════════════════════════════════════════════════════

@dataclass
class Document:
    document_id: str
    user_id: str
    filename: str
    storage_key: str
    mime_type: str
    file_size: int = 0
    file_hash: str = ""
    scope: str = "private"
    status: str = "uploaded"
    chunk_count: int = 0
    error_message: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class DocumentRepository(Protocol):
    async def create(self, doc: Document) -> Document: ...
    async def get(self, document_id: str) -> Document | None: ...
    async def list_by_user(self, user_id: str) -> list[Document]: ...
    async def update(self, document_id: str, **kwargs) -> Document | None: ...
    async def delete(self, document_id: str) -> None: ...


# ═══════════════════════════════════════════════════════════════
# Chunk
# ═══════════════════════════════════════════════════════════════

@dataclass
class ChunkRecord:
    chunk_id: str
    document_id: str
    user_id: str
    chunk_index: int
    chunk_hash: str
    text: str
    page_start: int
    page_end: int
    sections: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


class ChunkRepository(Protocol):
    async def batch_save(self, chunks: list[ChunkRecord]) -> None: ...
    async def get_by_document(self, document_id: str) -> list[ChunkRecord]: ...
    async def delete_by_document(self, document_id: str, user_id: str = "") -> None: ...


# ═══════════════════════════════════════════════════════════════
# Task
# ═══════════════════════════════════════════════════════════════

@dataclass
class TaskRecord:
    task_id: str
    document_id: str
    status: str
    progress: float = 0.0
    error_message: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class TaskRepository(Protocol):
    async def save(self, task: TaskRecord) -> None: ...
    async def get(self, task_id: str) -> TaskRecord | None: ...
    async def list_by_document(self, document_id: str) -> list[TaskRecord]: ...
