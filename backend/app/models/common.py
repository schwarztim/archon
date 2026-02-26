"""Common Pydantic response models shared across all API routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class StandardResponse(BaseModel, Generic[T]):
    """Standard API response envelope used by all endpoints.

    Wraps any response payload in a consistent structure with metadata
    for tracing, pagination, and versioning.

    Example::

        @router.get("/items/{item_id}", response_model=StandardResponse[Item])
        async def get_item(item_id: str) -> StandardResponse[Item]:
            item = await fetch_item(item_id)
            return StandardResponse(data=item)
    """

    data: T
    meta: dict[str, Any] = Field(
        default_factory=lambda: {
            "request_id": "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "data": {"id": "123", "name": "Example"},
                "meta": {
                    "request_id": "req_abc123",
                    "timestamp": "2025-02-25T10:00:00Z",
                },
            }
        }
    }


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response envelope."""

    data: list[T]
    meta: dict[str, Any] = Field(
        default_factory=lambda: {
            "request_id": "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total": 0,
            "page": 1,
            "page_size": 50,
        }
    )


class ErrorDetail(BaseModel):
    """Structured error detail for error responses."""

    code: str
    message: str
    field: str | None = None


class ErrorResponse(BaseModel):
    """Standard error response envelope."""

    error: ErrorDetail
    meta: dict[str, Any] = Field(
        default_factory=lambda: {
            "request_id": "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
