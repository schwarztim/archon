"""Pipeline artifact bridge node executors (W9c).

Two executors:

``execute_pipeline_artifact_upload``
  Upload an Archon artifact (identified by artifact URI from output_data) to
  an external pipeline via the provider adapter. The artifact bytes are read
  from Archon's artifact_service and POSTed to the provider's artifact URL.

``execute_pipeline_artifact_download``
  Download an artifact from an external pipeline (via a URL in node_config or
  input_data) and store it in Archon's artifact_service, returning the
  resulting artifact URI.

Both executors use the provider adapter's HTTP helpers (injectable in tests).

node_config keys (upload):
  ``artifact_uri``         — Archon artifact:// URI to upload
  ``provider``             — provider name (for credential resolution)
  ``upload_url``           — target URL on the external system
  ``credential_refs``      — dict of vault refs
  ``upload_headers``       — extra headers for the PUT/POST request

node_config keys (download):
  ``download_url``         — URL to fetch the artifact from
  ``credential_refs``      — dict of vault refs
  ``artifact_name``        — name to store the artifact under (default: "pipeline_artifact")
  ``artifact_metadata``    — extra metadata dict to attach
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


# ── Upload executor ───────────────────────────────────────────────────────────


async def execute_pipeline_artifact_upload(context: Any) -> Any:
    """W9c: upload an Archon artifact to an external pipeline."""
    from app.services.activity_runtime import ActivityResult  # noqa: PLC0415

    config: dict[str, Any] = context.node_config or {}
    artifact_uri: str = config.get("artifact_uri") or (
        (context.input_data or {}).get("artifact_uri", "")
    )
    upload_url: str = config.get("upload_url", "")

    if not artifact_uri:
        return ActivityResult(
            status="failed",
            error_code="ValueError",
            error_message="pipeline_artifact_upload: artifact_uri is required",
            non_retryable=True,
        )
    if not upload_url:
        return ActivityResult(
            status="failed",
            error_code="ValueError",
            error_message="pipeline_artifact_upload: upload_url is required",
            non_retryable=True,
        )

    # Resolve credentials.
    credential_refs: dict[str, str] = config.get("credential_refs") or {}
    credentials: dict[str, Any] = {}
    for key, ref in credential_refs.items():
        try:
            credentials[key] = await context.resolve_secret(ref)
        except Exception as exc:  # noqa: BLE001
            return ActivityResult(
                status="failed",
                error_code="SecretResolutionError",
                error_message=f"pipeline_artifact_upload: credential {key!r} resolution failed: {exc}",
                non_retryable=True,
            )

    # Fetch artifact bytes from Archon's artifact service.
    try:
        artifact_bytes = await _fetch_archon_artifact(artifact_uri, context)
    except Exception as exc:  # noqa: BLE001
        return ActivityResult(
            status="failed",
            error_code="ArtifactFetchError",
            error_message=f"pipeline_artifact_upload: failed to fetch {artifact_uri!r}: {exc}",
        )

    # Upload to external system.
    extra_headers: dict[str, str] = config.get("upload_headers") or {}
    token = credentials.get("token")
    headers: dict[str, str] = {
        "Content-Type": "application/octet-stream",
        **extra_headers,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = await _http_put(upload_url, headers=headers, content=artifact_bytes)
        if resp.get("status_code", 0) not in (200, 201, 202, 204):
            return ActivityResult(
                status="failed",
                error_code=f"HTTP_{resp.get('status_code')}",
                error_message=(
                    f"pipeline_artifact_upload: upload returned {resp.get('status_code')}"
                ),
            )
    except Exception as exc:  # noqa: BLE001
        return ActivityResult(
            status="failed",
            error_code="UploadError",
            error_message=f"pipeline_artifact_upload: upload failed: {exc}",
        )

    await context.heartbeat(
        {"artifact_uri": artifact_uri, "upload_url": upload_url, "uploaded": True}
    )

    return ActivityResult(
        status="completed",
        output_data={
            "artifact_uri": artifact_uri,
            "upload_url": upload_url,
            "bytes_uploaded": len(artifact_bytes),
        },
    )


# ── Download executor ─────────────────────────────────────────────────────────


async def execute_pipeline_artifact_download(context: Any) -> Any:
    """W9c: download a pipeline artifact and store in Archon's artifact service."""
    from app.services.activity_runtime import ActivityResult  # noqa: PLC0415

    config: dict[str, Any] = context.node_config or {}
    download_url: str = config.get("download_url") or (
        (context.input_data or {}).get("download_url", "")
    )
    if not download_url:
        return ActivityResult(
            status="failed",
            error_code="ValueError",
            error_message="pipeline_artifact_download: download_url is required",
            non_retryable=True,
        )

    artifact_name: str = config.get("artifact_name") or "pipeline_artifact"
    extra_metadata: dict[str, Any] = config.get("artifact_metadata") or {}

    # Resolve credentials.
    credential_refs: dict[str, str] = config.get("credential_refs") or {}
    credentials: dict[str, Any] = {}
    for key, ref in credential_refs.items():
        try:
            credentials[key] = await context.resolve_secret(ref)
        except Exception as exc:  # noqa: BLE001
            return ActivityResult(
                status="failed",
                error_code="SecretResolutionError",
                error_message=f"pipeline_artifact_download: credential {key!r} resolution failed: {exc}",
                non_retryable=True,
            )

    token = credentials.get("token")
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Download the artifact bytes.
    try:
        resp = await _http_get_bytes(download_url, headers=headers)
        if resp.get("status_code", 0) not in range(200, 300):
            return ActivityResult(
                status="failed",
                error_code=f"HTTP_{resp.get('status_code')}",
                error_message=(
                    f"pipeline_artifact_download: GET returned {resp.get('status_code')}"
                ),
            )
        artifact_bytes: bytes = resp.get("body", b"") or b""
    except Exception as exc:  # noqa: BLE001
        return ActivityResult(
            status="failed",
            error_code="DownloadError",
            error_message=f"pipeline_artifact_download: download failed: {exc}",
        )

    # Store in Archon artifact service via the runtime callback.
    metadata = {
        "source_url": download_url,
        "source": "pipeline_artifact",
        **extra_metadata,
    }
    try:
        stored_uri = await context.write_artifact(
            artifact_name,
            artifact_bytes,
            metadata,
        )
    except Exception as exc:  # noqa: BLE001
        return ActivityResult(
            status="failed",
            error_code="ArtifactStoreError",
            error_message=f"pipeline_artifact_download: failed to store artifact: {exc}",
        )

    await context.heartbeat(
        {
            "download_url": download_url,
            "artifact_name": artifact_name,
            "stored_uri": stored_uri,
            "bytes_downloaded": len(artifact_bytes),
        }
    )

    return ActivityResult(
        status="completed",
        output_data={
            "artifact_uri": stored_uri,
            "artifact_name": artifact_name,
            "download_url": download_url,
            "bytes_downloaded": len(artifact_bytes),
        },
        artifacts=[stored_uri],
    )


