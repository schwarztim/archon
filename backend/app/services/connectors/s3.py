"""AWS S3 connector — boto3 async wrapper (via asyncio.to_thread)."""

from __future__ import annotations

import asyncio
import io
import logging
import time
from typing import Any

from app.services.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class S3Connector(BaseConnector):
    """Connector for Amazon S3 using boto3 (run in thread pool for async compat).

    Configuration keys (``config`` dict):
        region: AWS region (default ``"us-east-1"``).
        bucket: Default bucket name.
        endpoint_url: Optional custom endpoint (MinIO, LocalStack, etc.).

    Credential keys (``credentials`` dict, loaded from Vault):
        access_key: AWS Access Key ID.
        secret_key: AWS Secret Access Key.
        session_token: Optional session token.
    """

    connector_type = "s3"

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        super().__init__(config, credentials)
        self._s3_client: Any = None

    # ------------------------------------------------------------------
    # boto3 client
    # ------------------------------------------------------------------

    def _get_s3(self) -> Any:
        """Return (or create) the boto3 S3 client."""
        if self._s3_client is not None:
            return self._s3_client

        try:
            import boto3  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for S3Connector. Install it with: pip install boto3"
            ) from exc

        kwargs: dict[str, Any] = {
            "region_name": self.config.get("region", "us-east-1"),
            "aws_access_key_id": self.credentials.get("access_key"),
            "aws_secret_access_key": self.credentials.get("secret_key"),
        }
        if self.credentials.get("session_token"):
            kwargs["aws_session_token"] = self.credentials["session_token"]
        if self.config.get("endpoint_url"):
            kwargs["endpoint_url"] = self.config["endpoint_url"]

        self._s3_client = boto3.client("s3", **kwargs)
        return self._s3_client

    async def _run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute a synchronous boto3 call in a thread pool."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def close(self) -> None:
        """boto3 clients are not async and have no explicit close."""
        self._s3_client = None

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def test_connection(self) -> dict[str, Any]:
        """Verify credentials by calling ``list_buckets``."""
        start = time.monotonic()
        try:
            s3 = self._get_s3()
            response = await self._run(s3.list_buckets)
            latency = (time.monotonic() - start) * 1000
            bucket_count = len(response.get("Buckets", []))
            return {
                "success": True,
                "latency_ms": round(latency, 2),
                "message": "S3 credentials valid",
                "details": {"bucket_count": bucket_count},
            }
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            logger.warning("S3 test_connection failed: %s", exc)
            return {
                "success": False,
                "latency_ms": round(latency, 2),
                "message": str(exc),
            }

    async def health_check(self) -> dict[str, Any]:
        """Return health status by listing buckets."""
        start = time.monotonic()
        try:
            s3 = self._get_s3()
            await self._run(s3.list_buckets)
            latency = (time.monotonic() - start) * 1000
            return {
                "status": "healthy",
                "latency_ms": round(latency, 2),
                "message": "S3 reachable",
            }
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return {
                "status": "error",
                "latency_ms": round(latency, 2),
                "message": str(exc),
            }

    async def list_resources(self) -> list[dict[str, Any]]:
        """List all accessible S3 buckets.

        If a default bucket is configured, also lists objects within it.

        Returns:
            List of bucket/object descriptors.
        """
        try:
            s3 = self._get_s3()
            response = await self._run(s3.list_buckets)
            buckets = response.get("Buckets", [])
            return [
                {
                    "id": b["Name"],
                    "name": b["Name"],
                    "type": "bucket",
                    "created": b.get("CreationDate", "").isoformat()
                    if hasattr(b.get("CreationDate", ""), "isoformat")
                    else str(b.get("CreationDate", "")),
                }
                for b in buckets
            ]
        except Exception as exc:
            logger.error("S3 list_resources failed: %s", exc)
            raise

    async def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        max_keys: int = 1000,
    ) -> list[dict[str, Any]]:
        """List objects in a specific bucket.

        Args:
            bucket: Bucket name.
            prefix: Optional key prefix filter.
            max_keys: Maximum objects to return (default 1000).

        Returns:
            List of object descriptors.
        """
        try:
            s3 = self._get_s3()
            response = await self._run(
                s3.list_objects_v2,
                Bucket=bucket,
                Prefix=prefix,
                MaxKeys=max_keys,
            )
            contents = response.get("Contents", [])
            return [
                {
                    "id": obj["Key"],
                    "name": obj["Key"].split("/")[-1],
                    "key": obj["Key"],
                    "size": obj.get("Size", 0),
                    "last_modified": str(obj.get("LastModified", "")),
                    "etag": obj.get("ETag", "").strip('"'),
                }
                for obj in contents
            ]
        except Exception as exc:
            logger.error("S3 list_objects failed for bucket %s: %s", bucket, exc)
            raise

    async def read(
        self,
        resource_id: str,
        params: dict[str, Any] | None = None,
    ) -> bytes:
        """Download an S3 object.

        Args:
            resource_id: The S3 key (path within the bucket).
            params: Optional dict with:
                - ``bucket`` (str): Override the default bucket.
                - ``byte_range`` (str): ``Range`` header value.

        Returns:
            Object body as bytes.
        """
        params = params or {}
        bucket = params.get("bucket") or self.config.get("bucket", "")
        if not bucket:
            raise ValueError("bucket must be specified in config or params")

        get_kwargs: dict[str, Any] = {"Bucket": bucket, "Key": resource_id}
        if params.get("byte_range"):
            get_kwargs["Range"] = params["byte_range"]

        try:
            s3 = self._get_s3()
            response = await self._run(s3.get_object, **get_kwargs)
            body: bytes = await asyncio.to_thread(response["Body"].read)
            return body
        except Exception as exc:
            logger.error("S3 read failed for key %s: %s", resource_id, exc)
            raise

    async def write(
        self,
        resource_id: str,
        data: Any,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Upload data to S3.

        Args:
            resource_id: The S3 key (path within the bucket).
            data: Bytes or string to upload.
            params: Optional dict with:
                - ``bucket`` (str): Override the default bucket.
                - ``content_type`` (str): MIME type.
                - ``metadata`` (dict): Object metadata.

        Returns:
            Dict with ``{"success": bool, "bucket": str, "key": str}``.
        """
        params = params or {}
        bucket = params.get("bucket") or self.config.get("bucket", "")
        if not bucket:
            raise ValueError("bucket must be specified in config or params")

        if isinstance(data, str):
            body = data.encode("utf-8")
        elif isinstance(data, bytes):
            body = data
        else:
            import json as _json

            body = _json.dumps(data).encode("utf-8")

        put_kwargs: dict[str, Any] = {
            "Bucket": bucket,
            "Key": resource_id,
            "Body": io.BytesIO(body),
        }
        if params.get("content_type"):
            put_kwargs["ContentType"] = params["content_type"]
        if params.get("metadata"):
            put_kwargs["Metadata"] = params["metadata"]

        try:
            s3 = self._get_s3()
            await self._run(s3.put_object, **put_kwargs)
            return {"success": True, "bucket": bucket, "key": resource_id}
        except Exception as exc:
            logger.error("S3 write failed for key %s: %s", resource_id, exc)
            raise

    async def get_schema(self, resource_id: str) -> dict[str, Any]:
        """Return head-object metadata as a schema descriptor.

        Args:
            resource_id: S3 key.

        Returns:
            Dict with object metadata fields.
        """
        params_default: dict[str, Any] = {}
        bucket = self.config.get("bucket", "")
        if not bucket:
            return {
                "key": resource_id,
                "fields": [
                    {"name": "Key", "type": "str"},
                    {"name": "Size", "type": "int"},
                    {"name": "LastModified", "type": "datetime"},
                    {"name": "ContentType", "type": "str"},
                    {"name": "ETag", "type": "str"},
                ],
            }

        try:
            s3 = self._get_s3()
            response = await self._run(s3.head_object, Bucket=bucket, Key=resource_id)
            return {
                "key": resource_id,
                "bucket": bucket,
                "content_type": response.get("ContentType", ""),
                "content_length": response.get("ContentLength", 0),
                "last_modified": str(response.get("LastModified", "")),
                "metadata": response.get("Metadata", {}),
                "fields": [
                    {"name": "Key", "type": "str"},
                    {"name": "Size", "type": "int"},
                    {"name": "LastModified", "type": "datetime"},
                    {"name": "ContentType", "type": "str"},
                    {"name": "ETag", "type": "str"},
                ],
            }
        except Exception as exc:
            logger.error("S3 get_schema failed for key %s: %s", resource_id, exc)
            raise


__all__ = ["S3Connector"]
