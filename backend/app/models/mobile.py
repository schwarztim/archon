"""Pydantic models for Mobile SDK backend services."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MobilePlatform(str, Enum):
    """Supported mobile platforms."""

    IOS = "ios"
    ANDROID = "android"


class DeviceRegistration(BaseModel):
    """Request payload for registering a mobile device."""

    platform: MobilePlatform
    device_name: str = Field(..., min_length=1, max_length=255)
    push_token: str = Field(default="", max_length=4096)
    biometric_capable: bool = False


class DeviceSession(BaseModel):
    """Persisted mobile device session."""

    device_id: str
    user_id: str
    tenant_id: str
    platform: MobilePlatform
    device_name: str = ""
    last_active: datetime | None = None
    push_enabled: bool = False
    biometric_enrolled: bool = False
    created_at: datetime | None = None


class MobileAuthResult(BaseModel):
    """Authentication result returned to mobile clients."""

    access_token: str
    refresh_token: str
    expires_in: int = Field(default=900, description="Token lifetime in seconds")
    device_id: str = ""
    mfa_required: bool = False


class PushNotification(BaseModel):
    """Push notification payload for APNs/FCM delivery."""

    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(default="", max_length=4096)
    data: dict[str, Any] = Field(default_factory=dict)
    priority: str = Field(default="normal", pattern=r"^(normal|high)$")
    badge_count: int | None = None


class OfflineAction(BaseModel):
    """An action queued while the device was offline."""

    action_type: str = Field(..., min_length=1, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    idempotency_key: str = Field(..., min_length=1, max_length=255)


class SyncResult(BaseModel):
    """Result of processing offline-queued actions."""

    processed: int = 0
    failed: int = 0
    conflicts: list[str] = Field(default_factory=list)


class BiometricProof(BaseModel):
    """Biometric authentication proof from a mobile device."""

    challenge: str = Field(..., min_length=1)
    signature: str = Field(..., min_length=1)
    device_id: str = Field(..., min_length=1)
    timestamp: datetime


__all__ = [
    "BiometricProof",
    "DeviceRegistration",
    "DeviceSession",
    "MobileAuthResult",
    "MobilePlatform",
    "OfflineAction",
    "PushNotification",
    "SyncResult",
]
