"""VaultSecretsManager — concrete implementation of the SecretsManager Protocol."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.interfaces.models.enterprise import (
    CertificateBundle,
    DynamicCredential,
    SecretMetadata,
)
from app.secrets.config import SecretsConfig
from app.secrets.exceptions import (
    CertificateError,
    RotationError,
    SecretAccessDeniedError,
    SecretNotFoundError,
    VaultConnectionError,
)

try:
    import hvac
    import hvac.exceptions
except ImportError:  # pragma: no cover
    hvac = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Module-level singleton
_instance: VaultSecretsManager | None = None
_lock = asyncio.Lock()


class _CacheEntry:
    """Internal cache entry with TTL tracking."""

    __slots__ = ("value", "created_at")

    def __init__(self, value: Any) -> None:
        self.value = value
        self.created_at = time.monotonic()

    def is_expired(self, ttl: int) -> bool:
        return (time.monotonic() - self.created_at) >= ttl


class VaultSecretsManager:
    """HashiCorp Vault implementation of the SecretsManager protocol.

    Provides tenant-isolated access to KV-v2, PKI, and dynamic credential
    engines via the ``hvac`` library.  Secrets are cached in-memory with a
    configurable TTL (will be replaced with Redis later).
    """

    def __init__(
        self,
        vault_addr: str,
        vault_token_path: str,
        namespace: str,
        *,
        config: SecretsConfig | None = None,
    ) -> None:
        if hvac is None:
            raise ImportError(
                "hvac is required for VaultSecretsManager. "
                "Install it with: pip install hvac"
            )

        self._config = config or SecretsConfig()
        self._vault_addr = vault_addr
        self._namespace = namespace
        self._vault_token = self._read_token(
            vault_token_path, config.vault_token if config else ""
        )
        self._cache: dict[str, _CacheEntry] = {}

        self._client = hvac.Client(
            url=self._vault_addr,
            token=self._vault_token,
            namespace=self._namespace,
        )

        logger.info(
            "VaultSecretsManager initialised",
            extra={"vault_addr": self._vault_addr, "namespace": self._namespace},
        )

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def get_secret(self, path: str, tenant_id: str) -> dict:
        """Retrieve a secret value by path, scoped to tenant."""
        self._validate_tenant_id(tenant_id)
        cache_key = f"{tenant_id}:{path}"

        entry = self._cache.get(cache_key)
        if entry is not None and not entry.is_expired(self._config.cache_ttl_seconds):
            logger.debug(
                "Cache hit for secret", extra={"path": path, "tenant_id": tenant_id}
            )
            return entry.value

        client = self._get_client(tenant_id)
        mount = self._config.vault_mount_point

        try:
            result = await asyncio.to_thread(
                client.secrets.kv.v2.read_secret_version,
                path=path,
                mount_point=mount,
            )
        except hvac.exceptions.InvalidPath as exc:
            raise SecretNotFoundError(path, tenant_id=tenant_id) from exc
        except hvac.exceptions.Forbidden as exc:
            raise SecretAccessDeniedError(path, tenant_id=tenant_id) from exc
        except Exception as exc:
            raise VaultConnectionError(str(exc)) from exc

        data: dict = result.get("data", {}).get("data", {})
        self._cache[cache_key] = _CacheEntry(data)
        return data

    async def put_secret(self, path: str, data: dict, tenant_id: str) -> SecretMetadata:
        """Store or update a secret, returning its metadata."""
        self._validate_tenant_id(tenant_id)
        client = self._get_client(tenant_id)
        mount = self._config.vault_mount_point

        try:
            result = await asyncio.to_thread(
                client.secrets.kv.v2.create_or_update_secret,
                path=path,
                secret=data,
                mount_point=mount,
            )
        except hvac.exceptions.Forbidden as exc:
            raise SecretAccessDeniedError(path, tenant_id=tenant_id) from exc
        except Exception as exc:
            raise VaultConnectionError(str(exc)) from exc

        metadata = result.get("data", {})

        # Invalidate cache for this path
        cache_key = f"{tenant_id}:{path}"
        self._cache.pop(cache_key, None)

        return SecretMetadata(
            path=path,
            version=metadata.get("version", 1),
            created_at=_parse_vault_time(metadata.get("created_time", "")),
        )

    async def delete_secret(self, path: str, tenant_id: str) -> None:
        """Soft-delete (destroy) a secret by path, scoped to tenant."""
        self._validate_tenant_id(tenant_id)
        client = self._get_client(tenant_id)
        mount = self._config.vault_mount_point

        try:
            await asyncio.to_thread(
                client.secrets.kv.v2.delete_metadata_and_all_versions,
                path=path,
                mount_point=mount,
            )
        except hvac.exceptions.InvalidPath as exc:
            raise SecretNotFoundError(path, tenant_id=tenant_id) from exc
        except hvac.exceptions.Forbidden as exc:
            raise SecretAccessDeniedError(path, tenant_id=tenant_id) from exc
        except Exception as exc:
            raise VaultConnectionError(str(exc)) from exc

        cache_key = f"{tenant_id}:{path}"
        self._cache.pop(cache_key, None)

        logger.info(
            "Secret deleted",
            extra={"path": path, "tenant_id": tenant_id},
        )

    async def list_secrets(self, prefix: str, tenant_id: str) -> list[SecretMetadata]:
        """List secret metadata under a given prefix."""
        self._validate_tenant_id(tenant_id)
        client = self._get_client(tenant_id)
        mount = self._config.vault_mount_point

        try:
            result = await asyncio.to_thread(
                client.secrets.kv.v2.list_secrets,
                path=prefix,
                mount_point=mount,
            )
        except hvac.exceptions.InvalidPath:
            return []
        except hvac.exceptions.Forbidden as exc:
            raise SecretAccessDeniedError(prefix, tenant_id=tenant_id) from exc
        except Exception as exc:
            raise VaultConnectionError(str(exc)) from exc

        keys: list[str] = result.get("data", {}).get("keys", [])
        return [
            SecretMetadata(
                path=f"{prefix.rstrip('/')}/{key}",
                version=0,
                created_at=datetime.now(timezone.utc),
            )
            for key in keys
        ]

    async def rotate_secret(self, path: str, tenant_id: str) -> SecretMetadata:
        """Create a new version of a secret with rotation_policy metadata."""
        self._validate_tenant_id(tenant_id)

        try:
            current = await self.get_secret(path, tenant_id)
        except SecretNotFoundError:
            raise RotationError(path, reason="Secret does not exist")

        current["_rotated_at"] = datetime.now(timezone.utc).isoformat()

        meta = await self.put_secret(path, current, tenant_id)
        meta.rotation_policy = "auto"

        logger.info(
            "Secret rotated",
            extra={
                "path": path,
                "tenant_id": tenant_id,
                "new_version": meta.version,
            },
        )
        return meta

    async def issue_certificate(
        self, common_name: str, tenant_id: str, ttl: str
    ) -> CertificateBundle:
        """Issue a TLS certificate via the PKI secrets engine."""
        self._validate_tenant_id(tenant_id)
        client = self._get_client(tenant_id)

        try:
            result = await asyncio.to_thread(
                client.secrets.pki.generate_certificate,
                name="default",
                common_name=common_name,
                extra_params={"ttl": ttl},
                mount_point="pki",
            )
        except hvac.exceptions.Forbidden as exc:
            raise SecretAccessDeniedError(
                f"pki/{common_name}", tenant_id=tenant_id
            ) from exc
        except Exception as exc:
            raise CertificateError(common_name, reason=str(exc)) from exc

        cert_data = result.get("data", {})
        expires_str = cert_data.get("expiration")
        expires_at = (
            datetime.fromtimestamp(int(expires_str), tz=timezone.utc)
            if expires_str
            else None
        )

        return CertificateBundle(
            cert=cert_data.get("certificate", ""),
            private_key=cert_data.get("private_key", ""),
            ca_chain=cert_data.get("ca_chain", []),
            serial=cert_data.get("serial_number", ""),
            expires_at=expires_at,
        )

    async def get_dynamic_credential(
        self, engine: str, role: str, tenant_id: str
    ) -> DynamicCredential:
        """Generate a short-lived credential from a secrets engine."""
        self._validate_tenant_id(tenant_id)
        client = self._get_client(tenant_id)

        try:
            result = await asyncio.to_thread(
                client.secrets.database.generate_credentials
                if engine == "database"
                else lambda role, mount_point: client.read(
                    f"{mount_point}/creds/{role}"
                ),
                role,
                mount_point=engine,
            )
        except hvac.exceptions.Forbidden as exc:
            raise SecretAccessDeniedError(
                f"{engine}/{role}", tenant_id=tenant_id
            ) from exc
        except Exception as exc:
            raise VaultConnectionError(str(exc)) from exc

        cred_data = result.get("data", {})
        # Build credential from Vault dynamic engine response
        cred_fields = {
            "username": cred_data.get("username", ""),
            "password": cred_data.get("password", ""),
            "lease_id": result.get("lease_id", ""),
            "lease_duration": result.get("lease_duration", 0),
            "renewable": result.get("renewable", False),
        }
        return DynamicCredential(**cred_fields)

    async def health(self) -> dict:
        """Return Vault cluster health status."""
        try:
            status = await asyncio.to_thread(self._client.sys.read_seal_status)
            return {
                "status": "healthy",
                "initialized": status.get("initialized", False),
                "sealed": status.get("sealed", True),
                "cluster_name": status.get("cluster_name", ""),
            }
        except Exception as exc:
            logger.warning("Vault health check failed", extra={"error": str(exc)})
            return {"status": "unhealthy", "error": str(exc)}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_tenant_id(self, tenant_id: str) -> None:
        """Raise ValueError if tenant_id is missing or empty."""
        if not tenant_id:
            raise ValueError("tenant_id must not be None or empty")

    def _get_tenant_namespace(self, tenant_id: str) -> str:
        """Map a tenant_id to a Vault namespace path."""
        return f"{self._namespace}/{tenant_id}"

    def _get_client(self, tenant_id: str) -> hvac.Client:
        """Return an hvac Client scoped to the tenant's namespace."""
        tenant_ns = self._get_tenant_namespace(tenant_id)
        return hvac.Client(
            url=self._vault_addr,
            token=self._vault_token,
            namespace=tenant_ns,
        )

    @staticmethod
    def _read_token(token_path: str, direct_token: str = "") -> str:
        """Read the Vault token from a file path or direct value."""
        if direct_token:
            return direct_token
        path = Path(token_path)
        if not path.exists():
            logger.warning(
                "Vault token file not found, using empty token",
                extra={"token_path": token_path},
            )
            return ""
        return path.read_text().strip()


