"""
ModelStorageService – where model files live.

The ML engine never touches files. The pipeline serialises a model to bytes
(ml.model.serialize_model), and this service stores them under a key such as
    live/20261001T120000Z/model_v2_0.joblib
and returns a StoredModel(path, checksum, size). The checksum is kept in the
model_versions table and verified before bytes are ever unpickled.

Backends:
  * LocalModelStorage – a directory (development, Docker volume)
  * S3ModelStorage    – any S3-compatible object store: AWS S3, Supabase
                        Storage (S3 endpoint), Cloudflare R2, MinIO

Models are write-once: saving to an existing key fails instead of overwriting.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,250}$")


class StorageError(RuntimeError):
    pass


class IntegrityError(StorageError):
    pass


@dataclass(frozen=True)
class StoredModel:
    path: str        # backend-specific location, stored in model_versions.model_path
    checksum: str    # sha256 hex
    size: int


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_key(key: str) -> str:
    if not _KEY_RE.match(key) or ".." in key or key.startswith("/"):
        raise StorageError(f"Invalid storage key: {key!r}")
    return key


class ModelStorage(Protocol):
    def save(self, key: str, data: bytes) -> StoredModel: ...
    def load(self, path: str, checksum: str | None = None) -> bytes: ...
    def delete(self, path: str) -> None: ...
    def exists(self, path: str) -> bool: ...
    def describe(self) -> str: ...


class LocalModelStorage:
    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir).resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        p = (self.base / _check_key(key)).resolve()
        if self.base not in p.parents:
            raise StorageError("Storage key escapes the model directory")
        return p

    def save(self, key: str, data: bytes) -> StoredModel:
        p = self._resolve(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(p, "xb") as fh:          # "x": never overwrite an existing model
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
        except FileExistsError as exc:
            raise StorageError(f"Model file already exists: {key}") from exc
        return StoredModel(path=key, checksum=sha256(data), size=len(data))

    def load(self, path: str, checksum: str | None = None) -> bytes:
        p = self._resolve(path)
        if not p.exists():
            raise StorageError(f"Model file not found: {path}")
        data = p.read_bytes()
        if checksum and sha256(data) != checksum:
            raise IntegrityError(f"Checksum mismatch for {path}; refusing to load it")
        return data

    def delete(self, path: str) -> None:
        p = self._resolve(path)
        p.unlink(missing_ok=True)

    def exists(self, path: str) -> bool:
        return self._resolve(path).is_file()

    def describe(self) -> str:
        return f"local:{self.base}"


class S3ModelStorage:
    def __init__(self, bucket: str, prefix: str = "", endpoint_url: str | None = None, region: str | None = None):
        try:
            import boto3  # lazy: only needed when this backend is selected
        except ImportError as exc:  # pragma: no cover
            raise StorageError("MODEL_STORAGE_BACKEND=s3 requires the 'boto3' package") from exc
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._client = boto3.client("s3", endpoint_url=endpoint_url or None, region_name=region or None)

    def _key(self, key: str) -> str:
        key = _check_key(key)
        return f"{self.prefix}/{key}" if self.prefix else key

    def save(self, key: str, data: bytes) -> StoredModel:
        from botocore.exceptions import ClientError
        full = self._key(key)
        try:
            self._client.head_object(Bucket=self.bucket, Key=full)
            raise StorageError(f"Model object already exists: {full}")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey", "NotFound"):
                raise StorageError(f"Could not check model object: {exc}") from exc
        digest = sha256(data)
        self._client.put_object(Bucket=self.bucket, Key=full, Body=data, ContentType="application/octet-stream",
                                Metadata={"sha256": digest})
        return StoredModel(path=key, checksum=digest, size=len(data))

    def load(self, path: str, checksum: str | None = None) -> bytes:
        from botocore.exceptions import ClientError
        try:
            data = self._client.get_object(Bucket=self.bucket, Key=self._key(path))["Body"].read()
        except ClientError as exc:
            raise StorageError(f"Model object not found: {path}") from exc
        if checksum and sha256(data) != checksum:
            raise IntegrityError(f"Checksum mismatch for {path}; refusing to load it")
        return data

    def delete(self, path: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=self._key(path))

    def exists(self, path: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self._client.head_object(Bucket=self.bucket, Key=self._key(path))
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise StorageError(f"Could not check model object: {exc}") from exc

    def describe(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}"


def build_model_storage(settings) -> ModelStorage:
    backend = settings.model_storage_backend.lower()
    if backend == "local":
        return LocalModelStorage(settings.model_storage_dir)
    if backend == "s3":
        return S3ModelStorage(settings.s3_bucket, settings.s3_prefix, settings.s3_endpoint_url, settings.s3_region)
    raise StorageError(f"Unknown MODEL_STORAGE_BACKEND '{settings.model_storage_backend}' (use 'local' or 's3')")
