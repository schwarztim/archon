"""Enterprise secrets management API routes with Vault-backed storage."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field as PField

from app.interfaces.models.enterprise import AuthenticatedUser, SecretMetadata
from app.middleware.auth import require_auth
from app.middleware.rbac import require_permission
from app.models.audit import EnterpriseAuditEvent
from app.models.secrets import SecretRegistration
from app.secrets.manager import VaultSecretsManager, get_secrets_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Secrets"])


# ── Request / response schemas ──────────────────────────────────────


class SecretCreate(BaseModel):
    """Payload for creating or storing a secret."""

    path: str
    data: dict[str, Any]
    secret_type: str = "static"  # static | dynamic | pki
    rotation_policy_days: int | None = None


class SecretUpdate(BaseModel):
    """Payload for updating a secret."""

    data: dict[str, Any]
    rotation_policy_days: int | None = None


class RotateRequest(BaseModel):
    """Payload for triggering secret rotation."""

    reason: str = ""


class PKICertificateRequest(BaseModel):
    """Payload for issuing a PKI certificate."""

    common_name: str
    ttl: str = "720h"


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _audit_event(
    user: AuthenticatedUser,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> EnterpriseAuditEvent:
    """Create an audit event record for a state-changing operation."""
    return EnterpriseAuditEvent(
        tenant_id=UUID(user.tenant_id),
        user_id=UUID(user.id),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        session_id=user.session_id,
    )


# ── Routes ───────────────────────────────────────────────────────────


@router.post("/secrets", status_code=status.HTTP_201_CREATED)
async def create_secret(
    body: SecretCreate,
    user: AuthenticatedUser = Depends(require_permission("secrets", "create")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Create or store a new secret in the tenant's Vault namespace.

    Requires ``secrets:create`` permission. The secret value is stored
    in Vault and only metadata is persisted in the application database.
    """
    request_id = str(uuid4())

    meta = await secrets.put_secret(body.path, body.data, user.tenant_id)

    audit = _audit_event(
        user, "secret.created", "secret", body.path,
        {"secret_type": body.secret_type, "path": body.path},
    )
    logger.info(
        "Secret created",
        extra={
            "request_id": request_id,
            "tenant_id": user.tenant_id,
            "path": body.path,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": meta.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@router.get("/secrets")
async def list_secrets(
    prefix: str = Query(default="", description="Path prefix filter"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(require_permission("secrets", "read")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """List secret metadata for the authenticated user's tenant.

    Requires ``secrets:read`` permission. Returns metadata only — secret
    values are never included in list responses.
    """
    all_secrets = await secrets.list_secrets(prefix, user.tenant_id)
    total = len(all_secrets)
    page = all_secrets[offset : offset + limit]

    return {
        "data": [s.model_dump(mode="json") for s in page],
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


@router.get("/secrets/{secret_id}")
async def get_secret(
    secret_id: str,
    user: AuthenticatedUser = Depends(require_permission("secrets", "read")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Retrieve a specific secret's metadata by path.

    Requires ``secrets:read`` permission. The actual secret value is
    returned from Vault, scoped to the user's tenant.
    """
    data = await secrets.get_secret(secret_id, user.tenant_id)

    return {
        "data": data,
        "meta": _meta(),
    }


@router.put("/secrets/{secret_id}")
async def update_secret(
    secret_id: str,
    body: SecretUpdate,
    user: AuthenticatedUser = Depends(require_permission("secrets", "update")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Update an existing secret's value.

    Requires ``secrets:update`` permission. Creates a new version in
    Vault's KV-v2 engine.
    """
    request_id = str(uuid4())

    meta = await secrets.put_secret(secret_id, body.data, user.tenant_id)

    audit = _audit_event(
        user, "secret.updated", "secret", secret_id,
        {"new_version": meta.version},
    )
    logger.info(
        "Secret updated",
        extra={
            "request_id": request_id,
            "tenant_id": user.tenant_id,
            "path": secret_id,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": meta.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@router.delete("/secrets/{secret_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(
    secret_id: str,
    user: AuthenticatedUser = Depends(require_permission("secrets", "delete")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> None:
    """Delete a secret and all its versions.

    Requires ``secrets:delete`` permission. Performs a metadata-and-all-versions
    delete in Vault's KV-v2 engine.
    """
    request_id = str(uuid4())

    await secrets.delete_secret(secret_id, user.tenant_id)

    audit = _audit_event(
        user, "secret.deleted", "secret", secret_id,
    )
    logger.info(
        "Secret deleted",
        extra={
            "request_id": request_id,
            "tenant_id": user.tenant_id,
            "path": secret_id,
            "audit_id": str(audit.id),
        },
    )


@router.post("/secrets/{secret_id}/rotate")
async def rotate_secret(
    secret_id: str,
    body: RotateRequest,
    user: AuthenticatedUser = Depends(require_permission("secrets", "admin")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Trigger rotation for a secret.

    Requires ``secrets:admin`` permission. Creates a new version with
    rotation metadata attached.
    """
    request_id = str(uuid4())

    meta = await secrets.rotate_secret(secret_id, user.tenant_id)

    audit = _audit_event(
        user, "secret.rotated", "secret", secret_id,
        {"new_version": meta.version, "reason": body.reason},
    )
    logger.info(
        "Secret rotated",
        extra={
            "request_id": request_id,
            "tenant_id": user.tenant_id,
            "path": secret_id,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": meta.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@router.post("/secrets/pki/certificates", status_code=status.HTTP_201_CREATED)
async def issue_pki_certificate(
    body: PKICertificateRequest,
    user: AuthenticatedUser = Depends(require_permission("secrets", "admin")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Issue a PKI certificate via the Vault PKI secrets engine.

    Requires ``secrets:admin`` permission. Returns the certificate bundle
    including cert, private key, and CA chain.
    """
    request_id = str(uuid4())

    bundle = await secrets.issue_certificate(
        body.common_name, user.tenant_id, body.ttl,
    )

    audit = _audit_event(
        user, "certificate.issued", "pki_certificate", bundle.serial,
        {"common_name": body.common_name, "ttl": body.ttl},
    )
    logger.info(
        "PKI certificate issued",
        extra={
            "request_id": request_id,
            "tenant_id": user.tenant_id,
            "common_name": body.common_name,
            "serial": bundle.serial,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": bundle.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }
