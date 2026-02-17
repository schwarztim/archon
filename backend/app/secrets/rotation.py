"""Secret rotation engine for automated credential lifecycle management."""

from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.secrets.exceptions import RotationError
from app.secrets.manager import VaultSecretsManager

logger = logging.getLogger(__name__)


class RotationPolicy(BaseModel):
    """Policy controlling how and when a secret should be rotated."""

    interval_days: int = Field(default=90, ge=1, description="Days between rotations")
    max_age_days: int = Field(default=365, ge=1, description="Maximum secret age before forced rotation")
    auto_rotate: bool = Field(default=True, description="Whether to rotate automatically")
    notify_before_days: int = Field(default=14, ge=0, description="Days before expiry to send notification")


class RotationResult(BaseModel):
    """Result of a secret rotation operation."""

    path: str
    old_version: int
    new_version: int
    rotated_at: datetime
    next_rotation: datetime


class SecretRotationEngine:
    """Engine that checks rotation policies and rotates secrets when due.

    Uses VaultSecretsManager for secret storage and an audit logger
    (currently ``logging``, will be replaced with AuditLog service)
    for tracking all rotation events.
    """

    def __init__(
        self,
        secrets_manager: VaultSecretsManager,
        audit_logger: Any = None,
    ) -> None:
        self._sm = secrets_manager
        self._audit = audit_logger or logger

    async def check_rotations(self, tenant_id: str) -> list[RotationResult]:
        """Check all secrets for a tenant and rotate any that are overdue.

        Returns a list of ``RotationResult`` for every secret that was
        rotated during this check cycle.
        """
        self._validate_tenant_id(tenant_id)
        results: list[RotationResult] = []

        secret_list = await self._sm.list_secrets("", tenant_id)
        now = datetime.now(timezone.utc)

        for meta in secret_list:
            try:
                data = await self._sm.get_secret(meta.path, tenant_id)
            except Exception:
                logger.warning(
                    "Failed to read secret during rotation check",
                    extra={"path": meta.path, "tenant_id": tenant_id},
                )
                continue

            policy_raw = data.get("_rotation_policy")
            if policy_raw is None:
                continue

            policy = RotationPolicy.model_validate(policy_raw)
            if not policy.auto_rotate:
                continue

            last_rotated_str = data.get("_rotated_at")
            if last_rotated_str:
                last_rotated = datetime.fromisoformat(last_rotated_str)
            else:
                last_rotated = meta.created_at

            age = now - last_rotated
            needs_rotation = (
                age >= timedelta(days=policy.interval_days)
                or age >= timedelta(days=policy.max_age_days)
            )

            if needs_rotation:
                result = await self.rotate_secret(
                    meta.path, tenant_id, reason="scheduled_rotation"
                )
                results.append(result)

        self._log_audit(
            "rotation_check_complete",
            tenant_id=tenant_id,
            details={"secrets_checked": len(secret_list), "rotated": len(results)},
        )
        return results

    async def rotate_secret(
        self, path: str, tenant_id: str, reason: str = "manual"
    ) -> RotationResult:
        """Rotate a specific secret by generating a new value and writing it.

        Raises ``RotationError`` if the secret cannot be read or written.
        """
        self._validate_tenant_id(tenant_id)

        try:
            current_data = await self._sm.get_secret(path, tenant_id)
        except Exception as exc:
            self._log_audit(
                "rotation_failed",
                tenant_id=tenant_id,
                details={"path": path, "reason": str(exc)},
            )
            raise RotationError(path, reason=f"Cannot read secret: {exc}") from exc

        old_version = current_data.get("_version", 1)
        secret_type = current_data.get("_type", "password")
        length = current_data.get("_length", 64)

        new_value = self._generate_secret_value(secret_type, length)
        now = datetime.now(timezone.utc)

        updated_data = {
            **current_data,
            "value": new_value,
            "_version": old_version + 1,
            "_rotated_at": now.isoformat(),
            "_rotation_reason": reason,
        }

        try:
            await self._sm.put_secret(path, updated_data, tenant_id)
        except Exception as exc:
            self._log_audit(
                "rotation_failed",
                tenant_id=tenant_id,
                details={"path": path, "reason": str(exc)},
            )
            raise RotationError(path, reason=f"Cannot write rotated secret: {exc}") from exc

        policy_raw = current_data.get("_rotation_policy", {})
        interval = policy_raw.get("interval_days", 90) if isinstance(policy_raw, dict) else 90
        next_rotation = now + timedelta(days=interval)

        result = RotationResult(
            path=path,
            old_version=old_version,
            new_version=old_version + 1,
            rotated_at=now,
            next_rotation=next_rotation,
        )

        self._log_audit(
            "secret_rotated",
            tenant_id=tenant_id,
            details={
                "path": path,
                "old_version": result.old_version,
                "new_version": result.new_version,
                "reason": reason,
                "next_rotation": result.next_rotation.isoformat(),
            },
        )

        return result

    async def schedule_rotation(
        self, path: str, tenant_id: str, policy: RotationPolicy
    ) -> None:
        """Attach a rotation policy to a secret.

        Writes ``_rotation_policy`` metadata into the secret's data so
        ``check_rotations`` can pick it up on the next cycle.
        """
        self._validate_tenant_id(tenant_id)

        try:
            data = await self._sm.get_secret(path, tenant_id)
        except Exception as exc:
            raise RotationError(path, reason=f"Cannot read secret: {exc}") from exc

        data["_rotation_policy"] = policy.model_dump()
        await self._sm.put_secret(path, data, tenant_id)

        self._log_audit(
            "rotation_policy_set",
            tenant_id=tenant_id,
            details={"path": path, "policy": policy.model_dump()},
        )

    @staticmethod
    def _generate_secret_value(secret_type: str, length: int = 64) -> str:
        """Generate a cryptographically random secret value.

        Supported types:
        - ``api_key``: URL-safe base64 token
        - ``password``: mixed-case alphanumeric with punctuation
        - ``certificate``: hex token (placeholder for real cert flows)
        """
        if length < 16:
            length = 16

        if secret_type == "api_key":
            return secrets.token_urlsafe(length)
        if secret_type == "certificate":
            return secrets.token_hex(length)

        # Default: password
        alphabet = string.ascii_letters + string.digits + string.punctuation
        return "".join(secrets.choice(alphabet) for _ in range(length))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_tenant_id(tenant_id: str) -> None:
        """Raise ValueError if tenant_id is missing or empty."""
        if not tenant_id:
            raise ValueError("tenant_id must not be None or empty")

    def _log_audit(
        self,
        action: str,
        *,
        tenant_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log an audit event for a rotation action."""
        extra = {
            "action": action,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **(details or {}),
        }
        if hasattr(self._audit, "info"):
            self._audit.info("SecretRotation: %s", action, extra=extra)
        else:
            logger.info("SecretRotation: %s", action, extra=extra)


__all__ = [
    "RotationPolicy",
    "RotationResult",
    "SecretRotationEngine",
]
