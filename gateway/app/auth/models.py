"""Auth models — user identity extracted from JWT/OIDC tokens."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GatewayUser(BaseModel):
    """Authenticated user identity extracted from Entra ID JWT."""

    oid: str = Field(description="Entra object ID (sub claim)")
    email: str = Field(default="", description="User email (upn or email claim)")
    name: str = Field(default="", description="Display name")
    groups: list[str] = Field(
        default_factory=list, description="Group memberships (group IDs or names)"
    )
    roles: list[str] = Field(default_factory=list, description="App roles")
    tenant_id: str = Field(default="", description="Entra tenant ID (tid claim)")
    is_dev: bool = Field(default=False, description="True when auth_dev_mode bypass is active")
