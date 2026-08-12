"""对象存储 — 协议 + 本地 + OSS"""
from .base import (
    ObjectStorage,
    UploadPart,
    MultipartUpload,
    ResumableCheckpoint,
)
from .local import LocalStorage
from .oss import AliyunOSSStorage


def create_storage() -> ObjectStorage:
    import os
    backend = os.getenv("STORAGE_BACKEND", "local")
    if backend == "oss":
        return AliyunOSSStorage(
            endpoint=os.getenv("OSS_ENDPOINT", ""),
            bucket_name=os.getenv("OSS_BUCKET_NAME", ""),
            access_key_id=os.getenv("OSS_ACCESS_KEY_ID", ""),
            access_key_secret=os.getenv("OSS_ACCESS_KEY_SECRET", ""),
            region=os.getenv("OSS_REGION", ""),
        )
    return LocalStorage(
        base_dir=os.getenv("STORAGE_LOCAL_DIR", "./storage/files")
    )


__all__ = [
    "ObjectStorage",
    "UploadPart",
    "MultipartUpload",
    "ResumableCheckpoint",
    "LocalStorage",
    "AliyunOSSStorage",
    "create_storage",
]
