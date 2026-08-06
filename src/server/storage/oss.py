"""AliyunOSSStorage — 阿里云 OSS 对象存储

支持:
  - 简单上传 (≤5 GB, 小文件推荐)
  - 分片上传 (大文件, 100KB~5GB/分片, 最多 10000 片, 支持并发)
  - 断点续传 (基于 checkpoint 文件, 网络中断后可从断点恢复)
  - 预签名 URL (用于外部访问, 如 MinerU 回调下载)
"""

import os
import json
import uuid
import hashlib
import logging
import asyncio
from typing import BinaryIO

from .base import MultipartUpload, UploadPart, ResumableCheckpoint

logger = logging.getLogger("server.storage.oss")

# 默认分片大小: 5MB (OSS 要求最小 100KB)
DEFAULT_PART_SIZE = 5 * 1024 * 1024


class AliyunOSSStorage:
    """阿里云 OSS 存储 — 基于 alibabacloud_oss_v2 SDK"""

    def __init__(
        self,
        endpoint: str,
        bucket_name: str,
        access_key_id: str,
        access_key_secret: str,
        region: str = "",
    ):
        self._endpoint = endpoint
        self._bucket_name = bucket_name
        self._region = region
        self._client = None
        self._access_key_id = access_key_id
        self._access_key_secret = access_key_secret

    # ------------------------------------------------------------------
    # 延迟初始化
    # ------------------------------------------------------------------

    @property
    def client(self):
        """延迟创建 OSS 客户端 (首次使用时导入 SDK)"""
        if self._client is None:
            import alibabacloud_oss_v2 as oss

            creds = oss.credentials.StaticCredentialsProvider(
                access_key_id=self._access_key_id,
                access_key_secret=self._access_key_secret,
            )
            cfg = oss.config.load_default()
            cfg.credentials_provider = creds
            cfg.endpoint = self._endpoint
            if self._region:
                cfg.region = self._region

            self._client = oss.Client(cfg)
            logger.info("OSS 客户端已初始化: endpoint=%s, bucket=%s",
                         self._endpoint, self._bucket_name)
        return self._client

    # ------------------------------------------------------------------
    # 基础操作
    # ------------------------------------------------------------------

    async def save(self, content: bytes, extension: str) -> str:
        """简单上传 — 适用于小文件 (≤5 GB)"""
        key = self._make_key(extension)
        import alibabacloud_oss_v2 as oss

        await asyncio.to_thread(
            self.client.put_object,
            oss.PutObjectRequest(
                bucket=self._bucket_name,
                key=key,
                body=content,
            ),
        )
        logger.debug("OSS 简单上传完成: key=%s, size=%d", key, len(content))
        return key

    async def read(self, key: str) -> bytes:
        """读取文件内容"""
        import alibabacloud_oss_v2 as oss

        result = await asyncio.to_thread(
            self.client.get_object,
            oss.GetObjectRequest(
                bucket=self._bucket_name,
                key=key,
            ),
        )
        return await asyncio.to_thread(result.body.read)

    async def delete(self, key: str) -> None:
        """删除文件 (幂等)"""
        import alibabacloud_oss_v2 as oss

        # 删除不存在对象本身是幂等成功；网络/鉴权错误必须向上抛出，
        # 让摄取补偿流程记录 cleanup_pending 并在启动时重试。
        await asyncio.to_thread(
            self.client.delete_object,
            oss.DeleteObjectRequest(
                bucket=self._bucket_name,
                key=key,
            ),
        )

    async def exists(self, key: str) -> bool:
        """检查文件是否存在"""
        import alibabacloud_oss_v2 as oss

        try:
            await asyncio.to_thread(
                self.client.head_object,
                oss.HeadObjectRequest(
                    bucket=self._bucket_name,
                    key=key,
                ),
            )
            return True
        except Exception:
            return False

    def resolve_path(self, key: str) -> str | None:
        """OSS 无法返回本地路径"""
        return None

    # ------------------------------------------------------------------
    # 外部访问
    # ------------------------------------------------------------------

    def presigned_url(self, key: str, expires: int = 3600) -> str | None:
        """生成预签名下载 URL。
        用于 MinerU 等外部服务回调下载文件。
        URL 在 expires 秒后失效。

        实现方式: 使用 OSS SDK v2 的签名能力构造带签名的 URL。
        """
        import alibabacloud_oss_v2 as oss

        try:
            # 方式 1: 使用 SDK 内置 Presigner
            from alibabacloud_oss_v2.presigner import Presigner

            signer = Presigner(self.client)
            result = signer.presign(
                method="GET",
                bucket=self._bucket_name,
                key=key,
                expiration=expires,
            )
            return result.url
        except (ImportError, AttributeError):
            pass

        try:
            # 方式 2: 手动构造预签名 URL
            # OSS 签名 URL 格式: {endpoint}/{bucket}/{key}?签名参数
            # SDK v2 内部有签名器可用
            from alibabacloud_oss_v2.auth import SignerV4

            # 构造请求并签名
            req = oss.GetObjectRequest(bucket=self._bucket_name, key=key)
            # 利用 SDK 内部机制生成带签名的 URL
            # 不同版本的 SDK 接口可能略有差异
            raise NotImplementedError(
                "当前 OSS SDK 版本不支持自动 presign，请升级 SDK 或使用 "
                "alibabacloud_oss_v2 >= 1.0.0"
            )
        except NotImplementedError:
            raise
        except Exception:
            logger.warning("无法生成预签名 URL，将返回未签名 URL (需要公共读权限)")
            return f"{self._endpoint}/{self._bucket_name}/{key}"

    # ------------------------------------------------------------------
    # 分片上传
    # ------------------------------------------------------------------

    def initiate_multipart_upload(self, key: str) -> MultipartUpload:
        """初始化分片上传任务。
        返回 MultipartUpload 句柄，其中 upload_id 用于后续操作。
        """
        import alibabacloud_oss_v2 as oss

        result = self.client.initiate_multipart_upload(
            oss.InitiateMultipartUploadRequest(
                bucket=self._bucket_name,
                key=key,
            )
        )
        logger.info("分片上传已初始化: key=%s, upload_id=%s",
                     key, result.upload_id)
        return MultipartUpload(
            upload_id=result.upload_id,
            key=key,
            part_size=DEFAULT_PART_SIZE,
        )

    def upload_part(self, key: str, upload_id: str, part_number: int,
                    data: bytes) -> UploadPart:
        """上传单个分片。
        分片大小需 ≥100KB (最后一个分片除外)。
        """
        import alibabacloud_oss_v2 as oss

        result = self.client.upload_part(
            oss.UploadPartRequest(
                bucket=self._bucket_name,
                key=key,
                upload_id=upload_id,
                part_number=part_number,
                body=data,
            )
        )
        logger.debug("分片上传完成: key=%s, part=%d, etag=%s, size=%d",
                      key, part_number, result.etag, len(data))
        return UploadPart(
            part_number=part_number,
            etag=result.etag,
            size=len(data),
        )

    def complete_multipart_upload(self, upload: MultipartUpload) -> str:
        """合并所有分片，完成上传。
        分片列表按 part_number 升序排列后提交。
        返回最终 key。
        """
        import alibabacloud_oss_v2 as oss

        parts = sorted(upload.uploaded_parts, key=lambda p: p.part_number)
        result = self.client.complete_multipart_upload(
            oss.CompleteMultipartUploadRequest(
                bucket=self._bucket_name,
                key=upload.key,
                upload_id=upload.upload_id,
                complete_multipart_upload=oss.CompleteMultipartUpload(
                    parts=[
                        oss.UploadPart(part_number=p.part_number, etag=p.etag)
                        for p in parts
                    ]
                ),
            )
        )
        logger.info("分片上传合并完成: key=%s, upload_id=%s, parts=%d",
                     upload.key, upload.upload_id, len(parts))
        return result.key

    def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        """取消分片上传，删除已上传的所有分片。
        避免碎片文件持续产生存储费用。
        """
        import alibabacloud_oss_v2 as oss

        try:
            self.client.abort_multipart_upload(
                oss.AbortMultipartUploadRequest(
                    bucket=self._bucket_name,
                    key=key,
                    upload_id=upload_id,
                )
            )
            logger.info("分片上传已取消: key=%s, upload_id=%s", key, upload_id)
        except Exception as e:
            logger.warning("取消分片上传失败: %s", e)

    def list_parts(self, key: str, upload_id: str) -> list[UploadPart]:
        """列出已上传的分片，用于断点续传时恢复进度。
        最多返回 1000 个分片 (单次请求限制)。
        """
        import alibabacloud_oss_v2 as oss

        uploaded = []
        next_marker = None

        while True:
            request = oss.ListPartsRequest(
                bucket=self._bucket_name,
                key=key,
                upload_id=upload_id,
            )
            if next_marker:
                request.part_number_marker = next_marker

            result = self.client.list_parts(request)

            for p in result.parts or []:
                uploaded.append(UploadPart(
                    part_number=p.part_number,
                    etag=p.etag,
                    size=p.size or 0,
                ))

            if result.is_truncated:
                next_marker = result.next_part_number_marker
            else:
                break

        return uploaded

    # ------------------------------------------------------------------
    # 断点续传
    # ------------------------------------------------------------------

    def resumable_upload(
        self,
        file_path: str,
        key: str,
        part_size: int = DEFAULT_PART_SIZE,
        checkpoint_file: str | None = None,
    ) -> str:
        """断点续传上传大文件。

        工作流程:
        1. 检查是否存在 checkpoint 文件 → 有则恢复进度
        2. 如无 checkpoint 或 upload_id 已失效 → 重新初始化
        3. 检查已上传分片 → 跳过已完成的分片
        4. 逐片上传剩余分片 → 每片完成后更新 checkpoint
        5. 全部完成后合并 → 删除 checkpoint

        Args:
            file_path: 本地文件路径
            key: OSS 对象 key
            part_size: 分片大小 (字节)，默认 5MB
            checkpoint_file: checkpoint 文件路径，默认 {file_path}.oss_checkpoint

        Returns:
            最终的 OSS key
        """
        if checkpoint_file is None:
            checkpoint_file = file_path + ".oss_checkpoint"

        file_size = os.path.getsize(file_path)
        total_parts = (file_size + part_size - 1) // part_size
        upload = None

        # ---- 1. 尝试从 checkpoint 恢复 ----
        if os.path.exists(checkpoint_file):
            try:
                ck = self._load_checkpoint(checkpoint_file)
                # 验证 checkpoint 有效性
                if (ck.file_path == file_path
                        and ck.file_size == file_size
                        and ck.part_size == part_size
                        and ck.key == key):
                    upload = MultipartUpload(
                        upload_id=ck.upload_id,
                        key=key,
                        part_size=part_size,
                        uploaded_parts=ck.uploaded_parts,
                    )
                    # 从 OSS 端确认哪些分片已上传 (防御本地 checkpoint 过期)
                    remote_parts = self.list_parts(key, upload.upload_id)
                    remote_dict = {p.part_number: p for p in remote_parts}
                    # 合并: checkpoint 中已有的 + OSS 端确认的
                    merged = {}
                    for p in ck.uploaded_parts:
                        merged[p.part_number] = p
                    for p in remote_parts:
                        merged[p.part_number] = p
                    upload.uploaded_parts = sorted(
                        merged.values(), key=lambda p: p.part_number
                    )
                    logger.info("从 checkpoint 恢复: upload_id=%s, "
                                 "已完成 %d/%d 分片",
                                 upload.upload_id,
                                 len(upload.uploaded_parts), total_parts)
                else:
                    logger.warning("checkpoint 文件不匹配，将重新初始化")
                    upload = None
            except Exception as e:
                logger.warning("checkpoint 文件损坏 (%s)，将重新初始化", e)
                upload = None

        # ---- 2. 初始化新上传 ----
        if upload is None:
            upload = self.initiate_multipart_upload(key)
            upload.part_size = part_size

        # ---- 3. 上传分片 ----
        completed_numbers = {p.part_number for p in upload.uploaded_parts}
        logger.info("开始断点续传: key=%s, parts=%d, part_size=%d, "
                     "已完成=%d",
                     key, total_parts, part_size, len(completed_numbers))

        try:
            with open(file_path, "rb") as f:
                for part_number in range(1, total_parts + 1):
                    if part_number in completed_numbers:
                        continue

                    # 计算分片偏移和大小
                    offset = (part_number - 1) * part_size
                    f.seek(offset)
                    data = f.read(part_size)

                    # 上传分片
                    part = self.upload_part(
                        key, upload.upload_id, part_number, data
                    )
                    upload.uploaded_parts.append(part)
                    completed_numbers.add(part_number)

                    # 保存 checkpoint
                    self._save_checkpoint(
                        checkpoint_file, upload.upload_id,
                        file_path, file_size, part_size,
                        upload.uploaded_parts,
                    )

                    if part_number % 10 == 0 or part_number == total_parts:
                        logger.info("断点续传进度: %d/%d 分片",
                                     part_number, total_parts)

        except Exception:
            # 异常时保留 checkpoint，下次可从中断处恢复
            logger.warning("断点续传中断: key=%s, 已完成=%d/%d, "
                            "checkpoint 已保存",
                            key, len(completed_numbers), total_parts)
            raise

        # ---- 4. 合并分片 ----
        result_key = self.complete_multipart_upload(upload)

        # ---- 5. 清理 checkpoint ----
        self._clean_checkpoint(checkpoint_file)
        logger.info("断点续传完成: key=%s, file=%s, size=%d",
                     result_key, file_path, file_size)

        return result_key

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _make_key(extension: str) -> str:
        """生成三层桶结构 key: {xx}/{yy}/{uuid}.{ext}"""
        bucket1 = str(uuid.uuid4())[:2]
        bucket2 = str(uuid.uuid4())[:2]
        file_id = str(uuid.uuid4())
        ext = extension.lstrip(".")
        return f"{bucket1}/{bucket2}/{file_id}.{ext}"

    @staticmethod
    def _load_checkpoint(path: str) -> ResumableCheckpoint:
        """从 JSON 文件加载断点"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ResumableCheckpoint(
            upload_id=data["upload_id"],
            key=data["key"],
            file_path=data["file_path"],
            file_size=data["file_size"],
            part_size=data["part_size"],
            uploaded_parts=[
                UploadPart(
                    part_number=p["part_number"],
                    etag=p["etag"],
                    size=p.get("size", 0),
                )
                for p in data.get("uploaded_parts", [])
            ],
        )

    @staticmethod
    def _save_checkpoint(
        path: str,
        upload_id: str,
        file_path: str,
        file_size: int,
        part_size: int,
        uploaded_parts: list[UploadPart],
        key: str = "",
    ):
        """保存断点 checkpoint 到 JSON 文件"""
        data = {
            "upload_id": upload_id,
            "key": key,
            "file_path": file_path,
            "file_size": file_size,
            "part_size": part_size,
            "uploaded_parts": [
                {
                    "part_number": p.part_number,
                    "etag": p.etag,
                    "size": p.size,
                }
                for p in uploaded_parts
            ],
        }
        # 原子写入: 先写临时文件，再 rename
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)

    @staticmethod
    def _clean_checkpoint(path: str):
        """删除断点文件"""
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
