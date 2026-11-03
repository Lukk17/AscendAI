"""One shared S3 client of the service (design D3).

Every feature that writes objects shares this client and its connection
settings ``OBJECT_STORE_S3_ENDPOINT``, ``OBJECT_STORE_S3_ACCESS_KEY`` and
``OBJECT_STORE_S3_SECRET_KEY``. No other module of the service creates an
S3 client. Blocking boto3 calls run in a thread through ``asyncio.to_thread``
so the worker loop never stalls.
"""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

from src.config.config import settings

logger = logging.getLogger(__name__)


def build_client() -> "S3Client":
    return boto3.client(
        "s3",
        endpoint_url=settings.OBJECT_STORE_S3_ENDPOINT,
        aws_access_key_id=settings.OBJECT_STORE_S3_ACCESS_KEY or None,
        aws_secret_access_key=settings.OBJECT_STORE_S3_SECRET_KEY or None,
    )


class ObjectStore:
    """Thin async wrapper over one S3-compatible bucket namespace."""

    def __init__(self, client: "S3Client | None" = None) -> None:
        self._client = client if client is not None else build_client()

    async def upload_file(self, path: str, bucket: str, key: str) -> None:
        """Upload a local file, using multipart for large files (boto3 default)."""
        await asyncio.to_thread(self._client.upload_file, path, bucket, key)

    async def put_json(self, bucket: str, key: str, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        await asyncio.to_thread(self._client.put_object, Bucket=bucket, Key=key, Body=body)

    async def put_text(self, bucket: str, key: str, text: str) -> None:
        await asyncio.to_thread(self._client.put_object, Bucket=bucket, Key=key, Body=text.encode("utf-8"))

    async def put_bytes(self, bucket: str, key: str, body: bytes) -> None:
        await asyncio.to_thread(self._client.put_object, Bucket=bucket, Key=key, Body=body)

    async def get_text(self, bucket: str, key: str) -> str | None:
        try:
            response = await asyncio.to_thread(self._client.get_object, Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise
        raw: bytes = await asyncio.to_thread(response["Body"].read)
        return raw.decode("utf-8")

    async def get_json(self, bucket: str, key: str) -> dict[str, Any]:
        response = await asyncio.to_thread(self._client.get_object, Bucket=bucket, Key=key)
        raw: bytes = await asyncio.to_thread(response["Body"].read)
        loaded: dict[str, Any] = json.loads(raw.decode("utf-8"))
        return loaded

    async def head(self, bucket: str, key: str) -> bool:
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True

    async def delete(self, bucket: str, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=bucket, Key=key)

    async def copy_inside_bucket(self, bucket: str, source_key: str, dest_key: str) -> None:
        """Server-side copy of one object, so bytes never pass the service."""
        await asyncio.to_thread(
            self._client.copy_object,
            Bucket=bucket,
            Key=dest_key,
            CopySource={"Bucket": bucket, "Key": source_key},
        )

    async def list_prefix(
        self, bucket: str, prefix: str, continuation: str | None = None
    ) -> tuple[list[str], str | None]:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if continuation is not None:
            kwargs["ContinuationToken"] = continuation
        response = await asyncio.to_thread(self._client.list_objects_v2, **kwargs)
        keys = [item["Key"] for item in response.get("Contents", [])]
        token = response.get("NextContinuationToken")
        return keys, token

    async def ensure_bucket(self, bucket: str) -> None:
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=bucket)
        except ClientError as exc:
            error = exc.response.get("Error", {})
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if error.get("Code") not in ("404", "NoSuchBucket", "NotFound") and status != 404:
                raise
            await asyncio.to_thread(self._client.create_bucket, Bucket=bucket)
            logger.info("object store: created bucket %s", bucket)

    async def presign_get(self, bucket: str, key: str, expires_seconds: int = 3600) -> str:
        url: str = await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )
        return url
