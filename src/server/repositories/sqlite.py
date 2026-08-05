"""SQLite 持久化存储实现

每个 Repository 对应 SQLite 中的一张表，通过 SqliteDb 统一管理连接。
所有数据库操作通过 asyncio.to_thread 在后台线程执行，避免阻塞事件循环。

数据库文件路径通过 STORAGE_SQLITE_DIR 环境变量配置，默认 ./data/mka.db。
"""

import asyncio
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from .base import (
    User, ApiKey, Session, Identity,
    Document, ChunkRecord, TaskRecord,
)

logger = logging.getLogger("server.sqlite_repos")

# ── 默认 SQLite 数据库路径 ──
DEFAULT_DB_PATH = os.path.join(
    os.getenv("STORAGE_SQLITE_DIR", os.path.join(os.getcwd(), "data")),
    "mka.db",
)


# ═══════════════════════════════════════════════════════════════════
# SQLite 连接管理
# ═══════════════════════════════════════════════════════════════════

class SqliteDb:
    """SQLite 数据库连接管理器。

    特性:
      - WAL 模式 (高并发读写)
      - 自动创建目录和表结构
      - 通过 asyncio.to_thread 实现异步
      - check_same_thread=False 支持多线程访问
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._conn: "sqlite3.Connection | None" = None
        self._initialized = False

    @property
    def db_path(self) -> str:
        return self._db_path

    # ── 连接生命周期 ──

    def _get_conn(self):
        """获取底层 sqlite3 连接 (同步, 在 to_thread 内调用)"""
        import sqlite3

        if self._conn is None:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    async def init_schema(self) -> None:
        """创建所有表 (幂等)"""
        def _init():
            conn = self._get_conn()
            conn.executescript(SCHEMA_SQL)
            conn.executescript(LEGACY_STATIC_KEY_MIGRATION_SQL)
            conn.commit()
        await asyncio.to_thread(_init)
        self._initialized = True

    async def close(self) -> None:
        """关闭数据库连接"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            self._initialized = False

    # ── 通用查询方法 ──

    async def execute(self, sql: str, params: tuple | list | None = None) -> None:
        """执行写入 SQL (INSERT / UPDATE / DELETE)"""
        def _run():
            conn = self._get_conn()
            conn.execute(sql, params or [])
            conn.commit()
        await asyncio.to_thread(_run)

    async def executemany(self, sql: str, params_list: list) -> None:
        """批量执行写入 SQL"""
        if not params_list:
            return
        def _run():
            conn = self._get_conn()
            conn.executemany(sql, params_list)
            conn.commit()
        await asyncio.to_thread(_run)

    async def fetchall(self, sql: str, params: tuple | list | None = None) -> list[dict]:
        """查询多条记录, 返回 dict 列表"""
        def _run():
            conn = self._get_conn()
            rows = conn.execute(sql, params or []).fetchall()
            return [dict(r) for r in rows]
        return await asyncio.to_thread(_run)

    async def fetchone(self, sql: str, params: tuple | list | None = None) -> dict | None:
        """查询单条记录, 返回 dict 或 None"""
        def _run():
            conn = self._get_conn()
            row = conn.execute(sql, params or []).fetchone()
            return dict(row) if row else None
        return await asyncio.to_thread(_run)

    async def fetchval(self, sql: str, params: tuple | list | None = None):
        """查询单个值 (第一行第一列)"""
        def _run():
            conn = self._get_conn()
            row = conn.execute(sql, params or []).fetchone()
            return row[0] if row else None
        return await asyncio.to_thread(_run)


# ═══════════════════════════════════════════════════════════════════
# Schema DDL
# ═══════════════════════════════════════════════════════════════════

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'user',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
    prefix      TEXT PRIMARY KEY,
    key_hash    TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    revoked_at  TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    title         TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    document_id   TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    filename      TEXT NOT NULL,
    storage_key   TEXT NOT NULL,
    mime_type     TEXT NOT NULL,
    file_size     INTEGER NOT NULL DEFAULT 0,
    file_hash     TEXT NOT NULL DEFAULT '',
    scope         TEXT NOT NULL DEFAULT 'private',
    status        TEXT NOT NULL DEFAULT 'uploaded',
    chunk_count   INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     TEXT PRIMARY KEY,
    document_id  TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    chunk_index  INTEGER NOT NULL,
    chunk_hash   TEXT NOT NULL,
    text         TEXT NOT NULL,
    page_start   INTEGER NOT NULL DEFAULT 0,
    page_end     INTEGER NOT NULL DEFAULT 0,
    sections     TEXT NOT NULL DEFAULT '[]',
    metadata     TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_user ON chunks(user_id);

