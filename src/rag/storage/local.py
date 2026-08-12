"""LocalStorage — 本地文件系统存储"""

import os
import uuid
import aiofiles
import logging

from .base import MultipartUpload, UploadPart

logger = logging.getLogger("server.storage.local")


class LocalStorage:
    """本地文件存储。
    分片上传/断点续传在本地场景下退化为简单写入。
    """

    def __init__(self, base_dir: str = "./storage/files"):
        self._base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # 基础操作
    # ------------------------------------------------------------------

    def _key_to_path(self, key: str) -> str:
        return os.path.join(self._base_dir, key)

    async def save(self, content: bytes, extension: str) -> str:
        bucket1 = str(uuid.uuid4())[:2]
        bucket2 = str(uuid.uuid4())[:2]
        file_id = str(uuid.uuid4())
        ext = extension.lstrip(".")
        key = f"{bucket1}/{bucket2}/{file_id}.{ext}"

        full_path = self._key_to_path(key)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        async with aiofiles.open(full_path, "wb") as f:
            await f.write(content)

        logger.debug("文件已保存: key=%s, size=%d", key, len(content))
        return key

    async def read(self, key: str) -> bytes:
        full_path = self._key_to_path(key)
        async with aiofiles.open(full_path, "rb") as f:
            return await f.read()

    async def delete(self, key: str) -> None:
        full_path = self._key_to_path(key)
        try:
            os.remove(full_path)
        except FileNotFoundError:
            pass

    async def exists(self, key: str) -> bool:
        return os.path.exists(self._key_to_path(key))

    def resolve_path(self, key: str) -> str:
        return self._key_to_path(key)

    # ------------------------------------------------------------------
    # 外部访问
    # ------------------------------------------------------------------

    def presigned_url(self, key: str, expires: int = 3600) -> str | None:
        """本地存储无法生成外部可访问的 URL"""
        return None

    # ------------------------------------------------------------------
    # 分片上传 (本地退化)
    # ------------------------------------------------------------------

    def initiate_multipart_upload(self, key: str) -> MultipartUpload:
        full_path = self._key_to_path(key)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        return MultipartUpload(upload_id="local", key=key)

    def upload_part(self, key: str, upload_id: str, part_number: int,
                    data: bytes) -> UploadPart:
        full_path = self._key_to_path(key)
        mode = "ab" if part_number > 1 else "wb"
        with open(full_path, mode) as f:
            f.write(data)
        return UploadPart(part_number=part_number, etag="local", size=len(data))

    def complete_multipart_upload(self, upload: MultipartUpload) -> str:
        return upload.key

    def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        try:
            os.remove(self._key_to_path(key))
        except FileNotFoundError:
            pass

    def list_parts(self, key: str, upload_id: str) -> list[UploadPart]:
        full_path = self._key_to_path(key)
        if os.path.exists(full_path):
            size = os.path.getsize(full_path)
            return [UploadPart(part_number=1, etag="local", size=size)]
        return []

    # ------------------------------------------------------------------
    # 断点续传 (本地退化)
    # ------------------------------------------------------------------

    def resumable_upload(self, file_path: str, key: str,
                         part_size: int = 5 * 1024 * 1024,
                         checkpoint_file: str | None = None) -> str:
        """本地断点续传退化为直接拷贝"""
        import shutil
        full_path = self._key_to_path(key)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        shutil.copy2(file_path, full_path)
        logger.debug("文件已拷贝: %s → %s", file_path, key)
        return key
