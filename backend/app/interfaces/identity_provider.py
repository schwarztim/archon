"""Abstract interface for enterprise identity and SSO."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.interfaces.models.enterprise import (
    AuthenticatedUser,
    GroupProfile,
    MFASetupResponse,
    SAMLRequest,
    UserProfile,
)


@runtime_checkable
class IdentityProvider(Protocol):
    """Contract for identity provider backends (e.g. Keycloak, Okta)."""

    async def validate_token(self, token: str) -> AuthenticatedUser:
        """Validate a bearer token and return the authenticated user."""
        ...

    async def get_user(
        self, user_id: str, tenant_id: str
    ) -> UserProfile:
        """Retrieve a user profile by ID, scoped to tenant."""
        ...

    async def create_user(
        self, user_data: dict, tenant_id: str
    ) -> UserProfile:
        """Provision a user via SCIM, scoped to tenant."""
        ...

    async def sync_group(
        self, group_data: dict, tenant_id: str
    ) -> GroupProfile:
        """Synchronise a group via SCIM, scoped to tenant."""
        ...

    async def initiate_saml_login(self, tenant_id: str) -> SAMLRequest:
        """Start a SAML authentication flow for the given tenant."""
        ...

    async def process_saml_response(
        self, saml_response: str
    ) -> AuthenticatedUser:
        """Process a SAML assertion and return the authenticated user."""
        ...

    async def setup_mfa(
        self, user_id: str, method: str
    ) -> MFASetupResponse:
        """Enrol a user in a new MFA method (e.g. totp, webauthn)."""
        ...

    async def verify_mfa(self, user_id: str, code: str) -> bool:
        """Verify an MFA code for a user. Return True if valid."""
        ...


__all__ = ["IdentityProvider"]
