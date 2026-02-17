"""Tests for the SecretsManager exception hierarchy."""

from __future__ import annotations

import pytest

from app.secrets.exceptions import (
    CertificateError,
    RotationError,
    SecretAccessDeniedError,
    SecretNotFoundError,
    SecretsManagerError,
    VaultConnectionError,
)


class TestExceptionHierarchy:
    """Verify all custom exceptions inherit from SecretsManagerError."""

    @pytest.mark.parametrize(
        "exc_class",
        [
            SecretNotFoundError,
            SecretAccessDeniedError,
            VaultConnectionError,
            RotationError,
            CertificateError,
        ],
    )
    def test_exception_inherits_from_base(self, exc_class: type) -> None:
        """Every SDK exception must be a subclass of SecretsManagerError."""
        assert issubclass(exc_class, SecretsManagerError)

    def test_base_is_exception(self) -> None:
        """SecretsManagerError itself must inherit from Exception."""
        assert issubclass(SecretsManagerError, Exception)


class TestExceptionMessages:
    """Verify exceptions carry proper error messages and details."""

    def test_secret_not_found_message(self) -> None:
        exc = SecretNotFoundError("my/path", tenant_id="t-123")
        assert "my/path" in str(exc)
        assert exc.details["path"] == "my/path"
        assert exc.details["tenant_id"] == "t-123"

    def test_secret_access_denied_message(self) -> None:
        exc = SecretAccessDeniedError("db/creds", tenant_id="t-456")
        assert "db/creds" in str(exc)
        assert exc.details["path"] == "db/creds"
        assert exc.details["tenant_id"] == "t-456"

    def test_vault_connection_error_message(self) -> None:
        exc = VaultConnectionError("timeout")
        assert "timeout" in str(exc)

    def test_vault_connection_error_default_message(self) -> None:
        exc = VaultConnectionError()
        assert "Unable to connect to Vault" in str(exc)

    def test_rotation_error_message(self) -> None:
        exc = RotationError("api/key", reason="version conflict")
        assert "api/key" in str(exc)
        assert exc.details["reason"] == "version conflict"

    def test_certificate_error_message(self) -> None:
        exc = CertificateError("*.example.com", reason="expired CA")
        assert "*.example.com" in str(exc)
        assert exc.details["common_name"] == "*.example.com"
        assert exc.details["reason"] == "expired CA"

    def test_base_error_details_default_empty(self) -> None:
        exc = SecretsManagerError("boom")
        assert exc.details == {}
