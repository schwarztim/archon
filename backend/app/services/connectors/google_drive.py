"""Google Drive connector — Google Drive API v3 via httpx."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.services.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_DRIVE_BASE = "https://www.googleapis.com/drive/v3"
_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"


class GoogleDriveConnector(BaseConnector):
    """Connector for Google Drive API v3.

    Credential keys (``credentials`` dict, loaded from Vault):
        access_token: OAuth 2.0 access token.
        token_type: Token type (default ``"Bearer"``).

    Configuration keys (``config`` dict):
        default_folder_id: Default parent folder ID for new files.
        page_size: Default page size for file listing (default 100).
    """

    connector_type = "google_drive"

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        super().__init__(config, credentials)
        self._client: Any = None  # httpx.AsyncClient

    # ------------------------------------------------------------------
    # HTTP client
    # ------------------------------------------------------------------

    def _access_token(self) -> str:
        return self.credentials.get("access_token") or self.credentials.get("token", "")

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            import httpx  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "httpx is required for GoogleDriveConnector. "
                "Install it with: pip install httpx"
            ) from exc

        token_type = self.credentials.get("token_type", "Bearer")
        self._client = httpx.AsyncClient(
            base_url=_DRIVE_BASE,
            headers={
                "Authorization": f"{token_type} {self._access_token()}",
                "Accept": "application/json",
            },
            timeout=30.0,
        )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Execute an authenticated Drive API request."""
        client = await self._get_client()
        response = await client.request(method, path, params=params, json=json)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def test_connection(self) -> dict[str, Any]:
        """Verify token validity by fetching ``about`` resource."""
        start = time.monotonic()
        try:
            data = await self._request(
                "GET", "/about", params={"fields": "user,storageQuota"}
            )
            latency = (time.monotonic() - start) * 1000
            user = data.get("user", {})
            return {
                "success": True,
                "latency_ms": round(latency, 2),
                "message": "Drive API authenticated",
                "details": {
                    "display_name": user.get("displayName"),
                    "email": user.get("emailAddress"),
                },
            }
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            logger.warning("Google Drive test_connection failed: %s", exc)
            return {
                "success": False,
                "latency_ms": round(latency, 2),
                "message": str(exc),
            }

    async def health_check(self) -> dict[str, Any]:
        """Return health status based on ``about`` availability."""
        start = time.monotonic()
        try:
            await self._request("GET", "/about", params={"fields": "user"})
            latency = (time.monotonic() - start) * 1000
            return {
                "status": "healthy",
                "latency_ms": round(latency, 2),
                "message": "Drive API reachable",
            }
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return {
                "status": "error",
                "latency_ms": round(latency, 2),
                "message": str(exc),
            }

    async def list_resources(self) -> list[dict[str, Any]]:
        """List files and folders via ``files.list``.

        Returns:
            List of file/folder descriptors with ``id``, ``name``,
            ``mimeType``, ``modifiedTime``.
        """
        page_size = int(self.config.get("page_size", 100))
        fields = "nextPageToken, files(id, name, mimeType, modifiedTime, size, parents)"
        params: dict[str, Any] = {
            "pageSize": page_size,
            "fields": fields,
            "orderBy": "modifiedTime desc",
        }
        try:
            data = await self._request("GET", "/files", params=params)
            files: list[dict[str, Any]] = data.get("files", [])
            return [
                {
                    "id": f["id"],
                    "name": f.get("name", ""),
                    "mime_type": f.get("mimeType", ""),
                    "modified_time": f.get("modifiedTime", ""),
                    "size": f.get("size"),
                    "parents": f.get("parents", []),
                }
                for f in files
            ]
        except Exception as exc:
            logger.error("Google Drive list_resources failed: %s", exc)
            raise

    async def read(
        self,
        resource_id: str,
        params: dict[str, Any] | None = None,
    ) -> bytes:
        """Download a file from Google Drive.

        Args:
            resource_id: Google Drive file ID.
            params: Optional dict with:
                - ``export_mime_type`` (str): For Google Docs export
                  (e.g. ``"application/pdf"``).

        Returns:
            File contents as bytes.
        """
        params = params or {}
        try:
            import httpx  # type: ignore[import]
        except ImportError as exc:
            raise ImportError("httpx required") from exc

        client = await self._get_client()
        token_type = self.credentials.get("token_type", "Bearer")

        if params.get("export_mime_type"):
            # Export Google Workspace doc to another format
            response = await client.get(
                f"/files/{resource_id}/export",
                params={"mimeType": params["export_mime_type"]},
            )
        else:
            # Regular binary download via alt=media
            # Must use the raw URL (not the httpx base_url which is Drive API)
            response = await httpx.AsyncClient(
                headers={"Authorization": f"{token_type} {self._access_token()}"},
                timeout=60.0,
            ).get(
                f"{_DRIVE_BASE}/files/{resource_id}",
                params={"alt": "media"},
            )

        response.raise_for_status()
        return response.content

    async def write(
        self,
        resource_id: str,
        data: Any,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or update a file in Google Drive.

        Args:
            resource_id: File name for new files, or Drive file ID to update.
            data: File contents as bytes or str.
            params: Optional dict with:
                - ``parent_id`` (str): Parent folder ID.
                - ``mime_type`` (str): Content MIME type.
                - ``update`` (bool): If True, update existing file by ID.

        Returns:
            Dict with ``{"success": bool, "file_id": str, "name": str}``.
        """
        params = params or {}
        try:
            import httpx  # type: ignore[import]
        except ImportError as exc:
            raise ImportError("httpx required") from exc

        token_type = self.credentials.get("token_type", "Bearer")
        if isinstance(data, str):
            body = data.encode("utf-8")
        elif isinstance(data, bytes):
            body = data
        else:
            import json as _json

            body = _json.dumps(data).encode("utf-8")

        mime_type = params.get("mime_type", "application/octet-stream")
        is_update = params.get("update", False)

        metadata: dict[str, Any] = {"name": resource_id}
        if params.get("parent_id"):
            metadata["parents"] = [params["parent_id"]]
        elif self.config.get("default_folder_id") and not is_update:
            metadata["parents"] = [self.config["default_folder_id"]]

        import json as _json

        meta_bytes = _json.dumps(metadata).encode("utf-8")

        # Multipart upload
        boundary = "boundary_archon_upload"
        multipart = (
            (
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            ).encode()
            + meta_bytes
            + (f"\r\n--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n").encode()
            + body
            + f"\r\n--{boundary}--".encode()
        )

        upload_headers = {
            "Authorization": f"{token_type} {self._access_token()}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        }

        async with httpx.AsyncClient(timeout=60.0) as upload_client:
            if is_update:
                response = await upload_client.patch(
                    f"{_UPLOAD_BASE}/files/{resource_id}",
                    params={"uploadType": "multipart"},
                    content=multipart,
                    headers=upload_headers,
                )
            else:
                response = await upload_client.post(
                    f"{_UPLOAD_BASE}/files",
                    params={"uploadType": "multipart"},
                    content=multipart,
                    headers=upload_headers,
                )

        response.raise_for_status()
        result = response.json()
        return {
            "success": True,
            "file_id": result.get("id", ""),
            "name": result.get("name", resource_id),
        }

    async def get_schema(self, resource_id: str) -> dict[str, Any]:
        """Return file metadata as a schema descriptor.

        Args:
            resource_id: Google Drive file ID.

        Returns:
            Dict with ``{"file_id": str, "fields": list[dict]}``.
        """
        fields = (
            "id, name, mimeType, size, createdTime, modifiedTime, "
            "parents, owners, permissions, capabilities"
        )
        try:
            data = await self._request(
                "GET",
                f"/files/{resource_id}",
                params={"fields": fields},
            )
            return {
                "file_id": resource_id,
                "name": data.get("name", ""),
                "mime_type": data.get("mimeType", ""),
                "size": data.get("size"),
                "created_time": data.get("createdTime", ""),
                "modified_time": data.get("modifiedTime", ""),
                "fields": [
                    {"name": "id", "type": "str", "description": "File ID"},
                    {"name": "name", "type": "str", "description": "File name"},
                    {"name": "mimeType", "type": "str", "description": "MIME type"},
                    {
                        "name": "size",
                        "type": "int",
                        "description": "File size in bytes",
                    },
                    {
                        "name": "createdTime",
                        "type": "datetime",
                        "description": "Creation time",
                    },
                    {
                        "name": "modifiedTime",
                        "type": "datetime",
                        "description": "Last modified time",
                    },
                    {
                        "name": "parents",
                        "type": "list",
                        "description": "Parent folder IDs",
                    },
                    {"name": "owners", "type": "list", "description": "File owners"},
                ],
            }
        except Exception as exc:
            logger.error("Google Drive get_schema failed for %s: %s", resource_id, exc)
            raise


__all__ = ["GoogleDriveConnector"]
