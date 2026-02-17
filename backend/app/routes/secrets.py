"""Enterprise secrets management API routes with Vault-backed storage."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
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
from app.services.secret_access_logger import (
    SecretAccessEntry,
    SecretAccessLogger,
    get_access_logger,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Secrets"])


# ── Request / response schemas ──────────────────────────────────────


class SecretCreate(BaseModel):
    """Payload for creating or storing a secret."""

    path: str
    data: dict[str, Any]
    secret_type: str = "custom"  # api_key | oauth_token | password | certificate | custom
    rotation_policy_days: int | None = None
    auto_rotate: bool = False
    notify_before_days: int = 14


class SecretUpdate(BaseModel):
    """Payload for updating a secret."""

    data: dict[str, Any]
    rotation_policy_days: int | None = None


class RotateRequest(BaseModel):
    """Payload for triggering secret rotation."""

    reason: str = ""
    new_value: dict[str, Any] | None = None


class PKICertificateRequest(BaseModel):
    """Payload for issuing a PKI certificate."""

    common_name: str
    ttl: str = "720h"


class RotationPolicyUpdate(BaseModel):
    """Payload for setting/updating a rotation policy on a secret."""

    rotation_policy_days: int = PField(ge=1, le=365, description="Days between rotations")
    auto_rotate: bool = True
    notify_before_days: int = PField(default=14, ge=0, le=90)


class VaultStatusResponse(BaseModel):
    """Vault connection status response."""

    mode: str  # connected | stub | sealed | disconnected
    initialized: bool = False
    sealed: bool = False
    cluster_name: str = ""
    message: str = ""


class RotationDashboardItem(BaseModel):
    """A secret with its rotation status for the dashboard."""

    path: str
    secret_type: str = "custom"
    rotation_status: str  # approaching | overdue | recently_rotated | never_rotated | ok
    last_rotated_at: str | None = None
    next_rotation_at: str | None = None
    days_until_rotation: int | None = None


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


# ── In-memory registration store (production would use DB) ──────────

_registrations: dict[str, dict[str, Any]] = {}


def _get_registration(tenant_id: str, path: str) -> dict[str, Any] | None:
    """Look up a secret registration by tenant+path."""
    return _registrations.get(f"{tenant_id}:{path}")


def _set_registration(tenant_id: str, path: str, reg: dict[str, Any]) -> None:
    """Store/update a secret registration."""
    _registrations[f"{tenant_id}:{path}"] = reg


def _delete_registration(tenant_id: str, path: str) -> None:
    """Remove a secret registration."""
    _registrations.pop(f"{tenant_id}:{path}", None)


# ── Routes ───────────────────────────────────────────────────────────


@router.post("/secrets", status_code=status.HTTP_201_CREATED)
async def create_secret(
    body: SecretCreate,
    user: AuthenticatedUser = Depends(require_permission("secrets", "create")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
    access_log: SecretAccessLogger = Depends(get_access_logger),
) -> dict[str, Any]:
    """Create or store a new secret in the tenant's Vault namespace.

    Requires ``secrets:create`` permission. The secret value is stored
    in Vault and only metadata is persisted in the application database.
    """
    request_id = str(uuid4())

    meta = await secrets.put_secret(body.path, body.data, user.tenant_id)
    meta.secret_type = body.secret_type

    now = datetime.now(timezone.utc)
    next_rot = None
    if body.rotation_policy_days:
        next_rot = (now + timedelta(days=body.rotation_policy_days)).isoformat()

    _set_registration(user.tenant_id, body.path, {
        "secret_type": body.secret_type,
        "rotation_policy_days": body.rotation_policy_days,
        "auto_rotate": body.auto_rotate,
        "notify_before_days": body.notify_before_days,
        "last_rotated_at": None,
        "next_rotation_at": next_rot,
        "expires_at": None,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "created_by": user.id,
    })

    access_log.log_access(
        tenant_id=user.tenant_id,
        secret_path=body.path,
        user_id=user.id,
        user_email=user.email,
        action="write",
        component="secrets_api",
    )

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
    values are never included in list responses. Includes type badges
    and rotation status.
    """
    all_secrets = await secrets.list_secrets(prefix, user.tenant_id)
    total = len(all_secrets)
    page = all_secrets[offset : offset + limit]

    enriched = []
    for s in page:
        reg = _get_registration(user.tenant_id, s.path)
        if reg:
            s.secret_type = reg.get("secret_type", "custom")
            s.rotation_policy_days = reg.get("rotation_policy_days")
            s.auto_rotate = reg.get("auto_rotate", False)
            if reg.get("last_rotated_at"):
                s.last_rotated_at = datetime.fromisoformat(reg["last_rotated_at"])
        enriched.append(s.model_dump(mode="json"))

    return {
        "data": enriched,
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


@router.get("/secrets/status")
async def get_vault_status(
    user: AuthenticatedUser = Depends(require_permission("secrets", "read")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Return Vault connection status.

    Reports whether the backend is connected to a real Vault instance,
    running in stub mode, or if Vault is sealed/disconnected.
    """
    from app.secrets.manager import _StubSecretsManager

    if isinstance(secrets, _StubSecretsManager):
        return {
            "data": VaultStatusResponse(
                mode="stub",
                message="Running in stub mode — secrets are NOT persisted. Configure Vault for production use.",
            ).model_dump(),
            "meta": _meta(),
        }

    try:
        health = await secrets.health()
        if health.get("sealed"):
            mode = "sealed"
            message = "Vault is sealed — unseal required."
        elif health.get("status") == "healthy":
            mode = "connected"
            message = "Vault is connected and healthy."
        else:
            mode = "disconnected"
            message = health.get("error", "Vault health check failed.")

        return {
            "data": VaultStatusResponse(
                mode=mode,
                initialized=health.get("initialized", False),
                sealed=health.get("sealed", False),
                cluster_name=health.get("cluster_name", ""),
                message=message,
            ).model_dump(),
            "meta": _meta(),
        }
    except Exception as exc:
        return {
            "data": VaultStatusResponse(
                mode="disconnected",
                message=f"Cannot reach Vault: {exc}",
            ).model_dump(),
            "meta": _meta(),
        }


@router.get("/secrets/rotation-dashboard")
async def get_rotation_dashboard(
    user: AuthenticatedUser = Depends(require_permission("secrets", "read")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Return secrets grouped by rotation status for the dashboard.

    Categories: approaching, overdue, recently_rotated, never_rotated, ok.
    """
    all_secrets = await secrets.list_secrets("", user.tenant_id)
    now = datetime.now(timezone.utc)
    items: list[dict[str, Any]] = []

    for s in all_secrets:
        reg = _get_registration(user.tenant_id, s.path)
        secret_type = reg.get("secret_type", "custom") if reg else "custom"
        policy_days = reg.get("rotation_policy_days") if reg else None
        last_rotated_str = reg.get("last_rotated_at") if reg else None
        next_rot_str = reg.get("next_rotation_at") if reg else None

        if not policy_days:
            rot_status = "never_rotated" if not last_rotated_str else "ok"
            days_until = None
        else:
            if next_rot_str:
                next_rot = datetime.fromisoformat(next_rot_str)
                if next_rot.tzinfo is None:
                    next_rot = next_rot.replace(tzinfo=timezone.utc)
                diff = (next_rot - now).days
                days_until = diff
                if diff < 0:
                    rot_status = "overdue"
                elif diff <= (reg.get("notify_before_days", 14) if reg else 14):
                    rot_status = "approaching"
                else:
                    rot_status = "ok"
            else:
                rot_status = "never_rotated"
                days_until = None

        if last_rotated_str and rot_status == "ok":
            last_dt = datetime.fromisoformat(last_rotated_str)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if (now - last_dt).days <= 7:
                rot_status = "recently_rotated"

        items.append(RotationDashboardItem(
            path=s.path,
            secret_type=secret_type,
            rotation_status=rot_status,
            last_rotated_at=last_rotated_str,
            next_rotation_at=next_rot_str,
            days_until_rotation=days_until,
        ).model_dump())

    return {
        "data": items,
        "meta": _meta(),
    }


@router.get("/secrets/{secret_id}")
async def get_secret(
    secret_id: str,
    user: AuthenticatedUser = Depends(require_permission("secrets", "read")),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
    access_log: SecretAccessLogger = Depends(get_access_logger),
) -> dict[str, Any]:
    """Retrieve a specific secret's metadata by path.

    Requires ``secrets:read`` permission. The actual secret value is
    returned from Vault, scoped to the user's tenant.
    """
    data = await secrets.get_secret(secret_id, user.tenant_id)

    access_log.log_access(
        tenant_id=user.tenant_id,
        secret_path=secret_id,
        user_id=user.id,
        user_email=user.email,
        action="read",
        component="secrets_api",
    )

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
    access_log: SecretAccessLogger = Depends(get_access_logger),
) -> dict[str, Any]:
    """Update an existing secret's value.

    Requires ``secrets:update`` permission. Creates a new version in
    Vault's KV-v2 engine.
    """
    request_id = str(uuid4())

    meta = await secrets.put_secret(secret_id, body.data, user.tenant_id)

    reg = _get_registration(user.tenant_id, secret_id)
    if reg:
        reg["updated_at"] = datetime.now(timezone.utc).isoformat()
        if body.rotation_policy_days is not None:
            reg["rotation_policy_days"] = body.rotation_policy_days
        _set_registration(user.tenant_id, secret_id, reg)

    access_log.log_access(
        tenant_id=user.tenant_id,
        secret_path=secret_id,
        user_id=user.id,
        user_email=user.email,
        action="write",
        component="secrets_api",
    )

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
    access_log: SecretAccessLogger = Depends(get_access_logger),
) -> None:
    """Delete a secret and all its versions.

    Requires ``secrets:delete`` permission. Performs a metadata-and-all-versions
    delete in Vault's KV-v2 engine.
    """
    request_id = str(uuid4())

    await secrets.delete_secret(secret_id, user.tenant_id)
    _delete_registration(user.tenant_id, secret_id)

    access_log.log_access(
        tenant_id=user.tenant_id,
        secret_path=secret_id,
        user_id=user.id,
        user_email=user.email,
        action="delete",
        component="secrets_api",
    )

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
    access_log: SecretAccessLogger = Depends(get_access_logger),
) -> dict[str, Any]:
    """Trigger rotation for a secret.

    Requires ``secrets:admin`` permission. If ``new_value`` is provided in the
    request body, that value is used; otherwise the existing value is re-versioned
    with rotation metadata.
    """
    request_id = str(uuid4())

    if body.new_value is not None:
        meta = await secrets.put_secret(secret_id, body.new_value, user.tenant_id)
        meta.rotation_policy = "manual"
    else:
        meta = await secrets.rotate_secret(secret_id, user.tenant_id)

    now = datetime.now(timezone.utc)
    reg = _get_registration(user.tenant_id, secret_id)
    if reg:
        reg["last_rotated_at"] = now.isoformat()
        if reg.get("rotation_policy_days"):
            reg["next_rotation_at"] = (now + timedelta(days=reg["rotation_policy_days"])).isoformat()
        reg["updated_at"] = now.isoformat()
        _set_registration(user.tenant_id, secret_id, reg)

    access_log.log_access(
        tenant_id=user.tenant_id,
        secret_path=secret_id,
        user_id=user.id,
        user_email=user.email,
        action="rotate",
        component="secrets_api",
        details=body.reason or "manual rotation",
    )

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


