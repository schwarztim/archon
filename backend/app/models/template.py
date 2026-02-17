"""Pydantic request/response models for the Template Library & Marketplace."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────


class TemplateDifficulty(str, Enum):
    """Difficulty levels for templates."""

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class TemplateStatus(str, Enum):
    """Lifecycle status of a template."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


# ── Manifests ────────────────────────────────────────────────────────


class CredentialManifest(BaseModel):
    """Describes a credential required by a template (Vault path only)."""

    name: str
    vault_path: str
    description: str = ""
    required: bool = True


class ConnectorManifest(BaseModel):
    """Describes a connector required by a template."""

    type: str
    name: str
    config_schema: dict[str, Any] = Field(default_factory=dict)
    required: bool = True


class ModelManifest(BaseModel):
    """Describes an LLM model used by a template."""

    provider: str
    model_id: str
    purpose: str = ""
    required: bool = True


# ── Category ─────────────────────────────────────────────────────────


class TemplateCategory(BaseModel):
    """A template category descriptor."""

    slug: str
    name: str
    description: str = ""
    icon: str = ""
    template_count: int = 0


# ── Filters ──────────────────────────────────────────────────────────


class TemplateFilter(BaseModel):
    """Filter criteria for listing templates."""

    category: str | None = None
    tags: list[str] | None = None
    difficulty: TemplateDifficulty | None = None
    min_rating: float | None = Field(default=None, ge=0.0, le=5.0)
    search_query: str | None = None
    status: TemplateStatus | None = None
    is_featured: bool | None = None


# ── Create / Update ──────────────────────────────────────────────────


class TemplateCreate(BaseModel):
    """Payload for creating a template."""

    name: str
    description: str | None = None
    category: str
    definition: dict[str, Any]
    tags: list[str] = Field(default_factory=list)
    difficulty: TemplateDifficulty = TemplateDifficulty.INTERMEDIATE
    is_featured: bool = False
    credential_manifests: list[CredentialManifest] = Field(default_factory=list)
    connector_manifests: list[ConnectorManifest] = Field(default_factory=list)
    model_manifests: list[ModelManifest] = Field(default_factory=list)


class TemplateUpdate(BaseModel):
    """Payload for partial template update."""

    name: str | None = None
    description: str | None = None
    category: str | None = None
    definition: dict[str, Any] | None = None
    tags: list[str] | None = None
    difficulty: TemplateDifficulty | None = None
    is_featured: bool | None = None
    credential_manifests: list[CredentialManifest] | None = None
    connector_manifests: list[ConnectorManifest] | None = None
    model_manifests: list[ModelManifest] | None = None


# ── Response models ──────────────────────────────────────────────────


class TemplateResponse(BaseModel):
    """Full template response model."""

    id: UUID
    name: str
    description: str | None = None
    category: str
    definition: dict[str, Any]
    tags: list[str] = Field(default_factory=list)
    difficulty: str = "intermediate"
    status: str = "draft"
    is_featured: bool = False
    usage_count: int = 0
    avg_rating: float = 0.0
    review_count: int = 0
    author_id: UUID
    tenant_id: str
    signature: str | None = None
    content_hash: str | None = None
    credential_manifests: list[CredentialManifest] = Field(default_factory=list)
    connector_manifests: list[ConnectorManifest] = Field(default_factory=list)
    model_manifests: list[ModelManifest] = Field(default_factory=list)
    forked_from: UUID | None = None
    created_at: datetime
    updated_at: datetime


class TemplatePage(BaseModel):
    """Paginated template list response."""

    items: list[TemplateResponse]
    total: int
    page: int
    page_size: int


# ── Rating ───────────────────────────────────────────────────────────


class TemplateRatingCreate(BaseModel):
    """Payload for rating a template."""

    rating: int = Field(ge=1, le=5)
    review: str | None = None


class TemplateRating(BaseModel):
    """Template rating/review response."""

    id: UUID
    template_id: UUID
    user_id: str
    tenant_id: str
    rating: int
    review: str | None = None
    created_at: datetime


# ── Install ──────────────────────────────────────────────────────────


class InstallConfig(BaseModel):
    """Configuration overrides provided during template install."""

    overrides: dict[str, Any] = Field(default_factory=dict)


class CredentialStatus(BaseModel):
    """Status of a required credential in the tenant Vault."""

    vault_path: str
    name: str
    available: bool


class InstalledTemplate(BaseModel):
    """Result of installing a template."""

    id: UUID
    template_id: UUID
    tenant_id: str
    installed_by: str
    installed_config: dict[str, Any] = Field(default_factory=dict)
    credential_status: list[CredentialStatus] = Field(default_factory=list)
    created_at: datetime


__all__ = [
    "ConnectorManifest",
    "CredentialManifest",
    "CredentialStatus",
    "InstallConfig",
    "InstalledTemplate",
    "ModelManifest",
    "TemplateCategory",
    "TemplateCreate",
    "TemplateDifficulty",
    "TemplateFilter",
    "TemplatePage",
    "TemplateRating",
    "TemplateRatingCreate",
    "TemplateResponse",
    "TemplateStatus",
    "TemplateUpdate",
]
