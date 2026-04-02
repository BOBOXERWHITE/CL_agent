from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from minio import Minio

from app.core.config import get_settings


@dataclass(frozen=True)
class StoredObject:
    storage_key: str
    size_bytes: int


class LocalObjectStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def store(self, file_bytes: bytes, filename: str, content_type: str) -> StoredObject:
        del content_type
        safe_name = Path(filename).name
        storage_key = f"{uuid4()}-{safe_name}"
        destination = self.root / storage_key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(file_bytes)
        return StoredObject(storage_key=storage_key, size_bytes=len(file_bytes))

    def read(self, storage_key: str) -> bytes:
        return (self.root / storage_key).read_bytes()


class MinioObjectStorage:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        secure: bool,
    ) -> None:
        self.client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self.bucket_name = bucket_name

    def _ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket_name):
            self.client.make_bucket(self.bucket_name)

    def store(self, file_bytes: bytes, filename: str, content_type: str) -> StoredObject:
        self._ensure_bucket()
        safe_name = Path(filename).name
        storage_key = f"raw/{uuid4()}-{safe_name}"
        self.client.put_object(
            self.bucket_name,
            storage_key,
            io.BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=content_type,
        )
        return StoredObject(storage_key=storage_key, size_bytes=len(file_bytes))

    def read(self, storage_key: str) -> bytes:
        response = self.client.get_object(self.bucket_name, storage_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()


def get_object_storage() -> LocalObjectStorage | MinioObjectStorage:
    settings = get_settings()

    if settings.object_storage_provider == "minio":
        return MinioObjectStorage(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket_name=settings.minio_bucket_name,
            secure=settings.minio_secure,
        )

    return LocalObjectStorage(root=Path(settings.object_storage_root))
