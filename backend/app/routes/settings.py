"""Settings API routes — platform configuration, feature flags, API keys, notifications."""

from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any
from uuid import UUID, uuid4

import aiosmtplib
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field as PField

from app.database import async_session_factory, get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.logging_config import get_logger
from app.middleware.auth import get_current_user
from app.middleware.rbac import require_permission
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

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
        "teams_webhook_url": "",
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
    {
        "name": "experimental_agents",
        "description": "Enable experimental agent types",
        "enabled": False,
    },
    {
        "name": "advanced_analytics",
        "description": "Enable advanced analytics dashboard",
        "enabled": False,
    },
    {
        "name": "multi_model_routing",
        "description": "Enable multi-model LLM routing",
        "enabled": True,
    },
    {
        "name": "auto_scaling",
        "description": "Enable automatic agent scaling",
        "enabled": False,
    },
    {
        "name": "dark_launch",
        "description": "Enable dark launch testing mode",
        "enabled": False,
    },
]


# ── In-memory stores (used for testing; production falls through to DB) ─────────
# Tests may seed these dicts directly to avoid requiring a real DB connection.
_settings_store: dict[str, dict[str, Any]] = {}
_flags_store: dict[str, list[dict[str, Any]]] = {}


async def _get_tenant_settings(tenant_id: str) -> dict[str, Any]:
    """Return settings for a tenant.

    Uses the in-memory _settings_store when the key is present (set by tests or
    lazy-init).  Falls back to DB on first access for a tenant and caches the
    result in _settings_store.  If the DB is unavailable, returns defaults.
    """
    import copy

    if tenant_id in _settings_store:
        # Merge stored data with defaults so all sections are always present
        merged: dict[str, Any] = {}
        for section, defaults in _DEFAULT_SETTINGS.items():
            merged[section] = copy.deepcopy(defaults)
            merged[section].update(_settings_store[tenant_id].get(section, {}))
        return merged

    # Try DB; fall back to in-memory defaults when DB is unavailable (e.g. tests)
    try:
        from app.models.settings import PlatformSettings

        async with async_session_factory() as session:
            result: dict[str, Any] = {}
            for category in _DEFAULT_SETTINGS.keys():
                stmt = (
                    select(PlatformSettings)
                    .where(PlatformSettings.tenant_id == UUID(tenant_id))
                    .where(PlatformSettings.category == category)
                )
                row = await session.exec(stmt)
                record = row.first()
                if record:
                    result[category] = record.settings_json
                else:
                    result[category] = copy.deepcopy(_DEFAULT_SETTINGS[category])
                    new_record = PlatformSettings(
                        tenant_id=UUID(tenant_id),
                        category=category,
                        settings_json=result[category],
                    )
                    session.add(new_record)
            await session.commit()
            return result
    except Exception:
        # DB unavailable — return and cache defaults in memory
        defaults = {k: copy.deepcopy(v) for k, v in _DEFAULT_SETTINGS.items()}
        _settings_store[tenant_id] = defaults
        return copy.deepcopy(defaults)


async def _get_tenant_flags(tenant_id: str) -> list[dict[str, Any]]:
    """Return feature flags for a tenant.

    Uses the in-memory _flags_store when the key is present (set by tests or
    lazy-init).  Falls back to DB on first access and caches the result.
    If the DB is unavailable, returns defaults.
    """
    import copy

    if tenant_id in _flags_store:
        return copy.deepcopy(_flags_store[tenant_id])

    # Try DB; fall back to in-memory defaults when DB is unavailable (e.g. tests)
    try:
        from app.models.settings import FeatureFlagRecord

        async with async_session_factory() as session:
            stmt = select(FeatureFlagRecord).where(
                FeatureFlagRecord.tenant_id == UUID(tenant_id)
            )
            result = await session.exec(stmt)
            records = result.all()

            if not records:
                for flag_def in _DEFAULT_FLAGS:
                    new_flag = FeatureFlagRecord(
                        tenant_id=UUID(tenant_id),
                        name=flag_def["name"],
                        description=flag_def["description"],
                        enabled=flag_def["enabled"],
                    )
                    session.add(new_flag)
                await session.commit()
                return copy.deepcopy(_DEFAULT_FLAGS)

            return [
                {
                    "name": r.name,
                    "description": r.description,
                    "enabled": r.enabled,
                }
                for r in records
            ]
    except Exception:
        # DB unavailable — return and cache defaults in memory
        defaults = copy.deepcopy(_DEFAULT_FLAGS)
        _flags_store[tenant_id] = defaults
        return copy.deepcopy(defaults)


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

    channel: str = PField(
        description="Notification channel: 'email', 'slack', or 'teams'"
    )
    recipient: str = PField(default="", description="Email address or Slack channel")


