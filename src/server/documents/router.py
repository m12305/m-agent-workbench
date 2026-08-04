"""文档管理 API 路由"""

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse

from ..deps import get_identity
from ..repositories.base import Identity
from ..schemas import DocumentResponse, DocumentUploadResponse, TaskResponse
from .service import DocumentService
from .errors import FileTooLargeError

logger = logging.getLogger("server.document_api")
router = APIRouter()

MAX_UPLOAD_SIZE = 20 * 1024 * 1024


def get_doc_service(request: Request) -> DocumentService:
    return request.app.state.doc_service


@router.post("/documents", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    scope: str = Form("private"),
    identity: Identity = Depends(get_identity),
    doc_service: DocumentService = Depends(get_doc_service),
):
    """上传文档"""
    if not file.filename:
        from .errors import UnsupportedFormatError
        raise UnsupportedFormatError("unknown", "unknown")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ("txt", "md", "pdf"):
        from .errors import UnsupportedFormatError
        raise UnsupportedFormatError(file.filename, f".{ext}")

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise FileTooLargeError(len(content), MAX_UPLOAD_SIZE)

    import magic
    detected_mime = magic.from_buffer(content[:2048], mime=True)

    if scope == "shared" and identity.role != "admin":
        scope = "private"

    result = await doc_service.upload(
        identity=identity,
        filename=file.filename,
        content=content,
        mime_type=detected_mime,
        scope=scope,
    )
    return DocumentUploadResponse(**result)


@router.get("/documents", response_model=list[DocumentResponse])
async def list_documents(
    identity: Identity = Depends(get_identity),
    doc_service: DocumentService = Depends(get_doc_service),
):
    """列出当前用户的文档"""
    docs = await doc_service.list_documents(identity.user_id)
    return [
        DocumentResponse(
            document_id=d.document_id,
            filename=d.filename,
            mime_type=d.mime_type,
            file_size=d.file_size,
            scope=d.scope,
            status=d.status,
            chunk_count=d.chunk_count,
            error_message=d.error_message,
            created_at=d.created_at,
            updated_at=d.updated_at,
        )
        for d in docs
    ]


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    identity: Identity = Depends(get_identity),
    doc_service: DocumentService = Depends(get_doc_service),
):
    """获取文档详情"""
    from ..exceptions import NotFoundError
    doc = await doc_service.get_document(document_id)
    if not doc or doc.user_id != identity.user_id:
        raise NotFoundError("文档", document_id)
    return DocumentResponse(
        document_id=doc.document_id,
        filename=doc.filename,
        mime_type=doc.mime_type,
        file_size=doc.file_size,
        scope=doc.scope,
        status=doc.status,
        chunk_count=doc.chunk_count,
        error_message=doc.error_message,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: str,
    request: Request,
    identity: Identity = Depends(get_identity),
    doc_service: DocumentService = Depends(get_doc_service),
):
    """下载原始文件"""
    from ..exceptions import NotFoundError
    doc = await doc_service.get_document(document_id)
    if not doc or doc.user_id != identity.user_id:
        raise NotFoundError("文档", document_id)

    storage = request.app.state.storage
    content = await storage.read(doc.storage_key)

    return StreamingResponse(
        iter([content]),
        media_type=doc.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(doc.filename, safe='')}"
            ),
        },
    )


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    identity: Identity = Depends(get_identity),
    doc_service: DocumentService = Depends(get_doc_service),
):
    """删除文档"""
    await doc_service.delete_document(identity.user_id, document_id)


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    doc_service: DocumentService = Depends(get_doc_service),
):
    """查询索引任务进度"""
    task = await doc_service._task_queue.get(task_id)
    if not task:
        from ..exceptions import NotFoundError
        raise NotFoundError("任务", task_id)
    return TaskResponse(
        task_id=task.task_id,
        document_id=task.document_id,
        status=task.status,
        progress=task.progress,
        error_message=task.error_message,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
