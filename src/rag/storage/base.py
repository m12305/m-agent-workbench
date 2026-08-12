"""ObjectStorage 协议定义"""

from dataclasses import dataclass, field
from typing import Protocol


# ═══════════════════════════════════════════════════════════════
# 分片上传相关类型
# ═══════════════════════════════════════════════════════════════

@dataclass
class UploadPart:
    """单个分片信息"""
    part_number: int
    etag: str
    size: int = 0


@dataclass
class MultipartUpload:
    """分片上传任务句柄"""
    upload_id: str
    key: str
    part_size: int = 5 * 1024 * 1024  # 默认 5MB
    uploaded_parts: list[UploadPart] = field(default_factory=list)


@dataclass
class ResumableCheckpoint:
    """断点续传检查点 — 可序列化到磁盘"""
    upload_id: str
    key: str
    file_path: str
    file_size: int
    part_size: int
    uploaded_parts: list[UploadPart] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# 协议
# ═══════════════════════════════════════════════════════════════

class ObjectStorage(Protocol):
    """对象存储协议 — 本地 / OSS 双实现"""

    # ---- 基础操作 ----

    async def save(self, content: bytes, extension: str) -> str:
        """保存文件，返回 storage_key"""
        ...

    async def read(self, key: str) -> bytes:
        """读取文件内容"""
        ...

    async def delete(self, key: str) -> None:
        """删除文件 (幂等)"""
        ...

    async def exists(self, key: str) -> bool:
        """检查文件是否存在"""
        ...

    def resolve_path(self, key: str) -> str | None:
        """获取本地文件路径。LocalStorage 返回绝对路径，OSS 返回 None"""
        ...

    # ---- 外部访问 ----

    def presigned_url(self, key: str, expires: int = 3600) -> str | None:
        """生成预签名下载 URL。
        LocalStorage 无法生成外部可访问的 URL，返回 None。
        OSS 返回带签名的临时下载链接。
        """
        ...

    # ---- 大文件分片上传 ----

    def initiate_multipart_upload(self, key: str) -> MultipartUpload:
        """初始化分片上传任务，返回 upload_id"""
        ...

    def upload_part(self, key: str, upload_id: str, part_number: int,
                    data: bytes) -> UploadPart:
        """上传一个分片，返回 etag 等信息"""
        ...

    def complete_multipart_upload(self, upload: MultipartUpload) -> str:
        """合并所有分片，返回最终 key"""
        ...

    def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        """取消分片上传，清理已上传分片"""
        ...

    def list_parts(self, key: str, upload_id: str) -> list[UploadPart]:
        """列出已上传的分片（用于断点续传恢复）"""
        ...

    # ---- 断点续传 ----

    def resumable_upload(self, file_path: str, key: str,
                         part_size: int = 5 * 1024 * 1024,
                         checkpoint_file: str | None = None) -> str:
        """断点续传上传大文件。
        自动处理分片、断点记录、重试。
        返回最终 key。
        """
        ...
