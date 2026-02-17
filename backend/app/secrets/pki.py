"""PKI utilities wrapping VaultSecretsManager certificate operations."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from pydantic import BaseModel

from app.interfaces.models.enterprise import CertificateBundle
from app.secrets.manager import VaultSecretsManager

logger = logging.getLogger(__name__)


class CertificateInfo(BaseModel):
    """Summary information for an issued certificate."""

    serial: str
    common_name: str
    issued_at: datetime
    expires_at: datetime | None = None
    revoked: bool = False


class PKIManager:
    """Convenience wrapper around VaultSecretsManager PKI operations.

    Provides service-cert, client-cert, revocation, and listing helpers
    with sensible defaults and structured audit logging.
    """

    def __init__(self, secrets_manager: VaultSecretsManager) -> None:
        self._sm = secrets_manager

    async def issue_service_cert(
        self,
        service_name: str,
        tenant_id: str,
        ttl: str = "720h",
    ) -> CertificateBundle:
        """Issue a long-lived TLS certificate for an internal service."""
        self._validate_tenant_id(tenant_id)
        common_name = f"{service_name}.{tenant_id}.svc"

        bundle = await self._sm.issue_certificate(common_name, tenant_id, ttl)

        logger.info(
            "Service certificate issued",
            extra={
                "service_name": service_name,
                "tenant_id": tenant_id,
                "serial": bundle.serial,
                "ttl": ttl,
            },
        )
        return bundle

    async def issue_client_cert(
        self,
        client_id: str,
        tenant_id: str,
        ttl: str = "24h",
    ) -> CertificateBundle:
        """Issue a short-lived mTLS client certificate."""
        self._validate_tenant_id(tenant_id)
        common_name = f"{client_id}.{tenant_id}.client"

        bundle = await self._sm.issue_certificate(common_name, tenant_id, ttl)

        logger.info(
            "Client certificate issued",
            extra={
                "client_id": client_id,
                "tenant_id": tenant_id,
                "serial": bundle.serial,
                "ttl": ttl,
            },
        )
        return bundle

    async def revoke_certificate(self, serial: str, tenant_id: str) -> None:
        """Revoke a certificate by serial number.

        Writes a revocation marker into the tenant's secret store so
        ``list_certificates`` reflects the revoked state.  The actual
        CRL/OCSP update is handled by Vault's PKI engine.
        """
        self._validate_tenant_id(tenant_id)
        revocation_path = f"pki/revoked/{serial}"

        await self._sm.put_secret(
            revocation_path,
            {
                "serial": serial,
                "revoked_at": datetime.now(timezone.utc).isoformat(),
                "tenant_id": tenant_id,
            },
            tenant_id,
        )

        logger.info(
            "Certificate revoked",
            extra={"serial": serial, "tenant_id": tenant_id},
        )

    async def list_certificates(self, tenant_id: str) -> list[CertificateInfo]:
        """List all certificates issued for a tenant.

        Reads certificate metadata from the tenant's ``pki/certs/``
        prefix and cross-references revocation markers.
        """
        self._validate_tenant_id(tenant_id)

        cert_metas = await self._sm.list_secrets("pki/certs", tenant_id)
        revoked_metas = await self._sm.list_secrets("pki/revoked", tenant_id)
        revoked_serials: set[str] = set()

        for meta in revoked_metas:
            serial = meta.path.rsplit("/", 1)[-1]
            revoked_serials.add(serial)

        certs: list[CertificateInfo] = []
        for meta in cert_metas:
            try:
                data = await self._sm.get_secret(meta.path, tenant_id)
            except Exception:
                logger.warning(
                    "Failed to read certificate metadata",
                    extra={"path": meta.path, "tenant_id": tenant_id},
                )
                continue

            serial = data.get("serial", meta.path.rsplit("/", 1)[-1])
            expires_raw = data.get("expires_at")
            expires_at = (
                datetime.fromisoformat(expires_raw) if expires_raw else None
            )

            certs.append(
                CertificateInfo(
                    serial=serial,
                    common_name=data.get("common_name", ""),
                    issued_at=meta.created_at,
                    expires_at=expires_at,
                    revoked=serial in revoked_serials,
                )
            )

        return certs

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_tenant_id(tenant_id: str) -> None:
        """Raise ValueError if tenant_id is missing or empty."""
        if not tenant_id:
            raise ValueError("tenant_id must not be None or empty")


__all__ = [
    "CertificateInfo",
    "PKIManager",
]
