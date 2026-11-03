import logging
import threading
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import anyio
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    pass


class ObjectStorage(Protocol):
    async def put(self, *, object_key: str, data: bytes, content_type: str) -> None: ...

    async def delete(self, *, object_key: str) -> None: ...


class LocalObjectStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def put(self, *, object_key: str, data: bytes, content_type: str) -> None:
        await anyio.to_thread.run_sync(self._put, object_key, data)

    async def delete(self, *, object_key: str) -> None:
        await anyio.to_thread.run_sync(self._delete, object_key)

    def _path(self, object_key: str) -> Path:
        path = (self._root / object_key).resolve()
        if not path.is_relative_to(self._root):
            raise StorageError("object key escapes storage root")
        return path

    def _put(self, object_key: str, data: bytes) -> None:
        try:
            path = self._path(object_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError as exc:
            raise StorageError(f"failed to store object: {exc}") from exc

    def _delete(self, object_key: str) -> None:
        try:
            self._path(object_key).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(f"failed to delete object: {exc}") from exc


class S3ObjectStorage:
    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key: str | None,
        secret_key: str | None,
        region: str,
    ) -> None:
        self._bucket = bucket
        self._region = region
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self._bucket_ready = False
        self._lock = threading.Lock()

    async def put(self, *, object_key: str, data: bytes, content_type: str) -> None:
        await anyio.to_thread.run_sync(self._put, object_key, data, content_type)

    async def delete(self, *, object_key: str) -> None:
        await anyio.to_thread.run_sync(self._delete, object_key)

    def _ensure_bucket(self) -> None:
        with self._lock:
            if self._bucket_ready:
                return
            try:
                self._client.head_bucket(Bucket=self._bucket)
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code not in {"404", "NoSuchBucket", "NotFound"}:
                    raise StorageError(f"failed to access bucket: {exc}") from exc
                create_kwargs: dict[str, object] = {"Bucket": self._bucket}
                if self._region != "us-east-1":
                    create_kwargs["CreateBucketConfiguration"] = {
                        "LocationConstraint": self._region
                    }
                self._client.create_bucket(**create_kwargs)
            self._bucket_ready = True

    def _put(self, object_key: str, data: bytes, content_type: str) -> None:
        try:
            self._ensure_bucket()
            self._client.put_object(
                Bucket=self._bucket,
                Key=object_key,
                Body=data,
                ContentType=content_type,
            )
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"failed to store object: {exc}") from exc

    def _delete(self, object_key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=object_key)
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"failed to delete object: {exc}") from exc


@lru_cache
def get_storage() -> ObjectStorage:
    if settings.s3_endpoint and settings.s3_bucket:
        return S3ObjectStorage(
            endpoint=settings.s3_endpoint,
            bucket=settings.s3_bucket,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            region=settings.s3_region,
        )
    return LocalObjectStorage(Path(settings.upload_dir))


__all__ = [
    "LocalObjectStorage",
    "ObjectStorage",
    "S3ObjectStorage",
    "StorageError",
    "get_storage",
]