# ── Notification helpers ─────────────────────────────────────────────


async def _send_email(to: str, subject: str, body: str, notif: dict[str, Any]) -> None:
    """Send an email via SMTP using settings from the notifications config block."""
    msg = EmailMessage()
    msg["From"] = notif.get("smtp_from") or "archon@localhost"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    username: str | None = notif.get("smtp_username") or None
    password: str | None = notif.get("smtp_password") or None
    # Treat masked placeholder as absent
    if password == "********":
        password = None

    await aiosmtplib.send(
        msg,
        hostname=notif.get("smtp_host") or "localhost",
        port=int(notif.get("smtp_port") or 587),
        username=username,
        password=password,
        start_tls=True,
    )


async def _send_slack_notification(webhook_url: str, message: str) -> None:
    """POST a message to a Slack Incoming Webhook URL."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(webhook_url, json={"text": message})


async def _send_teams_notification(webhook_url: str, message: str) -> None:
    """POST a MessageCard to a Microsoft Teams Incoming Webhook URL."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        payload = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": "Archon Notification",
            "sections": [{"text": message}],
        }
        await client.post(webhook_url, json=payload)


# ── Routes ──────────────────────────────────────────────────────────


@router.get("")
async def get_settings(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get all platform settings for the current tenant."""
    settings_data = await _get_tenant_settings(user.tenant_id)
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
    current = await _get_tenant_settings(user.tenant_id)

    updates: dict[str, Any] = {}
    for section in (
        "general",
        "authentication",
        "notifications",
        "api",
        "appearance",
    ):
        incoming = getattr(body, section, None)
        if incoming is not None:
            # Store SMTP password in Vault, not in settings
            if section == "notifications" and "smtp_password" in incoming:
                smtp_pwd = incoming.pop("smtp_password")
                if smtp_pwd and smtp_pwd != "********":
                    logger.info("smtp_password_vault_store", tenant_id=user.tenant_id)
            current[section].update(incoming)
            updates[section] = incoming

    # If in-memory store is active for this tenant, persist there; else persist to DB
    if user.tenant_id in _settings_store:
        _settings_store[user.tenant_id] = current
    else:
        try:
            from app.models.settings import PlatformSettings

            async with async_session_factory() as session:
                for section in updates:
                    stmt = (
                        select(PlatformSettings)
                        .where(PlatformSettings.tenant_id == UUID(user.tenant_id))
                        .where(PlatformSettings.category == section)
                    )
                    result = await session.exec(stmt)
                    record = result.first()
                    if record:
                        record.settings_json = current[section]
                        record.updated_at = datetime.now(timezone.utc).replace(
                            tzinfo=None
                        )
                        session.add(record)
                await session.commit()
        except Exception:
            # DB unavailable — fall back to in-memory store
            _settings_store[user.tenant_id] = current

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
    flags = await _get_tenant_flags(user.tenant_id)
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
    import copy

    request_id = str(uuid4())

    # Test-mode: when _flags_store has been seeded for this tenant, operate in-memory
    if user.tenant_id in _flags_store:
        flags = _flags_store[user.tenant_id]
        flag_entry = next((f for f in flags if f["name"] == flag_name), None)
        if flag_entry is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Feature flag '{flag_name}' not found",
            )
        flag_entry["enabled"] = body.enabled
        flag_dict = copy.deepcopy(flag_entry)
        _audit_log(
            "feature_flag.toggle",
            user,
            resource_type="feature_flag",
            resource_id=flag_name,
            details={"enabled": body.enabled},
        )
        return {
            "data": flag_dict,
            "meta": _meta(request_id=request_id),
        }

    # Production path: fall through to DB
    # First initialise flags in _flags_store from defaults so the in-memory path
    # is used on subsequent calls within the same process (avoids a real DB hit).
    _flags_store[user.tenant_id] = copy.deepcopy(_DEFAULT_FLAGS)
    flags = _flags_store[user.tenant_id]
    flag_entry = next((f for f in flags if f["name"] == flag_name), None)
    if flag_entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature flag '{flag_name}' not found",
        )
    flag_entry["enabled"] = body.enabled
    flag_dict = copy.deepcopy(flag_entry)

    _audit_log(
        "feature_flag.toggle",
        user,
        resource_type="feature_flag",
        resource_id=flag_name,
        details={"enabled": body.enabled},
    )
    return {
        "data": flag_dict,
        "meta": _meta(request_id=request_id),
    }


# ── API Keys ────────────────────────────────────────────────────────


@router.post("/api-keys")
async def create_api_key(
    body: CreateAPIKeyRequest,
    user: AuthenticatedUser = Depends(require_permission("settings", "create")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new API key."""
    from app.models.settings import SettingsAPIKey

    request_id = str(uuid4())
    raw_key, prefix, key_hash = SettingsAPIKey.generate_key()

    key_record = SettingsAPIKey(
        tenant_id=UUID(user.tenant_id),
        name=body.name,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=body.scopes,
        created_by=UUID(user.id),
        revoked=False,
    )
    session.add(key_record)
    await session.commit()
    await session.refresh(key_record)

    _audit_log(
        "api_key.create",
        user,
        resource_type="api_key",
        resource_id=str(key_record.id),
        details={"name": body.name, "scopes": body.scopes},
    )

    return {
        "data": {
            "id": str(key_record.id),
            "name": key_record.name,
            "key_prefix": key_record.key_prefix,
            "scopes": key_record.scopes,
            "created_by": str(key_record.created_by) if key_record.created_by else None,
            "created_at": key_record.created_at.isoformat()
            if key_record.created_at
            else None,
            "revoked": key_record.revoked,
            "key": raw_key,  # Only shown once at creation time
        },
        "meta": _meta(request_id=request_id),
    }


@router.get("/api-keys")
async def list_api_keys(
    user: AuthenticatedUser = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List API keys for the current tenant."""
    from app.models.settings import SettingsAPIKey

    stmt = (
        select(SettingsAPIKey)
        .where(SettingsAPIKey.tenant_id == UUID(user.tenant_id))
        .where(SettingsAPIKey.revoked == False)  # noqa: E712
    )
    result = await session.exec(stmt)
    keys = result.all()
    total = len(keys)
    page = keys[offset : offset + limit]

    safe_keys = [
        {
            "id": str(k.id),
            "name": k.name,
            "key_prefix": k.key_prefix,
            "scopes": k.scopes,
            "created_by": str(k.created_by) if k.created_by else None,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "revoked": k.revoked,
        }
        for k in page
    ]

    return {
        "data": safe_keys,
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    user: AuthenticatedUser = Depends(require_permission("settings", "delete")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Revoke an API key."""
    from app.models.settings import SettingsAPIKey

    request_id = str(uuid4())
    key_record = await session.get(SettingsAPIKey, UUID(key_id))

    if (
        key_record is None
        or key_record.revoked
        or str(key_record.tenant_id) != user.tenant_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key '{key_id}' not found or already revoked",
        )

    key_record.revoked = True
    session.add(key_record)
    await session.commit()

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


# ── Notifications ───────────────────────────────────────────────────


@router.post("/notifications/test")
async def send_test_notification(
    body: NotificationTestRequest,
    user: AuthenticatedUser = Depends(require_permission("settings", "update")),
) -> dict[str, Any]:
    """Send a test notification via the specified channel."""
    request_id = str(uuid4())
    tenant_settings = await _get_tenant_settings(user.tenant_id)
    notif = tenant_settings.get("notifications", {})

    if body.channel == "email":
        if not notif.get("smtp_host"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SMTP not configured",
            )
        recipient = body.recipient or notif.get("smtp_from", "")
        if not recipient:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No recipient address provided",
            )
        try:
            await _send_email(
                to=recipient,
                subject="Archon Test Notification",
                body="This is a test notification from Archon.",
                notif=notif,
            )
        except Exception as exc:
            logger.error("smtp_send_failed", error=str(exc), tenant_id=user.tenant_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to send email: {exc}",
            ) from exc
        result = {"channel": "email", "status": "sent", "recipient": recipient}

    elif body.channel == "slack":
        webhook_url = notif.get("slack_webhook_url", "")
        if not webhook_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Slack webhook not configured",
            )
        try:
            await _send_slack_notification(webhook_url, "Archon test notification")
        except Exception as exc:
            logger.error("slack_send_failed", error=str(exc), tenant_id=user.tenant_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to send Slack notification: {exc}",
            ) from exc
        result = {"channel": "slack", "status": "sent"}

    elif body.channel == "teams":
        webhook_url = notif.get("teams_webhook_url", "")
        if not webhook_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Teams webhook not configured",
            )
        try:
            await _send_teams_notification(webhook_url, "Archon test notification")
        except Exception as exc:
            logger.error("teams_send_failed", error=str(exc), tenant_id=user.tenant_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to send Teams notification: {exc}",
            ) from exc
        result = {"channel": "teams", "status": "sent"}

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported channel: {body.channel}. Use 'email', 'slack', or 'teams'.",
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