CREATE TABLE IF NOT EXISTS tasks (
    task_id       TEXT PRIMARY KEY,
    document_id   TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued',
    progress      REAL NOT NULL DEFAULT 0.0,
    error_message TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_document ON tasks(document_id);
"""


# 旧版本把 .env 静态 Key 写入 api_keys，却可能没有正确创建关联用户。
# 这里只修复已经持久化的数据，不再读取或注册任何环境变量 Key。
LEGACY_STATIC_KEY_MIGRATION_SQL = """
INSERT OR IGNORE INTO users (user_id, name, role, created_at)
SELECT
    api_key.user_id,
    CASE
        WHEN api_key.user_id LIKE 'sk-static-admin-%'
            THEN 'Migrated admin (' || api_key.prefix || ')'
        ELSE 'Migrated user (' || api_key.prefix || ')'
    END,
    CASE
        WHEN api_key.user_id LIKE 'sk-static-admin-%' THEN 'admin'
        ELSE 'user'
    END,
    api_key.created_at
FROM api_keys AS api_key
WHERE api_key.user_id LIKE 'sk-static-admin-%'
   OR api_key.user_id LIKE 'sk-static-user-%';
"""


# ═══════════════════════════════════════════════════════════════════
# 序列化 / 反序列化工具
# ═══════════════════════════════════════════════════════════════════

def _now() -> str:
    """返回 ISO 8601 时间戳 (UTC)"""
    return datetime.utcnow().isoformat()

def _parse_dt(s: str | None) -> datetime:
    """将 ISO 字符串解析为 datetime (兼容旧数据)"""
    if not s:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return datetime.utcnow()

def _json_list(val) -> str:
    """将 list 序列化为 JSON 字符串"""
    return json.dumps(val, ensure_ascii=False)

def _parse_json_list(s: str | None) -> list:
    """从 JSON 字符串反序列化为 list"""
    if not s:
        return []
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return []

def _json_dict(val) -> str:
    """将 dict 序列化为 JSON 字符串"""
    if val is None:
        return "{}"
    return json.dumps(val, ensure_ascii=False)

def _parse_json_dict(s: str | None) -> dict:
    """从 JSON 字符串反序列化为 dict"""
    if not s:
        return {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}


# ═══════════════════════════════════════════════════════════════════
# SqliteUserRepo
# ═══════════════════════════════════════════════════════════════════

class SqliteUserRepo:
    """SQLite 用户存储"""

    def __init__(self, db: SqliteDb):
        self._db = db

    async def create(self, name: str, role: str) -> User:
        user_id = str(uuid.uuid4())[:8]
        now = _now()
        await self._db.execute(
            "INSERT INTO users (user_id, name, role, created_at) VALUES (?, ?, ?, ?)",
            (user_id, name, role, now),
        )
        return User(user_id=user_id, name=name, role=role,
                     created_at=datetime.fromisoformat(now))

    async def get_by_id(self, user_id: str) -> User | None:
        row = await self._db.fetchone(
            "SELECT * FROM users WHERE user_id = ?", (user_id,))
        if not row:
            return None
        return User(
            user_id=row["user_id"], name=row["name"], role=row["role"],
            created_at=_parse_dt(row["created_at"]),
        )

    async def list_all(self) -> list[User]:
        rows = await self._db.fetchall("SELECT * FROM users ORDER BY created_at")
        return [
            User(user_id=r["user_id"], name=r["name"], role=r["role"],
                 created_at=_parse_dt(r["created_at"]))
            for r in rows
        ]

    async def delete(self, user_id: str) -> None:
        await self._db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))


# ═══════════════════════════════════════════════════════════════════
# SqliteApiKeyRepo
# ═══════════════════════════════════════════════════════════════════

class SqliteApiKeyRepo:
    """SQLite API Key 存储

    安全设计:
      - key_hash 存储 SHA-256 哈希值 (不存明文)
      - validate() 仅通过哈希表校验持久化 Key
    """

    def __init__(self, db: SqliteDb):
        self._db = db

    @staticmethod
    def _hash(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    # ── 协议方法 ──

    async def create(self, user_id: str, key_hash: str, prefix: str) -> ApiKey:
        now = _now()
        await self._db.execute(
            "INSERT OR IGNORE INTO api_keys (prefix, key_hash, user_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (prefix, key_hash, user_id, now),
        )
        return ApiKey(key_hash=key_hash, prefix=prefix, user_id=user_id,
                       created_at=datetime.fromisoformat(now))

    async def validate(self, api_key: str) -> Identity | None:
        key_hash = self._hash(api_key)
        row = await self._db.fetchone(
            "SELECT user_id, prefix FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL",
            (key_hash,),
        )
        if row:
            return Identity(
                user_id=row["user_id"], role="user",
                api_key_prefix=row["prefix"],
            )
        return None

    async def revoke(self, prefix: str) -> None:
        now = _now()
        await self._db.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE prefix = ?", (now, prefix))

    async def list_by_user(self, user_id: str) -> list[ApiKey]:
        rows = await self._db.fetchall(
            "SELECT * FROM api_keys WHERE user_id = ? ORDER BY created_at", (user_id,))
        return [
            ApiKey(
                key_hash=r["key_hash"], prefix=r["prefix"],
                user_id=r["user_id"],
                created_at=_parse_dt(r["created_at"]),
                revoked_at=_parse_dt(r["revoked_at"]) if r["revoked_at"] else None,
            )
            for r in rows
        ]


# ═══════════════════════════════════════════════════════════════════
# SqliteSessionRepo
# ═══════════════════════════════════════════════════════════════════

class SqliteSessionRepo:
    """SQLite 会话存储"""

    def __init__(self, db: SqliteDb):
        self._db = db

    async def create(self, user_id: str, title: str | None) -> Session:
        session_id = str(uuid.uuid4())
        now = _now()
        await self._db.execute(
            "INSERT INTO sessions (session_id, user_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, title, now, now),
        )
        return Session(
            session_id=session_id, user_id=user_id, title=title,
            message_count=0,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )

    async def get(self, session_id: str) -> Session | None:
        row = await self._db.fetchone(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        if not row:
            return None
        return Session(
            session_id=row["session_id"], user_id=row["user_id"],
            title=row["title"], message_count=row["message_count"],
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
        )

    async def list_by_user(self, user_id: str) -> list[Session]:
        rows = await self._db.fetchall(
            "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
        return [
            Session(
                session_id=r["session_id"], user_id=r["user_id"],
                title=r["title"], message_count=r["message_count"],
                created_at=_parse_dt(r["created_at"]),
                updated_at=_parse_dt(r["updated_at"]),
            )
            for r in rows
        ]

    async def update(self, session_id: str, **kwargs) -> Session | None:
        """根据 kwargs 动态构建 UPDATE 语句

        支持的字段: title, message_count
        """
        allowed = {"title", "message_count"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return await self.get(session_id)

        set_clauses = [f"{k} = ?" for k in updates]
        values = list(updates.values())
        values.append(_now())   # updated_at
        values.append(session_id)

        await self._db.execute(
            f"UPDATE sessions SET {', '.join(set_clauses)}, updated_at = ? "
            f"WHERE session_id = ?",
            tuple(values),
        )
        return await self.get(session_id)

    async def delete(self, session_id: str) -> None:
        await self._db.execute(
            "DELETE FROM sessions WHERE session_id = ?", (session_id,))


# ═══════════════════════════════════════════════════════════════════
# SqliteDocumentRepo
# ═══════════════════════════════════════════════════════════════════

class SqliteDocumentRepo:
    """SQLite 文档元数据存储"""

    def __init__(self, db: SqliteDb):
        self._db = db

    async def create(self, doc: Document) -> Document:
        await self._db.execute(
            "INSERT INTO documents (document_id, user_id, filename, storage_key, "
            "mime_type, file_size, file_hash, scope, status, chunk_count, "
            "error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc.document_id, doc.user_id, doc.filename, doc.storage_key,
             doc.mime_type, doc.file_size, doc.file_hash, doc.scope,
             doc.status, doc.chunk_count, doc.error_message,
             doc.created_at.isoformat(), doc.updated_at.isoformat()),
        )
        return doc

    async def get(self, document_id: str) -> Document | None:
        row = await self._db.fetchone(
            "SELECT * FROM documents WHERE document_id = ?", (document_id,))
        if not row:
            return None
        return self._row_to_doc(row)

    async def list_by_user(self, user_id: str) -> list[Document]:
        rows = await self._db.fetchall(
            "SELECT * FROM documents WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
        return [self._row_to_doc(r) for r in rows]

    async def update(self, document_id: str, **kwargs) -> Document | None:
        """根据 kwargs 动态构建 UPDATE 语句

        支持的字段: status, chunk_count, error_message, file_size, scope
        """
        allowed = {"status", "chunk_count", "error_message", "file_size", "scope"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return await self.get(document_id)

        set_clauses = [f"{k} = ?" for k in updates]
        values = list(updates.values())
        values.append(_now())    # updated_at
        values.append(document_id)

        await self._db.execute(
            f"UPDATE documents SET {', '.join(set_clauses)}, updated_at = ? "
            f"WHERE document_id = ?",
            tuple(values),
        )
        return await self.get(document_id)

    async def delete(self, document_id: str) -> None:
        await self._db.execute(
            "DELETE FROM documents WHERE document_id = ?", (document_id,))

    # ── 内部工具 ──

    @staticmethod
    def _row_to_doc(row: dict) -> Document:
        return Document(
            document_id=row["document_id"], user_id=row["user_id"],
            filename=row["filename"], storage_key=row["storage_key"],
            mime_type=row["mime_type"], file_size=row["file_size"],
            file_hash=row["file_hash"], scope=row["scope"],
            status=row["status"], chunk_count=row["chunk_count"],
            error_message=row["error_message"],
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
        )


# ═══════════════════════════════════════════════════════════════════
# SqliteChunkRepo
# ═══════════════════════════════════════════════════════════════════

class SqliteChunkRepo:
    """SQLite Chunk 存储 — ChunkRecord 的持久化"""

    def __init__(self, db: SqliteDb):
        self._db = db

    async def batch_save(self, chunks: list[ChunkRecord]) -> None:
        """批量写入 Chunk (executemany)"""
        if not chunks:
            return
        now = _now()
        rows = [
            (c.chunk_id, c.document_id, c.user_id,
             c.chunk_index, c.chunk_hash, c.text,
             c.page_start, c.page_end,
             _json_list(c.sections), _json_dict(c.metadata),
             now)
            for c in chunks
        ]
        await self._db.executemany(
            "INSERT INTO chunks (chunk_id, document_id, user_id, "
            "chunk_index, chunk_hash, text, page_start, page_end, "
            "sections, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    async def get_by_document(self, document_id: str) -> list[ChunkRecord]:
        rows = await self._db.fetchall(
            "SELECT * FROM chunks WHERE document_id = ? ORDER BY chunk_index",
            (document_id,),
        )
        return [self._row_to_chunk(r) for r in rows]

    async def delete_by_document(self, document_id: str, user_id: str = "") -> None:
        """删除文档的所有 Chunk，可选 user_id 双重校验"""
        if user_id:
            await self._db.execute(
                "DELETE FROM chunks WHERE document_id = ? AND user_id = ?",
                (document_id, user_id),
            )
        else:
            await self._db.execute(
                "DELETE FROM chunks WHERE document_id = ?", (document_id,))

    # ── 内部工具 ──

    @staticmethod
    def _row_to_chunk(row: dict) -> ChunkRecord:
        return ChunkRecord(
            chunk_id=row["chunk_id"], document_id=row["document_id"],
            user_id=row["user_id"],
            chunk_index=row["chunk_index"], chunk_hash=row["chunk_hash"],
            text=row["text"],
            page_start=row["page_start"], page_end=row["page_end"],
            sections=_parse_json_list(row["sections"]),
            metadata=_parse_json_dict(row["metadata"]),
            created_at=_parse_dt(row["created_at"]),
        )


# ═══════════════════════════════════════════════════════════════════
# SqliteTaskRepo
# ═══════════════════════════════════════════════════════════════════

class SqliteTaskRepo:
    """SQLite 任务存储"""

    def __init__(self, db: SqliteDb):
        self._db = db

    async def save(self, task: TaskRecord) -> None:
        """Upsert 任务记录 (INSERT OR REPLACE)"""
        await self._db.execute(
            "INSERT OR REPLACE INTO tasks (task_id, document_id, status, "
            "progress, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task.task_id, task.document_id, task.status,
             task.progress, task.error_message,
             task.created_at.isoformat(), task.updated_at.isoformat()),
        )

    async def get(self, task_id: str) -> TaskRecord | None:
        row = await self._db.fetchone(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        if not row:
            return None
        return TaskRecord(
            task_id=row["task_id"], document_id=row["document_id"],
            status=row["status"], progress=row["progress"],
            error_message=row["error_message"],
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
        )

    async def list_by_document(self, document_id: str) -> list[TaskRecord]:
        rows = await self._db.fetchall(
            "SELECT * FROM tasks WHERE document_id = ? ORDER BY created_at DESC",
            (document_id,),
        )
        return [
            TaskRecord(
                task_id=r["task_id"], document_id=r["document_id"],
                status=r["status"], progress=r["progress"],
                error_message=r["error_message"],
                created_at=_parse_dt(r["created_at"]),
                updated_at=_parse_dt(r["updated_at"]),
            )
            for r in rows
        ]
