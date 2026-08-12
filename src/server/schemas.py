"""Pydantic v2 请求/响应模型"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# 身份
# ═══════════════════════════════════════════════════════════════

class CreateUserRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    role: Literal["user", "admin"] = "user"


class CreateApiKeyRequest(BaseModel):
    user_id: str = Field(min_length=1)


class ApiKeyResponse(BaseModel):
    key: str
    prefix: str
    created_at: datetime


class ApiKeyInfo(BaseModel):
    """API Key 信息 (不含原始 Key — 仅展示用)"""
    prefix: str
    user_id: str
    created_at: datetime
    revoked_at: datetime | None = None


class UserResponse(BaseModel):
    user_id: str
    name: str
    role: str
    created_at: datetime


class MeResponse(BaseModel):
    user_id: str
    name: str
    role: str
    api_key_prefix: str


# ═══════════════════════════════════════════════════════════════
# 会话
# ═══════════════════════════════════════════════════════════════

class CreateSessionRequest(BaseModel):
    session_type: Literal["chat", "multi_agent"]
    title: str | None = Field(default=None, max_length=200)


class UpdateSessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class SessionResponse(BaseModel):
    session_id: str
    session_type: Literal["chat", "multi_agent"]
    title: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime


class MessageView(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


# ═══════════════════════════════════════════════════════════════
# 问答
# ═══════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    knowledge_scope: Literal["private", "shared", "hybrid"] = "hybrid"


class Citation(BaseModel):
    index: int
    document_name: str
    scope: Literal["private", "shared"]
    page: int | None = None
    section: str | None = None
    text_snippet: str


class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    citations: list[Citation] = []
    token_usage: TokenUsage | None = None


# ═══════════════════════════════════════════════════════════════
# 文档
# ═══════════════════════════════════════════════════════════════

class DocumentResponse(BaseModel):
    document_id: str
    filename: str
    mime_type: str
    file_size: int
    scope: str
    status: str
    chunk_count: int = 0
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentPageResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    mime_type: str
    file_size: int
    scope: str
    status: str
    task_id: str
    created_at: datetime


class DocumentBatchUploadItemResponse(BaseModel):
    filename: str
    success: bool
    document: DocumentUploadResponse | None = None
    error_code: str | None = None
    error_message: str | None = None


class DocumentBatchUploadResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[DocumentBatchUploadItemResponse]


class TaskResponse(BaseModel):
    task_id: str
    document_id: str
    status: str
    progress: float
    error_message: str | None
    created_at: datetime
    updated_at: datetime


# ═══════════════════════════════════════════════════════════════
# 错误
# ═══════════════════════════════════════════════════════════════

class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    error: ErrorDetail