@router.get("/secrets/{secret_id}/access-log")
async def get_secret_access_log(
    secret_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(require_permission("secrets", "read")),
    access_log: SecretAccessLogger = Depends(get_access_logger),
) -> dict[str, Any]:
    """Return access history for a specific secret.

    Requires ``secrets:read`` permission. Shows who accessed the secret,
    when, and what action was performed.
    """
    entries, total = access_log.get_access_log(
        secret_id, user.tenant_id, limit=limit, offset=offset,
    )
    return {
        "data": [e.model_dump() for e in entries],
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


@router.put("/secrets/{secret_id}/rotation-policy")
async def set_rotation_policy(
    secret_id: str,
    body: RotationPolicyUpdate,
    user: AuthenticatedUser = Depends(require_permission("secrets", "admin")),
    access_log: SecretAccessLogger = Depends(get_access_logger),
) -> dict[str, Any]:
    """Set or update the auto-rotation policy for a secret.

    Requires ``secrets:admin`` permission. Configures rotation period
    and notification settings.
    """
    request_id = str(uuid4())
    now = datetime.now(timezone.utc)

    reg = _get_registration(user.tenant_id, secret_id) or {
        "secret_type": "custom",
        "created_at": now.isoformat(),
        "created_by": user.id,
        "last_rotated_at": None,
    }
    reg["rotation_policy_days"] = body.rotation_policy_days
    reg["auto_rotate"] = body.auto_rotate
    reg["notify_before_days"] = body.notify_before_days
    reg["updated_at"] = now.isoformat()

    last_rot = reg.get("last_rotated_at")
    base_time = datetime.fromisoformat(last_rot) if last_rot else now
    if base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=timezone.utc)
    reg["next_rotation_at"] = (base_time + timedelta(days=body.rotation_policy_days)).isoformat()

    _set_registration(user.tenant_id, secret_id, reg)

    access_log.log_access(
        tenant_id=user.tenant_id,
        secret_path=secret_id,
        user_id=user.id,
        user_email=user.email,
        action="write",
        component="rotation_policy",
        details=f"Set rotation policy: {body.rotation_policy_days} days",
    )

    audit = _audit_event(
        user, "rotation_policy.set", "secret", secret_id,
        {"rotation_policy_days": body.rotation_policy_days, "auto_rotate": body.auto_rotate},
    )
    logger.info(
        "Rotation policy set",
        extra={
            "request_id": request_id,
            "tenant_id": user.tenant_id,
            "path": secret_id,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": {
            "path": secret_id,
            "rotation_policy_days": body.rotation_policy_days,
            "auto_rotate": body.auto_rotate,
            "notify_before_days": body.notify_before_days,
            "next_rotation_at": reg["next_rotation_at"],
        },
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
