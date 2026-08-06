"""SQLite 持久化存储实现

每个 Repository 对应 SQLite 中的一张表，通过 SqliteDb 统一管理连接。
普通操作使用独立 aiosqlite 短连接；事务在一个固定连接中完成。

数据库文件路径通过 STORAGE_SQLITE_DIR 环境变量配置，默认 ./data/mka.db。
"""

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

import aiosqlite

from .base import (
    User, ApiKey, Session, Identity,
    Document, ChunkRecord, TaskRecord,
)

logger = logging.getLogger("server.sqlite_repos")
T = TypeVar("T")

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
      - 普通操作使用独立 aiosqlite 连接，避免共享连接并发误用
      - WAL + busy_timeout 支持多连接读写
      - 事务期间固定使用同一连接
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._memory_uri: str | None = None
        self._keeper: aiosqlite.Connection | None = None
        self._initialized = False
        self._closed = False

    @property
    def db_path(self) -> str:
        return self._db_path

    # ── 连接生命周期 ──

    async def _connect(self) -> aiosqlite.Connection:
        if self._closed:
            raise RuntimeError("SQLite 数据库已经关闭")

        db_path = self._memory_uri or self._db_path
        conn = await aiosqlite.connect(
            db_path,
            timeout=5.0,
            uri=self._memory_uri is not None,
        )
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute("PRAGMA busy_timeout=5000")
        return conn

    async def init_schema(self) -> None:
        """创建所有表 (幂等)"""
        self._closed = False
        if self._db_path == ":memory:":
            self._memory_uri = f"file:mka-{uuid.uuid4()}?mode=memory&cache=shared"
            self._keeper = await self._connect()
            conn = self._keeper
        else:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = await self._connect()

        try:
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.executescript(SCHEMA_SQL)
            await conn.executescript(LEGACY_STATIC_KEY_MIGRATION_SQL)
            await conn.commit()
        finally:
            if conn is not self._keeper:
                await conn.close()
        self._initialized = True

    async def close(self) -> None:
        """关闭数据库连接"""
        self._closed = True
        if self._keeper is not None:
            await self._keeper.close()
            self._keeper = None
        self._initialized = False

    # ── 通用查询方法 ──

    async def execute(self, sql: str, params: tuple | list | None = None) -> None:
        """执行写入 SQL (INSERT / UPDATE / DELETE)"""
        conn = await self._connect()
        try:
            await conn.execute(sql, params or [])
            await conn.commit()
        finally:
            await conn.close()

    async def executemany(self, sql: str, params_list: list) -> None:
        """批量执行写入 SQL"""
        if not params_list:
            return
        conn = await self._connect()
        try:
            await conn.executemany(sql, params_list)
            await conn.commit()
        finally:
            await conn.close()

    async def fetchall(self, sql: str, params: tuple | list | None = None) -> list[dict]:
        """查询多条记录, 返回 dict 列表"""
        conn = await self._connect()
        try:
            cursor = await conn.execute(sql, params or [])
            rows = await cursor.fetchall()
            await cursor.close()
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    async def fetchone(self, sql: str, params: tuple | list | None = None) -> dict | None:
        """查询单条记录, 返回 dict 或 None"""
        conn = await self._connect()
        try:
            cursor = await conn.execute(sql, params or [])
            row = await cursor.fetchone()
            await cursor.close()
            return dict(row) if row else None
        finally:
            await conn.close()

    async def fetchval(self, sql: str, params: tuple | list | None = None):
        """查询单个值 (第一行第一列)"""
        conn = await self._connect()
        try:
            cursor = await conn.execute(sql, params or [])
            row = await cursor.fetchone()
            await cursor.close()
            return row[0] if row else None
        finally:
            await conn.close()

    async def transaction(
        self,
        operation: Callable[[aiosqlite.Connection], Awaitable[T]],
    ) -> T:
        """在一个固定连接和一个短事务中执行异步操作。

        operation 应直接使用传入连接，不得另开连接。
        解析、Embedding、Milvus 等耗时或外部操作也不得放入这里。
        """
        conn = await self._connect()
        try:
            await conn.execute("BEGIN IMMEDIATE")
            result = await operation(conn)
            await conn.commit()
            return result
        except BaseException:
            await conn.rollback()
            raise
        finally:
            await conn.close()


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

