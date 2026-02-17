"""Settings API routes — platform configuration, feature flags, API keys, notifications."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field as PField

from app.interfaces.models.enterprise import AuthenticatedUser
from app.logging_config import get_logger
from app.middleware.auth import get_current_user
from app.middleware.rbac import require_permission

logger = get_logger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

# ── Default settings seed data ──────────────────────────────────────

_DEFAULT_SETTINGS: dict[str, dict[str, Any]] = {
    "general": {
        "platform_name": "Archon",
        "default_language": "en",
        "timezone": "UTC",
        "logo_url": "",
    },
    "authentication": {
        "sso_enabled": False,
        "session_timeout_minutes": 480,
        "password_min_length": 12,
        "password_require_uppercase": True,
        "password_require_numbers": True,
        "password_require_special": True,
        "mfa_enabled": False,
    },
    "notifications": {
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_from": "",
        "smtp_username": "",
        "slack_webhook_url": "",
        "events": {
            "agent_failure": True,
            "deployment": True,
            "security_alert": True,
        },
    },
    "api": {
        "rate_limit_rpm": 1000,
        "rate_limit_burst": 100,
        "webhook_endpoints": [],
    },
    "appearance": {
        "theme": "dark",
        "accent_color": "#8b5cf6",
        "compact_mode": False,
    },
}

_DEFAULT_FLAGS: list[dict[str, Any]] = [
    {"name": "experimental_agents", "description": "Enable experimental agent types", "enabled": False},
    {"name": "advanced_analytics", "description": "Enable advanced analytics dashboard", "enabled": False},
    {"name": "multi_model_routing", "description": "Enable multi-model LLM routing", "enabled": True},
    {"name": "auto_scaling", "description": "Enable automatic agent scaling", "enabled": False},
    {"name": "dark_launch", "description": "Enable dark launch testing mode", "enabled": False},
]

# In-memory stores keyed by tenant_id
_settings_store: dict[str, dict[str, Any]] = {}
_flags_store: dict[str, list[dict[str, Any]]] = {}
_api_keys_store: dict[str, list[dict[str, Any]]] = {}


def _get_tenant_settings(tenant_id: str) -> dict[str, Any]:
    """Return settings for a tenant, initializing defaults if needed."""
    if tenant_id not in _settings_store:
        import copy
        _settings_store[tenant_id] = copy.deepcopy(_DEFAULT_SETTINGS)
    return _settings_store[tenant_id]


def _get_tenant_flags(tenant_id: str) -> list[dict[str, Any]]:
    """Return feature flags for a tenant, initializing defaults if needed."""
    if tenant_id not in _flags_store:
        import copy
        _flags_store[tenant_id] = copy.deepcopy(_DEFAULT_FLAGS)
    return _flags_store[tenant_id]


def _get_tenant_api_keys(tenant_id: str) -> list[dict[str, Any]]:
    """Return API keys for a tenant."""
    if tenant_id not in _api_keys_store:
        _api_keys_store[tenant_id] = []
    return _api_keys_store[tenant_id]


# ── Helpers ─────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _audit_log(
    action: str,
    user: AuthenticatedUser,
    resource_type: str = "settings",
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Log an audit event for settings mutations."""
    logger.info(
        "settings_audit",
        action=action,
        user_id=user.id,
        tenant_id=user.tenant_id,
        resource_type=resource_type,
        resource_id=resource_id or "",
        details=details or {},
    )


# ── Request / Response schemas ──────────────────────────────────────


class SettingsUpdate(BaseModel):
    """Payload for updating platform settings."""

    general: dict[str, Any] | None = None
    authentication: dict[str, Any] | None = None
    notifications: dict[str, Any] | None = None
    api: dict[str, Any] | None = None
    appearance: dict[str, Any] | None = None


class FeatureFlagUpdate(BaseModel):
    """Payload for toggling a feature flag."""

    enabled: bool


class CreateAPIKeyRequest(BaseModel):
    """Payload for creating an API key."""

    name: str = PField(min_length=1, max_length=100)
    scopes: list[str] = PField(default_factory=lambda: ["read"])


class NotificationTestRequest(BaseModel):
    """Payload for sending a test notification."""

    channel: str = PField(description="Notification channel: 'email' or 'slack'")
    recipient: str = PField(default="", description="Email address or Slack channel")


# ── Routes ──────────────────────────────────────────────────────────


