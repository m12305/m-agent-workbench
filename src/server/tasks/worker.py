"""TaskWorker — 编排完整的 解析→分块→Embedding→Milvus 写入 管线"""

import os
import asyncio
import time
import tempfile
import logging

from ..repositories.base import (
    DocumentRepository, ChunkRepository, ChunkRecord,
)

logger = logging.getLogger("server.task_worker")


class TaskWorker:
    """文档索引管线编排器。

    管线步骤:
      1. 获取文件 (OSS → 临时文件, Local → 直接路径)
      2. 解析: Parser.parse() → ParsedDocument
      3. 分块: ChunkingStrategy.chunk() → list[Chunk]
      4. Embedding: EmbeddingService.embed() → 每个 Chunk 追加向量
      5. Milvus: 批量写入向量 Collection
      6. SQLite: 保存 ChunkRecord
      7. 更新文档状态 → "indexed"
    """

    def __init__(
        self,
        doc_repo: DocumentRepository,
        chunk_repo: ChunkRepository,
        storage,
        parser_registry,
        chunker_registry,
        embedding_service,
        milvus_client,
    ):
        self._doc_repo = doc_repo
        self._chunk_repo = chunk_repo
        self._storage = storage
        self._parser_registry = parser_registry
        self._chunker_registry = chunker_registry
        self._embedding = embedding_service
        self._milvus = milvus_client

    async def execute(self, document_id: str):
        doc = await self._doc_repo.get(document_id)
        if not doc:
            raise ValueError(f"文档不存在: {document_id}")

        # ---- 1. 获取文件路径 ----
        file_path = self._storage.resolve_path(doc.storage_key)
        cleanup_temp = False
        if file_path is None:
            content = await self._storage.read(doc.storage_key)
            ext = doc.filename.rsplit(".", 1)[-1] if "." in doc.filename else ""
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
                f.write(content)
            file_path = f.name
            cleanup_temp = True

        try:
            # ---- 2. 解析 ----
            await self._doc_repo.update(document_id, status="parsing")
            parser = self._parser_registry.select(doc.mime_type, doc.filename)
            parsed = await asyncio.to_thread(
                parser.parse, file_path, doc.filename, doc.mime_type,
            )

            # ---- 3. 分块 ----
            await self._doc_repo.update(document_id, status="chunking")
            chunker = self._chunker_registry.get(doc.mime_type)
            chunks = chunker.chunk(parsed, document_id)

            if not chunks:
                logger.warning("文档 %s 未产生任何 Chunk", document_id)
                await self._doc_repo.update(
                    document_id, status="indexed", chunk_count=0,
                )
                return

            # ---- 4. Embedding ----
            await self._doc_repo.update(document_id, status="embedding")
            chunk_texts = [c.text for c in chunks]
            embed_results = await self._embedding.embed(chunk_texts)

            # 将向量附加到 Chunk metadata
            for er in embed_results:
                chunks[er.index].metadata["embedding"] = er.vector
                chunks[er.index].metadata["embedding_model"] = self._embedding.model_name

            logger.debug("Embedding 完成: %d 条", len(embed_results))

            # ---- 5. Milvus 写入 ----
            milvus_rows = []
            now_ts = int(time.time())
            # 确定 Milvus 分区键: private→实际user, shared→公共分区""
            milvus_user_id = doc.user_id if doc.scope == "private" else ""
            for c in chunks:
                milvus_rows.append({
                    "chunk_id": c.chunk_id,
                    "document_id": c.document_id,
                    "chunk_index": c.chunk_index,
                    "chunk_hash": c.chunk_hash,
                    "scope": doc.scope,
                    "user_id": milvus_user_id,
                    "text": c.text,
                    "source_name": doc.filename,
                    "page_start": c.page_start,
                    "page_end": c.page_end,
                    "sections": c.sections,
                    "embedding": c.metadata.get("embedding", []),
                    "created_at": now_ts,
                })

            # 分批写入 Milvus (每批 100 条)
            BATCH = 100
            for i in range(0, len(milvus_rows), BATCH):
                batch = milvus_rows[i:i + BATCH]
                self._milvus.insert(batch)

            logger.info("Milvus 写入完成: %d 条", len(milvus_rows))

            # ---- 6. SQLite 保存 ChunkRecord ----
            records = [
                ChunkRecord(
                    chunk_id=c.chunk_id,
                    document_id=c.document_id,
                    user_id=doc.user_id,  # 记录实际上传者，用于审计
                    chunk_index=c.chunk_index,
                    chunk_hash=c.chunk_hash,
                    text=c.text,
                    page_start=c.page_start,
                    page_end=c.page_end,
                    sections=c.sections,
                    metadata=c.metadata,
                )
                for c in chunks
            ]
            await self._chunk_repo.batch_save(records)

            # ---- 7. 更新文档状态 ----
            await self._doc_repo.update(
                document_id, status="indexed", chunk_count=len(chunks),
            )
            logger.info("文档索引完成: %s (%d chunks)", document_id, len(chunks))

        finally:
            if cleanup_temp:
                try:
                    os.unlink(file_path)
                except OSError:
                    pass