CREATE INDEX IF NOT EXISTS idx_documents_user_updated
ON documents(user_id, updated_at DESC);

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

    async def get_many(self, document_ids: list[str]) -> list[Document]:
        if not document_ids:
            return []
        placeholders = ", ".join("?" for _ in document_ids)
        rows = await self._db.fetchall(
            f"SELECT * FROM documents WHERE document_id IN ({placeholders})",
            tuple(document_ids),
        )
        by_id = {row["document_id"]: self._row_to_doc(row) for row in rows}
        return [by_id[doc_id] for doc_id in document_ids if doc_id in by_id]

    async def list_by_user(self, user_id: str) -> list[Document]:
        rows = await self._db.fetchall(
            "SELECT * FROM documents WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
        return [self._row_to_doc(r) for r in rows]

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
        clauses = ["user_id = ?"]
        params: list = [user_id]

        if search:
            clauses.append("instr(lower(filename), lower(?)) > 0")
            params.append(search)
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            params.extend(statuses)

        where_clause = " AND ".join(clauses)
        count_row = await self._db.fetchone(
            f"SELECT COUNT(*) AS total FROM documents WHERE {where_clause}",
            tuple(params),
        )
        total = int(count_row["total"]) if count_row else 0
        rows = await self._db.fetchall(
            f"SELECT * FROM documents WHERE {where_clause} "
            "ORDER BY updated_at DESC, document_id DESC LIMIT ? OFFSET ?",
            tuple([*params, limit, offset]),
        )
        return [self._row_to_doc(row) for row in rows], total

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

    async def commit_index(
        self,
        document_id: str,
        chunks: list[ChunkRecord],
        task_id: str | None = None,
    ) -> None:
        """原子替换 Chunk，并将文档（及任务）标记为完成。"""
        now = _now()
        rows = [
            (c.chunk_id, c.document_id, c.user_id,
             c.chunk_index, c.chunk_hash, c.text,
             c.page_start, c.page_end,
             _json_list(c.sections), _json_dict(c.metadata),
             now)
            for c in chunks
        ]

        async def _commit(conn: aiosqlite.Connection) -> None:
            await conn.execute(
                "DELETE FROM chunks WHERE document_id = ?", (document_id,),
            )
            if rows:
                await conn.executemany(
                    "INSERT INTO chunks (chunk_id, document_id, user_id, "
                    "chunk_index, chunk_hash, text, page_start, page_end, "
                    "sections, metadata, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
            cursor = await conn.execute(
                "UPDATE documents SET status = 'indexed', chunk_count = ?, "
                "error_message = NULL, updated_at = ? WHERE document_id = ?",
                (len(chunks), now, document_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"文档不存在: {document_id}")
            await cursor.close()
            if task_id:
                await conn.execute(
                    "UPDATE tasks SET status = 'done', progress = 1.0, "
                    "error_message = NULL, updated_at = ? WHERE task_id = ?",
                    (now, task_id),
                )

        await self._db.transaction(_commit)

    async def fail_index(
        self,
        document_id: str,
        task_id: str | None,
        error_message: str,
        document_status: str = "failed",
    ) -> None:
        """原子清理 SQLite 中间结果，并记录失败状态。"""
        if document_status not in {"failed", "cleanup_pending"}:
            raise ValueError(f"无效的文档失败状态: {document_status}")
        now = _now()

        async def _fail(conn: aiosqlite.Connection) -> None:
            await conn.execute(
                "DELETE FROM chunks WHERE document_id = ?", (document_id,),
            )
            await conn.execute(
                "UPDATE documents SET status = ?, chunk_count = 0, "
                "error_message = ?, updated_at = ? WHERE document_id = ?",
                (document_status, error_message, now, document_id),
            )
            if task_id:
                await conn.execute(
                    "UPDATE tasks SET status = 'failed', progress = 0.0, "
                    "error_message = ?, updated_at = ? WHERE task_id = ?",
                    (error_message, now, task_id),
                )

        await self._db.transaction(_fail)

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

    async def get_many(self, task_ids: list[str]) -> list[TaskRecord]:
        if not task_ids:
            return []
        placeholders = ", ".join("?" for _ in task_ids)
        rows = await self._db.fetchall(
            f"SELECT * FROM tasks WHERE task_id IN ({placeholders})",
            tuple(task_ids),
        )
        by_id = {
            row["task_id"]: TaskRecord(
                task_id=row["task_id"], document_id=row["document_id"],
                status=row["status"], progress=row["progress"],
                error_message=row["error_message"],
                created_at=_parse_dt(row["created_at"]),
                updated_at=_parse_dt(row["updated_at"]),
            )
            for row in rows
        }
        return [by_id[task_id] for task_id in task_ids if task_id in by_id]

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

    async def list_incomplete(self) -> list[TaskRecord]:
        rows = await self._db.fetchall(
            "SELECT task.* FROM tasks AS task "
            "LEFT JOIN documents AS document "
            "ON document.document_id = task.document_id "
            "WHERE task.status NOT IN ('done', 'failed') "
            "OR document.status IN ('indexed', 'cleanup_pending') "
            "ORDER BY task.created_at",
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