# ------------------------------------------------------------------
# Factory / singleton
# ------------------------------------------------------------------


class _StubSecretsManager:
    """In-memory stub used when Vault (hvac) is unavailable."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def put_secret(
        self,
        path: str,
        data: dict[str, Any],
        tenant_id: str = "",
    ) -> SecretMetadata:
        from uuid import uuid4

        key = f"{tenant_id}/{path}"
        now = datetime.now(timezone.utc)
        meta = SecretMetadata(
            id=str(uuid4()),
            path=path,
            version=1,
            created_at=now,
            updated_at=now,
        )
        self._store[key] = {"data": data, "meta": meta}
        return meta

    async def get_secret(
        self,
        path: str,
        tenant_id: str = "",
        version: int | None = None,
    ) -> dict[str, Any]:
        key = f"{tenant_id}/{path}"
        entry = self._store.get(key)
        if not entry:
            raise SecretNotFoundError(path)
        return entry["data"]

    async def delete_secret(self, path: str, tenant_id: str = "") -> None:
        key = f"{tenant_id}/{path}"
        self._store.pop(key, None)

    async def list_secrets(
        self,
        prefix: str = "",
        tenant_id: str = "",
    ) -> list[SecretMetadata]:
        results = []
        tp = f"{tenant_id}/"
        for key, entry in self._store.items():
            if key.startswith(tp) and (
                not prefix or entry["meta"].path.startswith(prefix)
            ):
                results.append(entry["meta"])
        return results

    async def rotate_secret(
        self,
        path: str,
        tenant_id: str = "",
        reason: str = "",
    ) -> SecretMetadata:
        key = f"{tenant_id}/{path}"
        entry = self._store.get(key)
        if not entry:
            raise SecretNotFoundError(path)
        now = datetime.now(timezone.utc)
        entry["meta"] = SecretMetadata(
            id=entry["meta"].id,
            path=path,
            version=entry["meta"].version + 1,
            created_at=entry["meta"].created_at,
            updated_at=now,
        )
        return entry["meta"]

    async def health(self) -> dict:
        """Return stub health status."""
        return {
            "status": "stub",
            "initialized": False,
            "sealed": False,
            "cluster_name": "",
        }

    async def issue_certificate(self, *_: Any, **__: Any) -> CertificateBundle:
        raise CertificateError("Vault PKI not available in stub mode")

    async def get_dynamic_credential(self, *_: Any, **__: Any) -> DynamicCredential:
        raise SecretAccessDeniedError("Dynamic credentials not available in stub mode")


async def get_secrets_manager(
    config: SecretsConfig | None = None,
) -> VaultSecretsManager | _StubSecretsManager:
    """Return (or create) the singleton VaultSecretsManager instance.

    Thread-safe via an asyncio lock.  Config values are read from
    environment variables prefixed ``ARCHON_`` if no explicit config
    is provided.

    Falls back to an in-memory stub when hvac is not installed or
    Vault is unreachable.
    """
    global _instance  # noqa: PLW0603

    if _instance is not None:
        return _instance

    async with _lock:
        # Double-checked locking
        if _instance is not None:
            return _instance

        if hvac is None:
            logger.warning(
                "Vault client unavailable — using in-memory secrets stub",
                extra={
                    "reason": "hvac package is not installed",
                    "impact": "secrets will not persist across restarts",
                    "action_required": "install hvac and configure Vault to enable persistent secrets",
                },
            )
            _stub = _StubSecretsManager()
            _instance = _stub  # type: ignore[assignment]
            return _stub

        cfg = config or SecretsConfig()
        try:
            mgr = VaultSecretsManager(
                vault_addr=cfg.vault_addr,
                vault_token_path=cfg.vault_token_path,
                namespace=cfg.vault_namespace,
                config=cfg,
            )
            _instance = mgr
            return _instance
        except Exception as exc:
            logger.warning(
                "Vault unreachable — using in-memory secrets stub",
                extra={
                    "reason": str(exc),
                    "impact": "secrets will not persist across restarts",
                    "action_required": "verify Vault address, token, and network connectivity",
                },
            )
            _stub = _StubSecretsManager()
            _instance = _stub  # type: ignore[assignment]
            return _stub


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _parse_vault_time(raw: str) -> datetime:
    """Parse a Vault RFC-3339 timestamp, falling back to utcnow."""
    if not raw:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


__all__ = ["VaultSecretsManager", "get_secrets_manager"]