# ── HTTP helpers ──────────────────────────────────────────────────────────────


async def _http_put(
    url: str,
    *,
    headers: dict[str, str],
    content: bytes,
) -> dict[str, Any]:
    try:
        import httpx  # noqa: PLC0415
    except ImportError:
        raise RuntimeError("httpx is required for pipeline_artifact_upload")

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.put(url, headers=headers, content=content)
    return {"status_code": resp.status_code, "body": resp.text}


async def _http_get_bytes(
    url: str,
    *,
    headers: dict[str, str],
) -> dict[str, Any]:
    try:
        import httpx  # noqa: PLC0415
    except ImportError:
        raise RuntimeError("httpx is required for pipeline_artifact_download")

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
    return {"status_code": resp.status_code, "body": resp.content}


async def _fetch_archon_artifact(artifact_uri: str, context: Any) -> bytes:
    """Fetch artifact bytes from Archon's artifact service using the URI.

    URI format: ``artifact://{tenant_id}/{kind}/{artifact_id}``
    Falls back to raw HTTP GET if the service is unavailable (tests).
    """
    # Parse the URI: artifact://<tenant>/<kind>/<uuid>
    if not artifact_uri.startswith("artifact://"):
        raise ValueError(f"Not an Archon artifact URI: {artifact_uri!r}")

    parts = artifact_uri[len("artifact://"):].split("/")
    if len(parts) < 3:
        raise ValueError(f"Malformed artifact URI: {artifact_uri!r}")

    artifact_id_str = parts[-1]

    try:
        from uuid import UUID  # noqa: PLC0415

        from app.services import artifact_service  # noqa: PLC0415

        artifact_id = UUID(artifact_id_str)
        session = context.db_session
        if session is not None:
            _artifact, content = await artifact_service.get_artifact(
                session, artifact_id
            )
            if isinstance(content, (bytes, bytearray)):
                return bytes(content)
            if isinstance(content, str):
                return content.encode()
    except Exception as exc:  # noqa: BLE001
        log.debug("_fetch_archon_artifact: artifact_service failed: %s", exc)

    raise RuntimeError(
        f"Cannot fetch artifact bytes for {artifact_uri!r}: artifact_service unavailable"
    )


__all__ = [
    "execute_pipeline_artifact_download",
    "execute_pipeline_artifact_upload",
]
