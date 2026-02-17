# Golden Path 04: Authenticated Endpoint with RBAC

Create a FastAPI endpoint with Keycloak JWT auth, RBAC, tenant isolation, and audit logging.

## Prerequisites

```bash
export BASE=http://localhost:8000/api/v1
export TOKEN="eyJhbGciOiJSUzI1NiIs..."   # Valid Keycloak JWT
```

## Step 1: Define the Router

```python
from fastapi import APIRouter, Depends
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.app.auth.dependencies import get_current_user
from backend.app.auth.models import AuthenticatedUser
from backend.app.auth.rbac import check_permission
from backend.app.core.audit import audit_log
from backend.app.core.context import get_request_id
from backend.app.db.session import get_db
from backend.app.models.agent import Agent
from backend.app.schemas.agent import AgentListResponse

router = APIRouter(prefix="/api/v1", tags=["agents"])
```

## Step 2: Implement the Endpoint

```python
@router.get("/agents", response_model=dict)
async def list_agents(
    limit: int = 20, offset: int = 0,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List agents visible to the authenticated user's tenant."""
    check_permission(user, "agents:read", scope="workspace")
    query = (
        select(Agent)
        .where(Agent.tenant_id == user.tenant_id, Agent.deleted_at.is_(None))
        .order_by(Agent.created_at.desc())
        .offset(offset).limit(min(limit, 100))
    )
    agents = (await db.exec(query)).all()
    await audit_log(user, "agent.listed", "agent", None, {"count": len(agents)})
    return {
        "data": [AgentListResponse.from_orm(a) for a in agents],
        "meta": {
            "request_id": get_request_id(),
            "pagination": {"limit": limit, "offset": offset, "total": len(agents)},
        },
    }
```

## Step 3: Call the Endpoint

```bash
curl -s "$BASE/agents?limit=10&offset=0" -H "Authorization: Bearer $TOKEN"
```

**Response (200 OK):**

```json
{
  "data": [{"id": "a1b2c3d4-...", "name": "summariser-v1", "status": "draft"}],
  "meta": {
    "request_id": "c9bf9e57-...",
    "pagination": { "limit": 10, "offset": 0, "total": 1 }
  }
}
```

## What NOT to Do

```python
# WRONG: No authentication — anyone can call this endpoint
@router.get("/agents")
async def list_agents(db: AsyncSession = Depends(get_db)):
    agents = await db.exec(select(Agent))  # No tenant filter — data leak!
    return agents.all()  # No envelope format, no audit trail

# WRONG: Skipping RBAC — authenticated but not authorised
@router.get("/agents")
async def list_agents(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Missing: check_permission(user, "agents:read", scope="workspace")
    agents = await db.exec(select(Agent))  # Missing tenant filter
    return {"data": agents.all()}  # Missing: meta, pagination, audit_log
```

## Next Steps

- [01 — Create and Run Agent](./01-create-and-run-agent.md) · [05 — Vault Credential Access](./05-vault-credential-access.md)
