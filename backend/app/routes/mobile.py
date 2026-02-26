"""Mobile SDK REST routes — device management, biometric auth, push, offline sync."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import require_auth
from app.middleware.rbac import check_permission
from app.models.audit import EnterpriseAuditEvent
from app.models.mobile import (
    BiometricProof,
    DeviceRegistration,
    OfflineAction,
    PushNotification,
)
from app.secrets.manager import VaultSecretsManager, get_secrets_manager
from app.services.mobile_service import MobileService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/mobile", tags=["Mobile SDK"])


# ── Request / response schemas ──────────────────────────────────────


class BiometricAuthRequest(BaseModel):
    """Biometric authentication request body."""

    device_id: str = Field(..., min_length=1)
    proof: BiometricProof


class SAMLMobileAuthRequest(BaseModel):
    """SAML SSO mobile authentication request body."""

    saml_response: str = Field(..., min_length=1)


class RefreshSessionRequest(BaseModel):
    """Mobile session refresh request body."""

    device_id: str = Field(..., min_length=1)
    refresh_token: str = Field(..., min_length=1)


class SendPushRequest(BaseModel):
    """Push notification send request body."""

    user_id: str = Field(..., min_length=1)
    notification: PushNotification


class SyncOfflineRequest(BaseModel):
    """Offline action sync request body."""

    actions: list[OfflineAction] = Field(default_factory=list)


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _audit_event(
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    *,
    user: AuthenticatedUser | None = None,
    tenant_id: str | None = None,
) -> EnterpriseAuditEvent:
    """Create an audit event for mobile operations."""
    resolved_tenant = tenant_id or (user.tenant_id if user else "")
    return EnterpriseAuditEvent(
        tenant_id=UUID(resolved_tenant) if resolved_tenant else UUID(int=0),
        user_id=UUID(user.id) if user else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        session_id=user.session_id if user else None,
    )


async def _get_mobile_service(
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> MobileService:
    """FastAPI dependency to construct a MobileService instance."""
    return MobileService(secrets_manager=secrets)


# ── Routes ───────────────────────────────────────────────────────────


@router.post("/devices", status_code=status.HTTP_201_CREATED)
async def register_device(
    body: DeviceRegistration,
    user: AuthenticatedUser = Depends(require_auth),
    service: MobileService = Depends(_get_mobile_service),
) -> dict[str, Any]:
    """Register a new mobile device for the authenticated user.

    Stores device metadata and push token, returns a DeviceSession.
    """
    request_id = str(uuid4())

    session = await service.register_device(
        tenant_id=user.tenant_id,
        user=user,
        device_info=body,
    )

    audit = _audit_event(
        "mobile.device.registered", "mobile_device", session.device_id,
        {"platform": body.platform.value, "device_name": body.device_name},
        user=user,
    )
    logger.info(
        "Mobile device registered",
        extra={
            "request_id": request_id,
            "tenant_id": user.tenant_id,
            "device_id": session.device_id,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": session.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@router.post("/auth/biometric")
async def biometric_auth(
    body: BiometricAuthRequest,
    service: MobileService = Depends(_get_mobile_service),
) -> dict[str, Any]:
    """Authenticate via biometric proof (unauthenticated — initial auth endpoint).

    Validates the signed challenge and returns short-lived session tokens.
    """
    request_id = str(uuid4())
    tenant_id = body.proof.device_id.split("-")[0] if "-" in body.proof.device_id else ""

    try:
        # Resolve tenant from device record via Vault lookup
        result = await service.authenticate_biometric(
            tenant_id=tenant_id,
            device_id=body.device_id,
            biometric_proof=body.proof,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@router.post("/auth/saml")
async def saml_mobile_auth(
    body: SAMLMobileAuthRequest,
    service: MobileService = Depends(_get_mobile_service),
) -> dict[str, Any]:
    """Authenticate via SAML SSO on a mobile device (unauthenticated — initial auth endpoint).

    Processes the SAML response and returns mobile session tokens.
    """
    request_id = str(uuid4())

    try:
        result = await service.authenticate_saml_mobile(
            tenant_id="",  # Extracted from SAML response during processing
            saml_response=body.saml_response,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@router.post("/auth/refresh")
async def refresh_session(
    body: RefreshSessionRequest,
    service: MobileService = Depends(_get_mobile_service),
) -> dict[str, Any]:
    """Refresh mobile session tokens (unauthenticated — uses refresh_token).

    Validates the refresh token and issues a new token pair.
    """
    request_id = str(uuid4())

    try:
        result = await service.refresh_mobile_session(
            tenant_id="",  # Resolved from device record
            device_id=body.device_id,
            refresh_token=body.refresh_token,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@router.post("/push")
async def send_push(
    body: SendPushRequest,
    user: AuthenticatedUser = Depends(require_auth),
    service: MobileService = Depends(_get_mobile_service),
) -> dict[str, Any]:
    """Send a push notification to a user's devices.

    Requires ``mobile:execute`` permission.
    """
    request_id = str(uuid4())

    if not check_permission(user, "mobile", "execute"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: mobile:execute required",
        )

    await service.send_push_notification(
        tenant_id=user.tenant_id,
        user_id=body.user_id,
        notification=body.notification,
    )

    audit = _audit_event(
        "mobile.push.sent", "push_notification", None,
        {"target_user_id": body.user_id, "title": body.notification.title},
        user=user,
    )
    logger.info(
        "Push notification sent",
        extra={
            "request_id": request_id,
            "tenant_id": user.tenant_id,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": {"message": "Notification sent"},
        "meta": _meta(request_id=request_id),
    }


@router.post("/sync")
async def sync_offline(
    body: SyncOfflineRequest,
    user: AuthenticatedUser = Depends(require_auth),
    service: MobileService = Depends(_get_mobile_service),
) -> dict[str, Any]:
    """Synchronise offline-queued actions from a mobile device.

    Processes actions idempotently using provided idempotency keys.
    """
    request_id = str(uuid4())

    result = await service.sync_offline_actions(
        tenant_id=user.tenant_id,
        user=user,
        actions=body.actions,
    )

    audit = _audit_event(
        "mobile.sync.completed", "mobile_sync", None,
        {"processed": result.processed, "failed": result.failed},
        user=user,
    )
    logger.info(
        "Offline sync completed",
        extra={
            "request_id": request_id,
            "tenant_id": user.tenant_id,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": result.model_dump(),
        "meta": _meta(request_id=request_id),
    }


@router.get("/devices")
async def list_devices(
    user: AuthenticatedUser = Depends(require_auth),
    service: MobileService = Depends(_get_mobile_service),
) -> dict[str, Any]:
    """List all registered mobile devices for the authenticated user."""
    request_id = str(uuid4())

    sessions = await service.get_device_sessions(
        tenant_id=user.tenant_id,
        user_id=user.id,
    )

    return {
        "data": [s.model_dump(mode="json") for s in sessions],
        "meta": _meta(request_id=request_id, pagination={"total": len(sessions)}),
    }


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(
    device_id: str,
    user: AuthenticatedUser = Depends(require_auth),
    service: MobileService = Depends(_get_mobile_service),
) -> None:
    """Revoke a registered mobile device session.

    Only the device owner or a user with ``mobile:admin`` can revoke.
    """
    try:
        await service.revoke_device(
            tenant_id=user.tenant_id,
            user=user,
            device_id=device_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    audit = _audit_event(
        "mobile.device.revoked", "mobile_device", device_id,
        {"device_id": device_id},
        user=user,
    )
    logger.info(
        "Mobile device revoked",
        extra={
            "request_id": str(uuid4()),
            "tenant_id": user.tenant_id,
            "device_id": device_id,
            "audit_id": str(audit.id),
        },
    )
