"""存储层 — 协议定义 + 内存实现 + SQLite 持久化"""
from .base import (
    UserRepository, ApiKeyRepository, SessionRepository,
    DocumentRepository, ChunkRepository, TaskRepository,
    RuntimeConfigRepository,
    SessionMessageRepository, MultiAgentTurnRepository,
    ConversationSummaryRepository,
    User, ApiKey, Session, SessionType, Identity,
    Document, ChunkRecord, TaskRecord, RuntimeConfigRecord,
    SessionMessage, MultiAgentTurn, ConversationSummary,
)
from .memory import (
    InMemoryUserRepo, InMemoryApiKeyRepo, InMemorySessionRepo,
    InMemoryDocumentRepo, InMemoryChunkRepo, InMemoryTaskRepo,
    InMemoryRuntimeConfigRepo,
    InMemorySessionMessageRepo, InMemoryMultiAgentTurnRepo,
    InMemoryConversationSummaryRepo,
)
from .sqlite import (
    SqliteDb,
    SqliteUserRepo, SqliteApiKeyRepo, SqliteSessionRepo,
    SqliteDocumentRepo, SqliteChunkRepo, SqliteTaskRepo,
    SqliteRuntimeConfigRepo,
    SqliteSessionMessageRepo, SqliteMultiAgentTurnRepo,
    SqliteConversationSummaryRepo,
    DEFAULT_DB_PATH,
)

__all__ = [
    "UserRepository", "ApiKeyRepository", "SessionRepository",
    "DocumentRepository", "ChunkRepository", "TaskRepository",
    "RuntimeConfigRepository",
    "SessionMessageRepository", "MultiAgentTurnRepository",
    "ConversationSummaryRepository",
    "User", "ApiKey", "Session", "SessionType", "Identity",
    "Document", "ChunkRecord", "TaskRecord", "RuntimeConfigRecord",
    "SessionMessage", "MultiAgentTurn", "ConversationSummary",
    # 内存实现
    "InMemoryUserRepo", "InMemoryApiKeyRepo", "InMemorySessionRepo",
    "InMemoryDocumentRepo", "InMemoryChunkRepo", "InMemoryTaskRepo",
    "InMemoryRuntimeConfigRepo",
    "InMemorySessionMessageRepo", "InMemoryMultiAgentTurnRepo",
    "InMemoryConversationSummaryRepo",
    # SQLite 持久化
    "SqliteDb",
    "SqliteUserRepo", "SqliteApiKeyRepo", "SqliteSessionRepo",
    "SqliteDocumentRepo", "SqliteChunkRepo", "SqliteTaskRepo",
    "SqliteRuntimeConfigRepo",
    "SqliteSessionMessageRepo", "SqliteMultiAgentTurnRepo",
    "SqliteConversationSummaryRepo",
    "DEFAULT_DB_PATH",
]
