"""Pydantic models for SCIM 2.0 provisioning (RFC 7643 / 7644)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SCIMName(BaseModel):
    """SCIM user name component (RFC 7643 §4.1.1)."""

    formatted: str = ""
    familyName: str = ""
    givenName: str = ""


class SCIMEmail(BaseModel):
    """SCIM multi-valued email (RFC 7643 §4.1.2)."""

    value: str
    type: str = "work"
    primary: bool = True


class SCIMMeta(BaseModel):
    """SCIM resource metadata (RFC 7643 §3.1)."""

    resourceType: str = "User"
    created: datetime | None = None
    lastModified: datetime | None = None
    location: str = ""


class SCIMUser(BaseModel):
    """SCIM 2.0 User resource (RFC 7643 §4.1)."""

    schemas: list[str] = Field(
        default_factory=lambda: ["urn:ietf:params:scim:schemas:core:2.0:User"],
    )
    id: str = ""
    externalId: str = ""
    userName: str = ""
    name: SCIMName = Field(default_factory=SCIMName)
    displayName: str = ""
    emails: list[SCIMEmail] = Field(default_factory=list)
    active: bool = True
    groups: list[dict[str, str]] = Field(default_factory=list)
    meta: SCIMMeta = Field(default_factory=SCIMMeta)


class SCIMGroupMember(BaseModel):
    """Member reference inside a SCIM Group."""

    value: str
    display: str = ""
    ref: str = Field(default="", alias="$ref")

    model_config = {"populate_by_name": True}


class SCIMGroup(BaseModel):
    """SCIM 2.0 Group resource (RFC 7643 §4.2)."""

    schemas: list[str] = Field(
        default_factory=lambda: ["urn:ietf:params:scim:schemas:core:2.0:Group"],
    )
    id: str = ""
    externalId: str = ""
    displayName: str = ""
    members: list[SCIMGroupMember] = Field(default_factory=list)
    meta: SCIMMeta = Field(default_factory=lambda: SCIMMeta(resourceType="Group"))


class SCIMPatchOperation(BaseModel):
    """Single SCIM PATCH operation (RFC 7644 §3.5.2)."""

    op: str  # add | remove | replace
    path: str = ""
    value: Any = None


class SCIMPatchRequest(BaseModel):
    """SCIM PATCH request body (RFC 7644 §3.5.2)."""

    schemas: list[str] = Field(
        default_factory=lambda: ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
    )
    Operations: list[SCIMPatchOperation] = Field(default_factory=list)


class SCIMListResponse(BaseModel):
    """SCIM 2.0 ListResponse (RFC 7644 §3.4.2)."""

    schemas: list[str] = Field(
        default_factory=lambda: ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
    )
    totalResults: int = 0
    startIndex: int = 1
    itemsPerPage: int = 0
    Resources: list[dict[str, Any]] = Field(default_factory=list)


class SCIMError(BaseModel):
    """SCIM 2.0 error response (RFC 7644 §3.12)."""

    schemas: list[str] = Field(
        default_factory=lambda: ["urn:ietf:params:scim:api:messages:2.0:Error"],
    )
    status: str
    scimType: str = ""
    detail: str = ""


__all__ = [
    "SCIMEmail",
    "SCIMError",
    "SCIMGroup",
    "SCIMGroupMember",
    "SCIMListResponse",
    "SCIMMeta",
    "SCIMName",
    "SCIMPatchOperation",
    "SCIMPatchRequest",
    "SCIMUser",
]
