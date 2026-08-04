"""文档相关错误码 — 复用 AppError"""

from ..exceptions import AppError


class UnsupportedFormatError(AppError):
    def __init__(self, filename: str, mime: str):
        super().__init__(
            code="UNSUPPORTED_FORMAT",
            message=f"不支持的文件格式: {filename} ({mime})",
            status_code=400,
        )


class FileTooLargeError(AppError):
    def __init__(self, size: int, max_size: int):
        super().__init__(
            code="FILE_TOO_LARGE",
            message=f"文件大小 {size} 超过限制 {max_size}",
            status_code=413,
        )


class MimeMismatchError(AppError):
    def __init__(self, ext: str, mime: str):
        super().__init__(
            code="MIME_MISMATCH",
            message=f"文件扩展名 {ext} 与 MIME 类型 {mime} 不一致",
            status_code=400,
        )


class DuplicateDocumentError(AppError):
    def __init__(self, filename: str):
        super().__init__(
            code="DUPLICATE_DOCUMENT",
            message=f"相同文件已存在: {filename}",
            status_code=409,
        )


class DocumentNotReadyError(AppError):
    def __init__(self, document_id: str, status: str):
        super().__init__(
            code="DOCUMENT_NOT_READY",
            message=f"文档仍在处理中: {status}",
            status_code=409,
        )