@router.get("")
async def get_settings(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get all platform settings for the current tenant."""
    settings_data = _get_tenant_settings(user.tenant_id)
    # Mask SMTP password — it lives in Vault
    notif = settings_data.get("notifications", {})
    if "smtp_password" in notif:
        notif["smtp_password"] = "********"

    return {
        "data": settings_data,
        "meta": _meta(),
    }


@router.put("")
async def update_settings(
    body: SettingsUpdate,
    user: AuthenticatedUser = Depends(require_permission("settings", "update")),
) -> dict[str, Any]:
    """Update platform settings for the current tenant."""
    request_id = str(uuid4())
    current = _get_tenant_settings(user.tenant_id)

    updates: dict[str, Any] = {}
    for section in ("general", "authentication", "notifications", "api", "appearance"):
        incoming = getattr(body, section, None)
        if incoming is not None:
            # Store SMTP password in Vault, not in settings
            if section == "notifications" and "smtp_password" in incoming:
                smtp_pwd = incoming.pop("smtp_password")
                if smtp_pwd and smtp_pwd != "********":
                    # In production: await secrets_mgr.put_secret(...)
                    logger.info(
                        "smtp_password_vault_store",
                        tenant_id=user.tenant_id,
                    )
            current[section].update(incoming)
            updates[section] = incoming

    _audit_log("settings.update", user, details={"sections": list(updates.keys())})

    return {
        "data": current,
        "meta": _meta(request_id=request_id),
    }


# ── Feature Flags ───────────────────────────────────────────────────


@router.get("/feature-flags")
async def list_feature_flags(
    user: AuthenticatedUser = Depends(require_permission("settings", "admin")),
) -> dict[str, Any]:
    """List all feature flags (admin only)."""
    flags = _get_tenant_flags(user.tenant_id)
    return {
        "data": flags,
        "meta": _meta(pagination={"total": len(flags), "limit": 100, "offset": 0}),
    }


@router.put("/feature-flags/{flag_name}")
async def toggle_feature_flag(
    flag_name: str,
    body: FeatureFlagUpdate,
    user: AuthenticatedUser = Depends(require_permission("settings", "admin")),
) -> dict[str, Any]:
    """Toggle a feature flag (admin only)."""
    request_id = str(uuid4())
    flags = _get_tenant_flags(user.tenant_id)

    for flag in flags:
        if flag["name"] == flag_name:
            flag["enabled"] = body.enabled
            _audit_log(
                "feature_flag.toggle",
                user,
                resource_type="feature_flag",
                resource_id=flag_name,
                details={"enabled": body.enabled},
            )
            return {
                "data": flag,
                "meta": _meta(request_id=request_id),
            }

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Feature flag '{flag_name}' not found",
    )


# ── API Keys ────────────────────────────────────────────────────────


@router.post("/api-keys")
async def create_api_key(
    body: CreateAPIKeyRequest,
    user: AuthenticatedUser = Depends(require_permission("settings", "create")),
) -> dict[str, Any]:
    """Create a new API key."""
    from app.models.settings import SettingsAPIKey

    request_id = str(uuid4())
    raw_key, prefix, key_hash = SettingsAPIKey.generate_key()

    key_record = {
        "id": str(uuid4()),
        "name": body.name,
        "key_prefix": prefix,
        "key_hash": key_hash,
        "scopes": body.scopes,
        "created_by": user.id,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "revoked": False,
    }

    _get_tenant_api_keys(user.tenant_id).append(key_record)

    _audit_log(
        "api_key.create",
        user,
        resource_type="api_key",
        resource_id=key_record["id"],
        details={"name": body.name, "scopes": body.scopes},
    )

    return {
        "data": {
            **key_record,
            "key": raw_key,  # Only shown once at creation time
        },
        "meta": _meta(request_id=request_id),
    }


@router.get("/api-keys")
async def list_api_keys(
    user: AuthenticatedUser = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List API keys for the current tenant."""
    keys = _get_tenant_api_keys(user.tenant_id)
    active_keys = [k for k in keys if not k.get("revoked")]
    page = active_keys[offset: offset + limit]
    # Never return key_hash to the client
    safe_keys = [{k: v for k, v in key.items() if k != "key_hash"} for key in page]

    return {
        "data": safe_keys,
        "meta": _meta(
            pagination={"total": len(active_keys), "limit": limit, "offset": offset},
        ),
    }


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    user: AuthenticatedUser = Depends(require_permission("settings", "delete")),
) -> dict[str, Any]:
    """Revoke an API key."""
    request_id = str(uuid4())
    keys = _get_tenant_api_keys(user.tenant_id)

    for key in keys:
        if key["id"] == key_id and not key.get("revoked"):
            key["revoked"] = True
            _audit_log(
                "api_key.revoke",
                user,
                resource_type="api_key",
                resource_id=key_id,
            )
            return {
                "data": {"id": key_id, "revoked": True},
                "meta": _meta(request_id=request_id),
            }

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"API key '{key_id}' not found or already revoked",
    )


# ── Notifications ───────────────────────────────────────────────────


@router.post("/notifications/test")
async def send_test_notification(
    body: NotificationTestRequest,
    user: AuthenticatedUser = Depends(require_permission("settings", "update")),
) -> dict[str, Any]:
    """Send a test notification via the specified channel."""
    request_id = str(uuid4())
    tenant_settings = _get_tenant_settings(user.tenant_id)
    notif = tenant_settings.get("notifications", {})

    if body.channel == "email":
        if not notif.get("smtp_host"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SMTP not configured",
            )
        # In production: send via SMTP using credentials from Vault
        result = {"channel": "email", "status": "sent", "recipient": body.recipient or notif.get("smtp_from", "")}

    elif body.channel == "slack":
        if not notif.get("slack_webhook_url"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Slack webhook not configured",
            )
        # In production: POST to Slack webhook URL
        result = {"channel": "slack", "status": "sent"}

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported channel: {body.channel}. Use 'email' or 'slack'.",
        )

    _audit_log(
        "notification.test",
        user,
        resource_type="notification",
        details={"channel": body.channel},
    )

    return {
        "data": result,
        "meta": _meta(request_id=request_id),
    }
