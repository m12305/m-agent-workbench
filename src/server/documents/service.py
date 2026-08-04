"""文档服务 — 上传、查询、删除"""

import hashlib
import uuid
import logging
from datetime import datetime

from ..milvus import MilvusClient

from ..repositories.base import (
    DocumentRepository, ChunkRepository,
    Document, Identity,
)
from ..tasks.base import TaskQueue
from .errors import (
    UnsupportedFormatError, FileTooLargeError,
    MimeMismatchError, DuplicateDocumentError,
)

logger = logging.getLogger("server.document_service")

ALLOWED_MIMES = {"text/plain", "text/markdown", "application/pdf"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


class DocumentService:

    def __init__(
        self,
        doc_repo: DocumentRepository,
        chunk_repo: ChunkRepository,
        storage,
        task_queue: TaskQueue,
        milvus_client: MilvusClient  # MilvusClient 
    ):
        self._doc_repo = doc_repo
        self._chunk_repo = chunk_repo
        self._storage = storage
        self._task_queue = task_queue
        self._milvus = milvus_client  

    async def upload(
        self, identity: Identity, filename: str,
        content: bytes, mime_type: str, scope: str = "private",
    ) -> dict:
        # 1. 校验
        if mime_type not in ALLOWED_MIMES:
            raise UnsupportedFormatError(filename, mime_type)
        if len(content) > MAX_FILE_SIZE:
            raise FileTooLargeError(len(content), MAX_FILE_SIZE)
        self._validate_extension(filename, mime_type)

        # 2. 去重检查
        file_hash = hashlib.sha256(content).hexdigest()
        existing = await self._doc_repo.list_by_user(identity.user_id)
        for doc in existing:
            if doc.file_hash == file_hash and doc.scope == scope:
                raise DuplicateDocumentError(filename)

        # 3. 存储文件
        ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
        storage_key = await self._storage.save(content, ext)

        # 4. 创建文档记录
        doc = Document(
            document_id=str(uuid.uuid4()),
            user_id=identity.user_id,
            filename=filename,
            storage_key=storage_key,
            mime_type=mime_type,
            file_size=len(content),
            file_hash=file_hash,
            scope=scope,
            status="queued",
        )
        await self._doc_repo.create(doc)

        # 5. 提交索引任务
        task_id = await self._task_queue.enqueue(doc.document_id)

        return {
            "document_id": doc.document_id,
            "filename": doc.filename,
            "mime_type": doc.mime_type,
            "file_size": doc.file_size,
            "scope": doc.scope,
            "status": doc.status,
            "task_id": task_id,
            "created_at": doc.created_at,
        }

    async def get_document(self, document_id: str) -> Document | None:
        return await self._doc_repo.get(document_id)

    async def list_documents(self, user_id: str) -> list[Document]:
        return await self._doc_repo.list_by_user(user_id)

    async def delete_document(self, user_id: str, document_id: str):
        doc = await self._doc_repo.get(document_id)
        if not doc:
            return
        if doc.user_id != user_id:
            from ..exceptions import NotFoundError
            raise NotFoundError("文档", document_id)

        await self._storage.delete(doc.storage_key)
        await self._chunk_repo.delete_by_document(document_id, user_id)
        # 同步清理 Milvus 向量 — 带 user_id 双重校验
        if self._milvus:
            delete_user_id = user_id if doc.scope == "private" else ""
            self._milvus.delete_by_document(document_id, delete_user_id)
        await self._doc_repo.delete(document_id)

    def _validate_extension(self, filename: str, mime: str):
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        ext_mime_map = {
            "txt": "text/plain",
            "md": "text/markdown",
            "pdf": "application/pdf",
        }
        expected = ext_mime_map.get(ext)
        if expected and expected != mime:
            raise MimeMismatchError(f".{ext}", mime)
