# ADR-001: API Response Format

> **Status**: ACCEPTED
> **Date**: 2026-02-14
> **Decision**: All API responses follow a consistent envelope format.

## Context

Multiple agents build different API endpoints. Without a standard response format, frontend agents and consumers face inconsistent data shapes, making integration fragile.

## Decision

All API responses MUST use this envelope format:

### Success Response

```json
{
  "data": { ... },
  "meta": {
    "request_id": "uuid",
    "timestamp": "ISO-8601",
    "pagination": {
      "total": 100,
      "limit": 20,
      "offset": 0,
      "has_more": true
    }
  }
}
```

### Error Response

```json
{
  "errors": [
    {
      "code": "VALIDATION_ERROR",
      "message": "Human-readable description",
      "field": "email",
      "details": { ... }
    }
  ],
  "meta": {
    "request_id": "uuid",
    "timestamp": "ISO-8601"
  }
}
```

### Canonical Code Pattern (COPY THIS)

```python
from pydantic import BaseModel
from typing import Any, Optional, List
from datetime import datetime
import uuid

class PaginationMeta(BaseModel):
    total: int
    limit: int
    offset: int
    has_more: bool

class ResponseMeta(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    pagination: Optional[PaginationMeta] = None

class APIResponse(BaseModel):
    data: Any
    meta: ResponseMeta = Field(default_factory=ResponseMeta)

class ErrorDetail(BaseModel):
    code: str
    message: str
    field: Optional[str] = None
    details: Optional[dict] = None

class ErrorResponse(BaseModel):
    errors: List[ErrorDetail]
    meta: ResponseMeta = Field(default_factory=ResponseMeta)
```

### Anti-Patterns (DO NOT DO THIS)

```python
# WRONG: Returning raw data without envelope
return {"agents": [...]}

# WRONG: Inconsistent error format
return {"error": "something went wrong"}

# WRONG: Missing request_id
return {"data": {...}}
```

## Consequences

- All consumers can rely on consistent response shapes
- Request IDs enable end-to-end tracing
- Pagination is always in the same location
- Error handling is uniform across all endpoints
