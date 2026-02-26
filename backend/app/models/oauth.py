"""SQLModel database model for OAuth 2.0 pending state storage."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.utcnow()


class OAuthPendingState(SQLModel, table=True):
    """Pending OAuth flow state — replaces the in-memory _pending_states dict."""

    __tablename__ = "oauth_pending_states"

    state: str = Field(primary_key=True)
    tenant_id: str
    connector_id: str
    provider_type: str
    redirect_uri: str
    code_verifier: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)


__all__ = ["OAuthPendingState"]
