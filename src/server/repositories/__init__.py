"""存储层 — 协议定义 + 内存实现 + SQLite 持久化"""
from .base import (
    UserRepository, ApiKeyRepository, SessionRepository,
    DocumentRepository, ChunkRepository, TaskRepository,
    User, ApiKey, Session, Identity,
    Document, ChunkRecord, TaskRecord,
)
from .memory import (
    InMemoryUserRepo, InMemoryApiKeyRepo, InMemorySessionRepo,
    InMemoryDocumentRepo, InMemoryChunkRepo, InMemoryTaskRepo,
)
from .sqlite import (
    SqliteDb,
    SqliteUserRepo, SqliteApiKeyRepo, SqliteSessionRepo,
    SqliteDocumentRepo, SqliteChunkRepo, SqliteTaskRepo,
    DEFAULT_DB_PATH,
)

__all__ = [
    "UserRepository", "ApiKeyRepository", "SessionRepository",
    "DocumentRepository", "ChunkRepository", "TaskRepository",
    "User", "ApiKey", "Session", "Identity",
    "Document", "ChunkRecord", "TaskRecord",
    # 内存实现
    "InMemoryUserRepo", "InMemoryApiKeyRepo", "InMemorySessionRepo",
    "InMemoryDocumentRepo", "InMemoryChunkRepo", "InMemoryTaskRepo",
    # SQLite 持久化
    "SqliteDb",
    "SqliteUserRepo", "SqliteApiKeyRepo", "SqliteSessionRepo",
    "SqliteDocumentRepo", "SqliteChunkRepo", "SqliteTaskRepo",
    "DEFAULT_DB_PATH",
]
