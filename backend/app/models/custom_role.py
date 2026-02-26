"""Custom Role and Group-Role Mapping SQLModel tables.

``CustomRole`` is defined in ``app.models.rbac`` and re-exported here for
convenience.  Only ``GroupRoleMapping`` is introduced in this module.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

# Re-export CustomRole so callers can import from this module
from app.models.rbac import CustomRole  # noqa: F401


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class GroupRoleMapping(SQLModel, table=True):
    """Maps an IdP group OID to a platform role for a given tenant."""

    __tablename__ = "group_role_mappings"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    group_oid: str = Field(index=True)
    role_name: str
    created_at: datetime = Field(default_factory=_utcnow)


__all__ = [
    "CustomRole",
    "GroupRoleMapping",
]
