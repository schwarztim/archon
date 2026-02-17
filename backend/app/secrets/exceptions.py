"""Custom exceptions for the SecretsManager SDK."""

from __future__ import annotations


class SecretsManagerError(Exception):
    """Base exception for all secrets manager errors."""

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class SecretNotFoundError(SecretsManagerError):
    """Raised when a requested secret path does not exist."""

    def __init__(self, path: str, *, tenant_id: str = "") -> None:
        super().__init__(
            f"Secret not found: {path}",
            details={"path": path, "tenant_id": tenant_id},
        )


class SecretAccessDeniedError(SecretsManagerError):
    """Raised when the caller lacks permission to access a secret."""

    def __init__(self, path: str, *, tenant_id: str = "") -> None:
        super().__init__(
            f"Access denied for secret: {path}",
            details={"path": path, "tenant_id": tenant_id},
        )


class VaultConnectionError(SecretsManagerError):
    """Raised when the Vault backend is unreachable or unhealthy."""

    def __init__(self, message: str = "Unable to connect to Vault") -> None:
        super().__init__(message)


class RotationError(SecretsManagerError):
    """Raised when secret rotation fails."""

    def __init__(self, path: str, reason: str = "") -> None:
        super().__init__(
            f"Rotation failed for {path}: {reason}",
            details={"path": path, "reason": reason},
        )


class CertificateError(SecretsManagerError):
    """Raised when PKI certificate issuance fails."""

    def __init__(self, common_name: str, reason: str = "") -> None:
        super().__init__(
            f"Certificate issuance failed for {common_name}: {reason}",
            details={"common_name": common_name, "reason": reason},
        )


__all__ = [
    "CertificateError",
    "RotationError",
    "SecretAccessDeniedError",
    "SecretNotFoundError",
    "SecretsManagerError",
    "VaultConnectionError",
]
