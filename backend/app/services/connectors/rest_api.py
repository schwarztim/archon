"""REST API connector — httpx.AsyncClient with bearer/basic/api_key auth."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.services.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_AUTH_BEARER = "bearer"
_AUTH_BASIC = "basic"
_AUTH_API_KEY = "api_key"
_AUTH_NONE = "none"


class RestApiConnector(BaseConnector):
    """Generic REST API connector backed by ``httpx.AsyncClient``.

    Configuration keys (``config`` dict):
        base_url: Base URL for all requests.
        auth_type: One of ``"bearer"`` / ``"basic"`` / ``"api_key"`` / ``"none"``.
        auth_key_name: Header/param name for API-key auth (e.g. ``"X-API-Key"``).
        headers_json: JSON string of extra headers.

    Credential keys (``credentials`` dict, loaded from Vault):
        token: Bearer token (when auth_type == "bearer").
        username: Username (when auth_type == "basic").
        password: Password (when auth_type == "basic").
        api_key: API key value (when auth_type == "api_key").
    """

    connector_type = "rest_api"

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        super().__init__(config, credentials)
        self._client: Any = None  # httpx.AsyncClient

    # ------------------------------------------------------------------
    # HTTP client
    # ------------------------------------------------------------------

    def _build_auth_headers(self) -> dict[str, str]:
        """Build authentication headers based on auth_type."""
        auth_type = (self.config.get("auth_type") or _AUTH_NONE).lower()
        headers: dict[str, str] = {}

        if auth_type == _AUTH_BEARER:
            token = self.credentials.get("token") or self.credentials.get(
                "auth_key_value", ""
            )
            if token:
                headers["Authorization"] = f"Bearer {token}"

        elif auth_type == _AUTH_BASIC:
            import base64

            username = self.credentials.get("username") or self.config.get(
                "username", ""
            )
            password = self.credentials.get("password") or self.credentials.get(
                "secret_credential", ""
            )
            if username:
                encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
                headers["Authorization"] = f"Basic {encoded}"

        elif auth_type == _AUTH_API_KEY:
            key_name = self.config.get("auth_key_name", "X-API-Key")
            key_value = self.credentials.get("api_key") or self.credentials.get(
                "auth_key_value", ""
            )
            if key_name and key_value:
                headers[key_name] = key_value

        return headers

    def _build_extra_headers(self) -> dict[str, str]:
        """Parse the optional ``headers_json`` config field."""
        raw = self.config.get("headers_json", "")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("rest_api: could not parse headers_json")
            return {}

    async def _get_client(self) -> Any:
        """Return the httpx.AsyncClient, creating it on first call."""
        if self._client is not None:
            return self._client

        try:
            import httpx  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "httpx is required for RestApiConnector. "
                "Install it with: pip install httpx"
            ) from exc

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **self._build_extra_headers(),
            **self._build_auth_headers(),
        }

        self._client = httpx.AsyncClient(
            base_url=self.config.get("base_url", ""),
            headers=headers,
            timeout=30.0,
            follow_redirects=True,
        )
        return self._client

    async def close(self) -> None:
        """Close the underlying httpx.AsyncClient."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def test_connection(self) -> dict[str, Any]:
        """Attempt a HEAD/GET to the base URL to confirm connectivity."""
        start = time.monotonic()
        try:
            client = await self._get_client()
            response = await client.get("/")
            latency = (time.monotonic() - start) * 1000
            return {
                "success": response.is_success or response.status_code < 500,
                "latency_ms": round(latency, 2),
                "message": f"HTTP {response.status_code}",
                "details": {"status_code": response.status_code},
            }
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            logger.warning("REST API test_connection failed: %s", exc)
            return {
                "success": False,
                "latency_ms": round(latency, 2),
                "message": str(exc),
            }

    async def health_check(self) -> dict[str, Any]:
        """Return health status based on a lightweight GET request."""
        start = time.monotonic()
        try:
            client = await self._get_client()
            response = await client.get("/")
            latency = (time.monotonic() - start) * 1000
            if response.is_success:
                return {
                    "status": "healthy",
                    "latency_ms": round(latency, 2),
                    "message": "API reachable",
                }
            if response.status_code < 500:
                return {
                    "status": "degraded",
                    "latency_ms": round(latency, 2),
                    "message": f"HTTP {response.status_code}",
                }
            return {
                "status": "error",
                "latency_ms": round(latency, 2),
                "message": f"HTTP {response.status_code}",
            }
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return {
                "status": "error",
                "latency_ms": round(latency, 2),
                "message": str(exc),
            }

    async def list_resources(self) -> list[dict[str, Any]]:
        """Return a descriptor for the root endpoint (REST APIs have no universal resource list).

        Subclasses or callers should pass a ``/`` path and inspect the
        response to enumerate actual resources.
        """
        return [
            {
                "id": "/",
                "name": "Root",
                "description": "REST API root endpoint",
                "url": self.config.get("base_url", ""),
            }
        ]

    async def read(
        self,
        resource_id: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Send a GET request to the given path.

        Args:
            resource_id: URL path relative to ``base_url``, e.g. ``"/users"``.
            params: Optional query parameters.

        Returns:
            Parsed JSON response body (dict or list).
        """
        try:
            client = await self._get_client()
            response = await client.get(resource_id, params=params or {})
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.error("REST API read failed for %s: %s", resource_id, exc)
            raise

    async def write(
        self,
        resource_id: str,
        data: Any,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a POST request to the given path.

        Args:
            resource_id: URL path relative to ``base_url``.
            data: JSON-serialisable payload.
            params: Optional query parameters.

        Returns:
            Dict with response body and status code.
        """
        try:
            client = await self._get_client()
            response = await client.post(resource_id, json=data, params=params or {})
            response.raise_for_status()
            try:
                body = response.json()
            except Exception:
                body = {"raw": response.text}
            return {
                "success": True,
                "status_code": response.status_code,
                "data": body,
            }
        except Exception as exc:
            logger.error("REST API write failed for %s: %s", resource_id, exc)
            raise

    async def get_schema(self, resource_id: str) -> dict[str, Any]:
        """Infer schema from a sample GET response.

        Performs a GET request and analyses the first object in the
        response to build a field-type map.

        Returns:
            Dict with ``{"endpoint": str, "fields": list[dict]}``.
        """
        try:
            data = await self.read(resource_id)
            sample: dict[str, Any] = {}
            if isinstance(data, list) and data:
                sample = data[0] if isinstance(data[0], dict) else {}
            elif isinstance(data, dict):
                sample = data

            fields = [
                {"name": key, "type": type(value).__name__}
                for key, value in sample.items()
            ]
            return {"endpoint": resource_id, "fields": fields}
        except Exception as exc:
            logger.error("REST API get_schema failed for %s: %s", resource_id, exc)
            raise


__all__ = ["RestApiConnector"]
